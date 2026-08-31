#!/usr/bin/env python3
# forgejo-runner/scripts/pick-heaviest-workflow.py
"""CLI: kies de zwaarste representatieve workflow uit historische runs.

Leest de Actions-enabled repositories uit trust-inventory.json (Task 6), haalt per
repository de historische runs op via de ForgejoClient uit Task 6 en schrijft de
zwaarste geslaagde run (langste duur) naar --out. De keuzelogica zelf staat IO-vrij
in pick_heaviest_workflow.py, zodat ze zonder instance testbaar is.
"""

import argparse
import json
import os
import sys

import pick_heaviest_workflow
from trust_scope import Unreadable
from trust_scope_cli import ForgejoClient


def _runs_voor(client, full_name):
    """Historische runs van een repository, defensief over de responsvorm.

    Forgejo levert /actions/runs doorgaans als dict met een lijst onder
    workflow_runs; een andere instance kan een kale lijst geven. Beide vormen
    worden ondersteund.

    Belangrijk: Forgejo levert `duration` als int64 NANOSECONDEN (Go time.Duration),
    niet als seconden. De keuzelogica werkt op seconden, dus elke run wordt hier
    genormaliseerd naar hele seconden — bij voorkeur uit started/stopped
    (gezaghebbende wandkloktijd), anders uit de nanoseconden-duration.
    """
    data = client._get(f"/repos/{full_name}/actions/runs", {"limit": 50})
    if isinstance(data, dict):
        runs = None
        for sleutel in ("workflow_runs", "runs", "data"):
            if isinstance(data.get(sleutel), list):
                runs = data[sleutel]
                break
        runs = runs or []
    elif isinstance(data, list):
        runs = data
    else:
        runs = []
    for run in runs:
        run["duration"] = _duur_seconden(run)
    return runs


def _duur_seconden(run):
    """Duur in hele seconden. Voorkeur voor started/stopped; anders de
    nanoseconden-duration omgerekend (Forgejo geeft int64-nanoseconden)."""
    secs = _duur_uit_tijdstempels(run)
    if secs > 0:
        return secs
    raw = run.get("duration")
    if isinstance(raw, dict):
        return int(raw.get("seconds", 0))
    if isinstance(raw, (int, float)):
        return int(raw // 1_000_000_000)
    return 0


def _duur_uit_tijdstempels(run):
    """Berekent de duur in seconden uit started/stopped als die er zijn.

    Ondersteunt RFC3339-tijdstempels; lukt het niet, dan 0 (de run telt dan niet
    mee als zwaarste, wat veiliger is dan een verzonnen piek).
    """
    from datetime import datetime
    start, stop = run.get("started"), run.get("stopped")
    if not (isinstance(start, str) and isinstance(stop, str)):
        return 0
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(stop.replace("Z", "+00:00"))
        secs = int((b - a).total_seconds())
        return secs if secs > 0 else 0
    except ValueError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True, help="trust-inventory.json uit Task 6")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        print("FORGEJO_TOKEN ontbreekt", file=sys.stderr)
        return 3

    with open(args.inventory, encoding="utf-8") as fh:
        inv = json.load(fh)
    repos = [r["full_name"] for r in inv.get("repositories", []) if r.get("has_actions")]

    client = ForgejoClient(os.environ.get("FORGEJO_URL", "https://git.jp-visser.nl"), token)
    runs_per_repo = {}
    for full_name in repos:
        try:
            runs_per_repo[full_name] = _runs_voor(client, full_name)
        except Unreadable as exc:
            print(f"waarschuwing: runs onleesbaar voor {full_name}: {exc}", file=sys.stderr)
            runs_per_repo[full_name] = []

    keuze = pick_heaviest_workflow.pick(runs_per_repo)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(keuze, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if keuze is None:
        print("geen geslaagde runs gevonden; geen keuze mogelijk", file=sys.stderr)
        return 1
    print("zwaarste: {repo} {workflow_id} run {run_id} = {duration_seconds}s".format(**keuze))
    return 0


if __name__ == "__main__":
    sys.exit(main())
