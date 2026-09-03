# forgejo-runner/scripts/pick_heaviest_workflow.py
"""Kiest de zwaarste representatieve workflow uit historische runs.

Zwaarst = de langste succesvol afgeronde run. Mislukte en lopende runs tellen
niet mee: hun duur zegt niets over de werkelijke piekbelasting.
"""

TERMINAAL_GESLAAGD = ("success", "completed")


def _duration_seconds(run):
    raw = run.get("duration")
    if isinstance(raw, dict):
        return int(raw.get("seconds", 0))
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def pick(runs_per_repo):
    beste = None
    for repo, runs in runs_per_repo.items():
        for run in runs:
            if str(run.get("status", "")).lower() not in TERMINAAL_GESLAAGD:
                continue
            duur = _duration_seconds(run)
            if beste is None or duur > beste["duration_seconds"]:
                beste = {
                    "repo": repo,
                    "workflow_id": run.get("workflow_id"),
                    "run_id": run.get("id"),
                    "duration_seconds": duur,
                }
    return beste
