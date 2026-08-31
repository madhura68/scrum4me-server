#!/usr/bin/env python3
"""Redigeer secrets uit `docker container inspect`-JSON.

Leest de inspect-JSON (een lijst containers) van stdin en schrijft dezelfde
structuur naar stdout met alle secretwaarden vervangen door <GEREDIGEERD>.

De inspect-uitvoer draagt `Config.Env` en het entrypoint-/argumentcommando; die
kunnen een RUNNER_REGISTRATION_TOKEN of vergelijkbaar geheim bevatten. Zonder
redactie belandt zo'n token in het bewijs. Twee mechanismen, samen fail-safe:

  1. env-vars met een secret-achtige sleutel (TOKEN/SECRET/PASSWORD/...) worden
     geredigeerd en hun waarde verzameld, net als waarden achter secret-flags in
     argumentlijsten;
  2. iedere verzamelde waarde wordt daarna overal in de geserialiseerde tekst
     vervangen, zodat hetzelfde token dat óók inline in het commando staat
     (bijv. `--token X`) eveneens verdwijnt.

Dit script is bewust conservatief: bij twijfel redigeert het liever te veel dan
een geheim door te laten.
"""
import json
import re
import sys

RED = "<GEREDIGEERD>"
SECRET_KEY = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|APIKEY|API_KEY|ACCESS_KEY)", re.I
)
SECRET_FLAG = re.compile(r"^--(token|secret|password|passwd|pass|api[-_]?key|apikey|key)$", re.I)
SECRET_FLAG_EQ = re.compile(
    r"^(--[A-Za-z0-9_-]*(?:token|secret|password|passwd|key)[A-Za-z0-9_-]*)=(.+)$", re.I
)

secret_values = set()


def note(value):
    # Alleen niet-triviale waarden verzamelen; te korte waarden zouden bij een
    # globale vervanging te veel legitieme tekst raken.
    if isinstance(value, str) and len(value) >= 4:
        secret_values.add(value)


def redact_env(cfg):
    env = cfg.get("Env")
    if not isinstance(env, list):
        return
    out = []
    for entry in env:
        if isinstance(entry, str) and "=" in entry:
            key, value = entry.split("=", 1)
            if SECRET_KEY.search(key):
                note(value)
                out.append(key + "=" + RED)
                continue
        out.append(entry)
    cfg["Env"] = out


def redact_args(seq):
    if not isinstance(seq, list):
        return seq
    out = []
    i = 0
    while i < len(seq):
        arg = seq[i]
        if isinstance(arg, str):
            m = SECRET_FLAG_EQ.match(arg)
            if m:
                note(m.group(2))
                out.append(m.group(1) + "=" + RED)
                i += 1
                continue
            if SECRET_FLAG.match(arg) and i + 1 < len(seq) and isinstance(seq[i + 1], str):
                note(seq[i + 1])
                out.append(arg)
                out.append(RED)
                i += 2
                continue
        out.append(arg)
        i += 1
    return out


def main():
    data = json.load(sys.stdin)
    containers = data if isinstance(data, list) else [data]
    for container in containers:
        if not isinstance(container, dict):
            continue
        cfg = container.get("Config")
        if isinstance(cfg, dict):
            redact_env(cfg)
            for key in ("Cmd", "Entrypoint"):
                if key in cfg:
                    cfg[key] = redact_args(cfg[key])
        if "Args" in container:
            container["Args"] = redact_args(container["Args"])
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    # Langste waarden eerst, zodat een deel-string niet eerst een langere breekt.
    for value in sorted(secret_values, key=len, reverse=True):
        text = text.replace(value, RED)
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
