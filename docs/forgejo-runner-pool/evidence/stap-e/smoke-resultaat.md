# Kern stap E — smoke-resultaat (max2)

**Datum:** 8 september 2026. **Runner:** `max2-forgejo-runner-02`. Procedure: `../stap-d/bring-up-runbook.md` §6.
Reikwijdte: één bewust groene en één bewust rode `workflow_dispatch`-job (géén volledige poolproef/paralleltest/reboottest — dat is stap F).

## Opzet
Tijdelijke workflows op `janpeter/scrum4me-shared` (in de trust-allowlist), commit `fcc1795`, `runs-on: ubuntu-latest`:
`smoke-green.yml` (`exit 0`) en `smoke-red.yml` (`exit 1`). Beide handmatig gedispatcht; runner-01 werd door JP gepauzeerd zodat de jobs op max2 landden. De smoke-workflows zijn na afloop weer verwijderd (`scrum4me-shared` commit `ffeff7a`).

## Resultaat — de kern van de proef
| Job | Forgejo terminale status | Controllerjournal |
|---|---|---|
| groen | run #62 `smoke` = **success** (`fcc1795`) | `cyclus: runner exit rc=0` → `cyclus: scrub ok=True` → volgende runner online |
| rood | run #63 `smoke` = **failure** (`fcc1795`) | `cyclus: runner exit rc=0` → `cyclus: scrub ok=True` → volgende runner online |

(Forgejo action-tasks-API op `janpeter/scrum4me-shared` + `docker ps`/Site-Admin bevestigden dat beide op `max2-forgejo-runner-02` liepen; er liep eerder ook een echte DigiPlein-job (#5607) succesvol op deze runner.)

## Conclusie
Precies het beoogde contrast (ontwerp §7.3 / migratieontwerp §8 stap E): het **runnerproces** eindigt in beide gevallen `rc=0` (`one-job` rondt de ene job af, gevolgd door een groene scrub en terug naar `WAITING`), terwijl alleen de **Forgejo-workflowuitslag** verschilt (success vs failure). De runner voert dus echte jobs uit, ruimt tussen jobs op, en komt schoon terug — kern stap E is aangetoond.
