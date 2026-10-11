# S1 — relatieve paden en `--env-file` in `docker compose config` (M52, R17 fase 1)

Datum 2026-10-11. Gemeten op de Mac van de orchestrator (Docker Compose 5.5.1), in een wegwerpmap; geen host, geen daemon, niets in de repo. Het bewijs op `max2` zelf is Gate G1 in fase 2b (de composeversie daar kan afwijken).

## Vraag

Het plan (`implementatieplan-n-stacks.md`, spike S1) eist twee dingen voordat T1 het compose-sjabloon parametriseert:

1. Met `docker compose -f <bundel>/compose.yaml -p <naam> --env-file <elders>/.env config` verwijzen de relatieve paden (`./allowed-job-images.txt`, `./runner-config.yml`) naar de bundelmap, niet naar de map van het env-bestand.
2. Met `--env-file` gezet en een ontbrekende verplichte variabele **faalt** `config`, en valt hij niet terug op de `.env` van de projectmap.

## Opzet

Een kopie van `forgejo-runner/compose.yaml` waarin de vier waarden het T1-patroon krijgen (`${STACK_TOKEN:?…}`, `${STACK_CONFIG:?…}`, `${STACK_BRIDGE:?…}`, `${STACK_VOLUME:?…}`), in een map `bundel/` met een `.env` die voor stack `02` alle waarden draagt; een tweede map `stack03/` met een eigen `.env` (de waarden van `-03`, absolute paden) en een dummy `runner-config.yml`. De runnerservice staat onder het profiel `cycle`; `config` toont hem alleen met `--profile cycle`.

## Uitkomst

| Aanroep | Uitkomst |
|---|---|
| `--profile cycle -f bundel/compose.yaml -p forgejo-runner-03 --env-file stack03/.env config` | exit 0; `./allowed-job-images.txt` wijst naar `bundel/` (de bundelmap, niet de map van het env-bestand); `STACK_CONFIG` en `STACK_TOKEN` (absoluut) wijzen naar `stack03/`; bridge `fr-dind1`; volume `forgejo-runner-03-dind-data`; netwerk `forgejo-runner-03_runner-control` |
| dezelfde aanroep met een env-bestand zonder `STACK_BRIDGE`, terwijl `bundel/.env` die waarde wél heeft | exit 1: `required variable STACK_BRIDGE is missing a value`; **geen terugval** op de `.env` van de projectmap |
| zonder `--env-file` (zoals de controller van stack `02` compose nu aanroept) | de `.env` van de projectmap wordt wél gebruikt; exit 0 |
| stack `02`-vorm, `STACK_CONFIG=./runner-config.yml` | lost op naar `bundel/runner-config.yml` |

## Gevolgen voor T1

- Beide vragen zijn bevestigd; `STACK_CONFIG` hoeft **niet** een absoluut pad per stack te zijn voor stack `02`: de relatieve vorm lost op naar de bundelmap. Voor `-03` is het absolute pad in de per-stack-map.
- Een test op `config` moet het profiel `cycle` meegeven, anders ontbreekt de runnerservice (en dus `STACK_CONFIG` en `STACK_TOKEN`) in de uitvoer.
- Een vergeten variabele faalt dus altijd, ook als de bundelmap een `.env` met alle waarden draagt: de `${VAR:?}`-vorm is hier de bescherming tegen een stil hergebruik van het volume van stack `02`.
