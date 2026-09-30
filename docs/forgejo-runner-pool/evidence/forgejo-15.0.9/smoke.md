# Smoke na de upgrade (5.3) — 30 september 2026

Repository `janpeter/scrum4me-shared` (in de trust-allowlist), tijdelijke workflow `.forgejo/workflows/smoke-green.yml` (`on: [workflow_dispatch]`, `runs-on: ubuntu-latest`, `run: echo "smoke groen"; exit 0`), toegevoegd en weer verwijderd via de contents-API op `main`.

| Run | Workflow | Trigger | Taak | Runner | Status |
|---|---|---|---|---|---|
| #89 | `smoke-green.yml` | `workflow_dispatch` | 10100 | `max2-forgejo-runner-02` | success |
| #90 | `ci.yml` | push (toevoegen van de smoke-workflow) | 10101 | `scrum4me-srv-runner` | success |
| #91 | `ci.yml` | push (verwijderen van de smoke-workflow) | — | — | success |

De vereiste smoke is run #89. Op `max2` volgde `cyclus: runner exit rc=0` → `cyclus: scrub ok=True` → `cyclus: runner gestart` (`venster/f5-max2-smoke.txt`). De twee push-runs waren een bijvangst van de commits op `main` en bewijzen hetzelfde protocol voor de legacy runner (`venster/f5-srv-smoke.txt`). De workflow bestaat niet meer (`venster/f5-smoke.txt`: 404 na verwijderen).

Eindstand: beide records `idle` op v12.10.1 (`runners-na.tsv`), geen open jobs.
