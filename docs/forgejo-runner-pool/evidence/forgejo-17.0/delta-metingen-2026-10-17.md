# Metingen voor de delta van 17 oktober 2026 (D6–D10)

Dit zijn read-only metingen op `max2` en via de Forgejo-API. Ze zijn gedaan op 17 oktober 2026 tussen 00:30 en 01:00 CEST (16 oktober 22:30–23:00 UTC), voor de tweede post-GO-delta van [implementatieplan-forgejo-17.0.md](../../implementatieplan-forgejo-17.0.md).

Op `max2` is niets gewijzigd, op twee handelingen na. JP droeg die op voor het trustincident van §5: Actions uit op `janpeter/MacSearch`, en de trust-unit herstarten.

Dit document bevat geen tokens en geen runner-UUID's. De runnerrecords staan er alleen met hun numerieke ID in.

## 1. Vorm van de pool (D6)

Runnerrecords, gelezen met `capture-forgejo-records.sh --scope global`. Hier staan alleen de kolommen zonder `uuid`:

```text
scope	id	name	status	version	ephemeral	labels
global	3	scrum4me-srv-runner	idle	v12.10.1	False	ubuntu-latest
global	6	max2-forgejo-runner-03	idle	v12.10.1	False	ubuntu-latest
global	5	max2-forgejo-runner-02	idle	v12.10.1	False	ubuntu-latest
```

Units op `max2` (`systemctl list-units 'forgejo-runner*'`), en de bundel die er draait:

```text
forgejo-runner-cycle.service active running
forgejo-runner-cycle@03.service active running
forgejo-runner-dind-guard.service active exited
forgejo-runner-trust.timer active waiting
BUNDLE_COMMIT cbc7c26d4061bc0438d59475ad00b1b4a057e428
```

Projectnaam en marker per stack (`grep` op beide `controller.toml`'s):

```text
/opt/forgejo-runner/controller.toml:16:project      = "forgejo-runner"
/opt/forgejo-runner/controller.toml:17:marker_path  = "/opt/forgejo-runner/state/cycle-op.marker"
/opt/forgejo-runner-stacks/03/controller.toml:16:project      = "forgejo-runner-03"
/opt/forgejo-runner-stacks/03/controller.toml:17:marker_path  = "/opt/forgejo-runner-stacks/03/state/cycle-op.marker"
/opt/forgejo-runner-stacks/03/controller.toml:18:env_file     = "/opt/forgejo-runner-stacks/03/.env"
```

Versies op `max2`: Docker 29.9.0, Compose 5.6.0. Op `scrum4me-server` staat ook Compose 5.6.0; het plan noemt 5.5.1 van 30 september, en stap 0.6 meet het opnieuw.

## 2. De offline-controle van de runnerstop (D8)

Gemeten terwijl op beide stacks een runner draaide en wachtte (eerste regel van §5):

```text
+ cd /opt/forgejo-runner
+ docker compose ps --profile cycle runner --format '{{.Name}} {{.State}}'
unknown flag: --profile
+ docker compose -p forgejo-runner-03 -f /opt/forgejo-runner/compose.yaml --env-file /opt/forgejo-runner-stacks/03/.env ps --profile cycle runner --format '{{.Name}} {{.State}}'
unknown flag: --profile
[1] docker compose --profile cycle ps runner --format "{{.Name}} {{.State}}"
rc=0                                   (geen uitvoer, terwijl de runner draait)
[2] docker compose --profile cycle ps -a --format "{{.Name}} {{.Service}} {{.State}}"
forgejo-runner-dind-1 dind running
forgejo-runner-runner-run-02db944a4465 runner running
rc=0
[3] docker ps -a --filter label=com.docker.compose.project=forgejo-runner --filter label=com.docker.compose.service=runner --format "{{.Names}} {{.State}} {{.Label "com.docker.compose.oneoff"}}"
forgejo-runner-runner-run-02db944a4465 running True
rc=0
[4] docker ps -a --filter label=com.docker.compose.project=forgejo-runner-03 --filter label=com.docker.compose.service=runner --format "{{.Names}} {{.State}}"
forgejo-runner-03-runner-run-ddd5716c96da running
rc=0
[neg] docker ps -a --filter label=com.docker.compose.project=forgejo-runner-99 --filter label=com.docker.compose.service=runner --format "{{.Names}} {{.State}}"
rc=0                                   (geen uitvoer: geen container met dat project)
```

Conclusie:
- De vorm uit het plan (`ps --profile cycle runner`) faalt.
- De vorm `--profile cycle ps runner` toont een draaiende runcontainer niet. De controller start de runner met `compose --profile cycle run --rm runner` (`cycle_adapters.py`), en zo'n eenmalige container valt buiten de servicefilter van `compose ps`.
- Een lege uitvoer van beide vormen bewijst dus niet dat er geen runner is.
- De labelfilter toont de draaiende runner van elke stack, en niets voor een project zonder container.
- Het 15.0.9-venster legde onder "compose ps runner (verwacht leeg)" een lege uitvoer vast (`evidence/forgejo-15.0.9/venster/f2-max2.txt`).

De vorm van de explicietere compose-aanroep voor stack `02` die 2.2 gebruikt:

```text
docker compose -p forgejo-runner -f /opt/forgejo-runner/compose.yaml --env-file /opt/forgejo-runner/.env ps --format "{{.Name}} {{.State}}"
forgejo-runner-dind-1 running
rc=0
```

## 3. Controle 1 en 2 uit "Een lopende job niet onderbreken" per stack (D7)

Beide runners waren idle. De laatste journalregels van beide units (`journalctl -u <unit> -n 4 -o cat`):

```text
time="2026-10-16T22:39:05Z" level=info msg="single task poller received no task from https://git.jp-visser.nl, trying again"
```

Aantal containers in DinD per stack: `docker compose -p <project> -f /opt/forgejo-runner/compose.yaml --env-file <env> exec -T dind docker -H tcp://127.0.0.1:2375 ps -q | wc -l`. Uitkomst: `0` voor `forgejo-runner` en `0` voor `forgejo-runner-03`.

## 4. R.4 met `NREC` (D6)

Het contractblok van R.4 is buiten de repo gedraaid tegen een lokale stub die drie runnerrecords teruggeeft. Alleen de basis-URL en het tokenpad zijn naar de stub omgezet; de controles zijn letterlijk die uit het plan.

```text
NREC='3' CONTRACT OK: 3 runners, 0 jobs
NREC='2' AssertionError: verwacht 2 runnerrecords, kreeg {'runners': [ …drie records… ]}
NREC='4' AssertionError: verwacht 4 runnerrecords, kreeg {'runners': [ …drie records… ]}
NREC=''  ValueError: invalid literal for int() with base 10: ''
NREC unset KeyError: 'NREC'
```

Ook gecontroleerd: `docker run -i -e NREC=…` brengt de waarde in de container, samen met een heredoc op stdin. Dat is gedraaid op de dev-engine van `max2` met `python:3.13-slim`, en de uitvoer was `NREC in container: 3`.

## 5. Trustincident van 16–17 oktober (D10)

Tijdlijn uit de journals van `forgejo-runner-trust.service` en beide controllers op `max2`, in CEST:

| Tijd | Gebeurtenis |
|---|---|
| 16 okt 06:02 en 12:01 | trustmeting groen met zachte afwijkingen |
| 16 okt 14:44 | `janpeter/MacSearch` aangemaakt: privé, alleen `main`, geen workflowmap, Actions aan (standaard) |
| 16 okt 18:02 | `HARD: janpeter/MacSearch: Actions staat aan maar de repository staat niet in de allowlist`, CLI-exit 20, verdict geïnvalideerd. Beide controllers loggen `trustgate ROOD: ok is niet true → geen nieuwe runners` |
| 16 okt 21:08 en 22:24 | `-03` en `-02` ronden hun laatste job af. Daarna start geen runner meer |
| 17 okt 00:08 | de unit staat op `failed` (start-limit) |
| 17 okt 00:36 | Actions uit op MacSearch (API, besluit JP). Daarna `reset-failed` en `start` van de trust-unit: `Result=success`, groen met zachte afwijkingen, `ok=True` |
| 17 okt 00:37:01 | beide controllers loggen `trustgate groen` |
| 17 okt 00:37:32 | beide loggen `cyclus: runner gestart` en melden zich bij Forgejo |

Hetzelfde patroon deed zich op 5 oktober voor met `janpeter/my-mods`, opgelost met commit `15947a1`. Het incident staat als ISS-18 bij product `max2`, fingerprint `max2:forgejo-runner-trust:new-repo-not-in-allowlist`.

## 6. De `hiderefs`-controle (D12, #14866)

**Mechanisme in de bron**, gelezen op Codeberg in `modules/git/git.go`:
- **v15.0.9:** `configSet("receive.hideRefs", "refs/pull/")`, op regel 308.
- **v17.0.0:** `configSet("receive.hideRefs", "")`, op regel 309.
- **Fix #14869 op `forgejo`:** `configUnsetAll("receive.hideRefs", "refs/pull/")` en daarna `configUnsetAll("receive.hideRefs", "")`, waarbij exit 5 wordt getolereerd. De v17-backport #14870 stond op 17 oktober nog open.

`configSet` schrijft met `git config --global` naar `$HOME/.gitconfig`, met `HOME` = `[git] HOME_PATH` (standaard `%(APP_DATA_PATH)s/home`).

**Productie, 17 oktober.** De exacte commando's uit 0.19, waarbij de functie uit het plan via `bash -s` op `scrum4me-server` is gedefinieerd:

```text
APP_DATA_PATH = /data/gitea
grep-exit=0
[refs/pull/]
exit=0
```

`/data/gitea/home/.gitconfig` is van `git:git` en heeft mode 644. `git config --file /bestaat-niet --get-all …` geeft exit 1. Daarom toetst de functie eerst of het bestand leesbaar is, anders zou een ontbrekend bestand als `GEEN` doorgaan. In de container zit git 2.52.0 en busybox `sh`.

**Proef op de dev-engine van `max2`.** Dit zijn wegwerpcontainers met label `dev.owner=mac`. De functie is letterlijk die uit het plan; alleen `docker` is `docker --context max2-dev`. Elke container draait sqlite met `INSTALL_LOCK=true`, en beide gebruiken hetzelfde benoemde volume, eerst 15.0.9 en daarna 17.0.0.

Images:
- `forgejo:15.0.9` met digest `sha256:91a5310c86934339e16bd06b6078aada836e3d8935b2d70f6598108cbfaed5d1`
- `forgejo:17.0.0` met digest `sha256:06d38310de496a10186d952bdad5ca764c153c8023ede8dfa0944c79a1dc5412`

```text
===== 1. Forgejo 15.0.9, vers volume
{"version":"15.0.9+gitea-1.22.0"}
[refs/pull/]
exit=0
===== 2. Forgejo 17.0.0 op hetzelfde volume (negatieve controle: #14866)
{"version":"17.0.0+gitea-1.22.0"}
[]
exit=0
===== 3. Toestand na de fix nagebootst: de twee unset-all-stappen van #14869
unset refs/pull/ exit=5
unset leeg exit=0
GEEN
exit=0
===== 4. Foutgeval: twee waarden (refs/pull/ en leeg)
[refs/pull/]
[]
exit=0
===== 5. Foutgeval: gitconfig onleesbaar (weggezet)
HIDEREFS ROOD: /data/gitea/home/.gitconfig onleesbaar
exit=2
===== 6. Foutgeval: container bestaat niet
Error response from daemon: No such container: fj17-hiderefs-bestaat-niet
exit=1
===== opruimen
einde
```

Na de proef waren er geen containers of volumes met label `dev.task=fj17-hiderefs` meer.

Wat de proef niet dekt: er was geen image met de echte fix. De experimentele 18.0-images zijn gebouwd op 16 oktober om 03:05, en #14869 is pas om 23:42 gemerged. Stap 3 voert daarom de twee commando's van de fix met de hand uit. R.4 draait de controle op het echte `V17`.

### 6a. `hiderefs` na delta-ronde 1 (F3)

De reviewer liet zien dat de eerste versie van de functie een fout in haar tweede `git config`-aanroep maskeerde: die aanroep stond in een pipeline, dus de exitcode van `sed` telde. De functie leest nu één keer met `--get-regexp`, controleert de exitcode van die aanroep, en formatteert pas daarna.

Wat daarna is gedraaid:
- de volumeproef hierboven (stap 1–6), opnieuw met de nieuwe functie: dezelfde uitkomsten als in de tabel hierboven;
- de exacte commando's van 0.19 op productie, opnieuw: `APP_DATA_PATH = /data/gitea`, `grep-exit=0`, `[refs/pull/]`, `exit=0`;
- de functietekst in de busybox-`sh` van de 17.0.0-image, met een opgezet bestand per geval (`docker run --rm` op de dev-engine van `max2`):

```text
refs/pull/ (15.0.9):               [refs/pull/] exit=0
leeg (17.0.0, #14866):             [] exit=0
afwezig (na fix #14869):           GEEN exit=0
twee waarden:                      [refs/pull/] [] exit=0
ongeldige config (git-fout):       fatal: bad config line 1 in file /data/gitea/home/.gitconfig HIDEREFS ROOD: git config exit 128 exit=2
bestand ontbreekt:                 HIDEREFS ROOD: /data/gitea/home/.gitconfig onleesbaar exit=2
```

## 7. De Forgejo-kant vóór de stop (D7, na delta-ronde 1, F1)

De bron van 15.0.9 voor `GET /admin/actions/runners/jobs` is `routers/api/v1/admin/runners.go`, `GetActionRunJobs`, dat `shared.GetActionRunJobs(ctx, 0, 0)` aanroept. Die functie (`routers/api/v1/shared/runners.go`) zoekt `ActionRunJob`'s met status `StatusWaiting` of `StatusRunning`, zonder filter op eigenaar of repository. Het antwoord bevat dus elke wachtende of lopende job in de hele forge. Een job die al aan een runner is toegewezen, telt als lopend.

Gedraaid vanaf de mac: de regels van het blok in 2.3 tot vóór `( set -e`, letterlijk, met alleen `/tmp/fj-17.0` vervangen door een scratchmap. Daarna stap 1 van 2.2 voor beide stacks, tegen productie, plus drie foutgevallen:

```text
0 []
stack 02 precheck exit=0
0 []
stack 03 precheck exit=0
1 ['running']                         (fixture: één job met status running)
fixture running exit=1
1 ['waiting']                         (fixture: één job met status waiting)
fixture waiting exit=1
curl: (22) The requested URL returned error: 401
ongeldig token exit=22
```
