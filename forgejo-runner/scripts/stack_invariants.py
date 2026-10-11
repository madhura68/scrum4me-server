#!/usr/bin/env python3
# forgejo-runner/scripts/stack_invariants.py
# Het statische deel van exit 66 van verify-stack.sh (R17 §6.1): wat vóór enige start
# van een extra stack te bewijzen valt. Per aangekondigde stack leest dit script de
# controller.toml met dezelfde loader als de controller (cycle_runtime.load_config) en
# de EFFECTIEVE waarden uit `docker compose config`, niet de envtekst. Daarna toetst
# het de invarianten tussen de stacks: uniek zijn projectnaam, bridge, volume,
# tokenpad, tokeninhoud en marker_path; gelijk zijn alle niet-STACK_*-sleutels van de
# per-stack-envs (image-pins, caps).
#
# Gebruik: stack_invariants.py --bundle MAP --stacks-dir MAP --stacks "02 03"
# Exit 0 groen, 66 stackinvariant geschonden, 2 gebruiksfout. Overtredingen staan op
# stderr, een per regel. Er worden nooit tokens, hashes of envwaarden geprint.
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cycle_runtime  # noqa: E402

TOKEN_TARGET = "/run/forgejo-runner-credentials/forgejo-token"
CONFIG_TARGET = "/etc/forgejo-runner/config.yml"
BRIDGE_OPT = "com.docker.network.bridge.name"
# De guard dekt `fr-dind+` (dind-guard.sh); een bridge buiten dat patroon (of boven de
# 15 tekens van IFNAMSIZ) zou buiten de firewallregel vallen.
BRIDGE_RE = re.compile(r"^fr-dind[0-9]+$")
BRIDGE_MAX = 15
_LOAD_FOUTEN = (OSError, ValueError, TypeError, AttributeError, KeyError)


def layout(bundle, stacks_dir, sid):
    """Waar de bestanden van stack <sid> horen te staan (R17 §5)."""
    m = bundle if sid == "02" else os.path.join(stacks_dir, sid)
    return {
        "map": m,
        "project": "forgejo-runner" if sid == "02" else f"forgejo-runner-{sid}",
        "env": os.path.join(m, ".env"),
        "token": os.path.join(m, "credentials", "forgejo-token"),
        "config": os.path.join(m, "runner-config.yml"),
        "marker": os.path.join(m, "state", "cycle-op.marker"),
    }


def compose_config(cfg, run=subprocess.run, timeout=60):
    """`docker compose config` zoals de controller compose aanroept, plus het profiel
    `cycle` (zonder dat ontbreekt de runnerservice en dus token- en configmount).
    Een schone omgeving: een in de shell van de operator geëxporteerde STACK_BRIDGE
    gaat voor op het env-bestand en zou een andere waarde tonen dan de controller ziet."""
    argv = ["docker", "compose", "-f", cfg.compose_file, "-p", cfg.project]
    if cfg.env_file:
        argv += ["--env-file", cfg.env_file]
    argv += ["--profile", "cycle", "config", "--format", "json"]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "DOCKER_CONFIG") if k in os.environ}
    cp = run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    if cp.returncode != 0:
        eerste = (cp.stderr or "").strip().splitlines()[:1]
        raise ValueError("docker compose config faalde: " + (eerste[0][:200] if eerste else f"exit {cp.returncode}"))
    return json.loads(cp.stdout)


def effective_values(doc):
    """Pakt de waarden op sleutel, nooit op positie in een lijst."""
    try:
        bridge = doc["networks"]["runner-control"]["driver_opts"][BRIDGE_OPT]
        volume = doc["volumes"]["dind-data"]["name"]
        mounts = {
            v["target"]: v["source"]
            for v in doc["services"]["runner"]["volumes"]
            if v.get("type") == "bind"
        }
        return {
            "project": str(doc["name"]),
            "bridge": str(bridge),
            "volume": str(volume),
            "token": str(mounts[TOKEN_TARGET]),
            "config": str(mounts[CONFIG_TARGET]),
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"effectieve compose-configuratie mist een veld: {exc!s}") from None


def parse_env(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for regel in fh:
            regel = regel.strip()
            if not regel or regel.startswith("#") or "=" not in regel:
                continue
            sleutel, _, waarde = regel.partition("=")
            sleutel = sleutel.strip()
            if sleutel.startswith("export "):
                sleutel = sleutel[len("export "):].strip()
            waarde = waarde.strip()
            if len(waarde) >= 2 and waarde[0] == waarde[-1] and waarde[0] in "'\"":
                waarde = waarde[1:-1]
            out[sleutel] = waarde
    return out


def _digest(pad):
    with open(pad, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _uniek(label, per_stack, overtredingen):
    gezien = {}
    for sid, waarde in per_stack.items():
        gezien.setdefault(waarde, []).append(sid)
    for waarde, sids in gezien.items():
        if len(sids) > 1:
            overtredingen.append(f"{label} is niet uniek: stack {' en '.join(sids)} delen {waarde}")


def check_stacks(bundle, stacks_dir, ids, run=subprocess.run):
    """Geeft de lijst overtredingen (leeg = groen)."""
    rp = os.path.realpath
    overtredingen = []
    gelezen = {}   # sid -> dict met project, bridge, volume, token, marker, env
    for sid in ids:
        lay = layout(bundle, stacks_dir, sid)
        try:
            cfg = cycle_runtime.load_config(os.path.join(lay["map"], "controller.toml"))
        except _LOAD_FOUTEN as exc:
            overtredingen.append(f"stack {sid}: controller.toml onleesbaar of ongeldig ({type(exc).__name__})")
            continue
        if cfg.project != lay["project"]:
            overtredingen.append(
                f"stack {sid}: projectnaam {cfg.project} wijkt af van de conventie {lay['project']}")
        if rp(cfg.compose_file) != rp(os.path.join(bundle, "compose.yaml")):
            overtredingen.append(
                f"stack {sid}: compose_file {cfg.compose_file} is niet het compose.yaml van de bundel "
                "(compose-bestanden worden nooit gekopieerd)")
        if sid == "02":
            env_ok = cfg.env_file == "" or rp(cfg.env_file) == rp(lay["env"])
        else:
            # Zonder --env-file valt compose terug op de .env van de projectmap: die van stack 02.
            env_ok = cfg.env_file != "" and rp(cfg.env_file) == rp(lay["env"])
        if not env_ok:
            overtredingen.append(f"stack {sid}: env_file in controller.toml wijst niet naar {lay['env']}")
        if rp(cfg.marker_path) != rp(lay["marker"]):
            overtredingen.append(f"stack {sid}: marker_path moet {lay['marker']} zijn (eigen state-map)")
        try:
            eff = effective_values(compose_config(cfg, run=run))
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            overtredingen.append(f"stack {sid}: {exc}")
            eff = None
        stand = {"project": cfg.project, "marker": rp(cfg.marker_path), "env": lay["env"]}
        if eff is not None:
            if not BRIDGE_RE.match(eff["bridge"]) or len(eff["bridge"]) > BRIDGE_MAX:
                overtredingen.append(
                    f"stack {sid}: bridge {eff['bridge']} past niet bij fr-dind<N> (max {BRIDGE_MAX} tekens): "
                    "buiten de guardwildcard fr-dind+")
            if rp(eff["token"]) != rp(lay["token"]):
                overtredingen.append(f"stack {sid}: tokenpad {eff['token']} ligt niet in de eigen map ({lay['token']})")
            if rp(eff["config"]) != rp(lay["config"]):
                overtredingen.append(f"stack {sid}: config {eff['config']} ligt niet in de eigen map ({lay['config']})")
            stand.update(bridge=eff["bridge"], volume=eff["volume"], token=rp(eff["token"]))
        gelezen[sid] = stand

    _uniek("projectnaam", {s: g["project"] for s, g in gelezen.items()}, overtredingen)
    _uniek("bridge", {s: g["bridge"] for s, g in gelezen.items() if "bridge" in g}, overtredingen)
    _uniek("volume", {s: g["volume"] for s, g in gelezen.items() if "volume" in g}, overtredingen)
    _uniek("tokenpad", {s: g["token"] for s, g in gelezen.items() if "token" in g}, overtredingen)
    _uniek("marker_path", {s: g["marker"] for s, g in gelezen.items()}, overtredingen)

    digests = {}
    for sid, g in gelezen.items():
        if "token" not in g:
            continue
        try:
            digests[sid] = _digest(g["token"])
        except OSError:
            overtredingen.append(f"stack {sid}: tokenbestand onleesbaar of afwezig ({g['token']})")
    # De tokeninhoud wordt via zijn digest vergeleken en nooit geprint: een eigen melding zonder waarde.
    per_digest = {}
    for sid, d in digests.items():
        per_digest.setdefault(d, []).append(sid)
    for sids in per_digest.values():
        if len(sids) > 1:
            overtredingen.append(f"tokeninhoud is niet uniek: stack {' en '.join(sids)} delen hetzelfde token")

    envs = {}
    for sid, g in gelezen.items():
        try:
            envs[sid] = {k: v for k, v in parse_env(g["env"]).items() if not k.startswith("STACK_")}
        except OSError:
            overtredingen.append(f"stack {sid}: env-bestand onleesbaar of afwezig ({g['env']})")
    if envs:
        ref_sid = next(iter(envs))
        for sid, env in envs.items():
            if sid == ref_sid:
                continue
            for sleutel in sorted(set(envs[ref_sid]) | set(env)):
                if envs[ref_sid].get(sleutel) != env.get(sleutel):
                    overtredingen.append(
                        f"sleutel {sleutel} verschilt tussen stack {ref_sid} en {sid} (alleen STACK_* mag per stack verschillen)")
    return overtredingen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__ or "")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--stacks-dir", required=True)
    ap.add_argument("--stacks", required=True, help='bijv. "02 03"')
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    ids = args.stacks.split()
    if "02" not in ids or len(set(ids)) != len(ids) or not all(re.fullmatch(r"[0-9]{2}", i) for i in ids):
        print("gebruik: --stacks vraagt unieke tweecijferige ids, inclusief 02", file=sys.stderr)
        sys.exit(2)
    overtredingen = check_stacks(args.bundle, args.stacks_dir, ids)
    for o in overtredingen:
        print(f"stackinvariant: {o}", file=sys.stderr)
    sys.exit(66 if overtredingen else 0)


if __name__ == "__main__":
    main()
