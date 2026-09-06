# Ontwerp — controller-entrypoint (dunne bring-up)

Status: concept voor review (delta-review met `mac:codex`).
Datum: 2026-09-06.
Reikwijdte: **stap D + de kern van stap E** uit `migratieontwerp.md` §8.
Product: `scrum4me-server` (canonieke bundel); doelhost van deze slice: **max2**.

## 1. Doel

De systemd-unit `forgejo-runner-cycle.service` start
`forgejo_runner_cycle.py --config /opt/forgejo-runner/controller.toml`, maar die
module is vandaag een **puur beslis-hart** (toestandsmachine §7.7/§7.9, 99
unittests) zonder CLI, main-loop, probes, config-loader of Docker-aansturing. Er
bestaat ook nog **geen** `controller.toml`. Zonder die runtime-schil kan stap D
("activeer de cyclecontroller") niet.

Deze slice bouwt de **dunne runtime-schil** die het bestaande beslis-hart aan de
buitenwereld koppelt, net genoeg om op max2:

1. de runner online te krijgen in Forgejo (stap D);
2. één bewust groene én één bewust rode testjob te draaien (beide procesexit `0`,
   terminale Forgejo-status verschilt) met een groene scrub ertussen (kern stap E);
3. netjes te stoppen op `SIGTERM` (systemd-citizen, reboot-vriendelijk).

Twee scope-besluiten van JP (2026-09-06) sturen dit ontwerp:

- **Dunne bring-up eerst** (niet de volledige §7.9-runtime).
- **Transport-only readiness-probe** (geen tweede hostcredential in de controller).

## 2. Niet-doelen (expliciet uitgesteld naar de follow-up)

Deze staan bewust NIET in deze slice; het beslis-hart ondersteunt ze al, de
adapters komen later:

- **assignment-nulbewijs / volwaardige `DRAINING`**: de twee Forgejo-side
  snapshots (assigned/running per runner-ID, §7.9) vergen API-toegang die de
  transport-only-keuze niet biedt. `controller.nulbewijs_ok` blijft dus `False`.
- **live per-cyclus trustgate**: de bestaande trustgate maakt geauthenticeerde
  Forgejo-API-calls (zie §6, M6). De controller draait die in deze slice NIET
  zelf; hij gate't op een bij deploy geproduceerde, groene verdict (§6.3). Een
  live per-cyclus trustgate mét credential is follow-up.
- **maintenance-record arming** (cross-host onderhoudsvenster, stap F).
- **`CREDENTIAL_ERROR`-detectie** (geauthenticeerde readiness-probe, 401/403).
- **cancel/redispatch** van een op/na-latch geaccepteerde job (§7.7).
- **terminale-Forgejo-jobstatus-correlatie** per job (vergt API-toegang); de
  slice beslist op de **procesexitcode** (§7.9 exitcodecontract).
- **`job_accepted`-detectie** via runnerlog-parsing (zie §7.3).

## 3. Uitgangspunten (gemeten)

- max2: Python **3.14.4** (`tomllib` aanwezig), Docker **Compose v2**, `curl`
  aanwezig; bereikbaar als `ssh janpeter@max2` (tailscale). Gemeten 2026-09-06.
- De unit draait system-`/usr/bin/python3` zonder venv ⇒ de **controller** gebruikt
  alleen stdlib: `tomllib`, `urllib.request`, `subprocess`, `signal`, `logging`,
  `time`, `json`, `sys`.
- Het beslis-hart `forgejo_runner_cycle.py` blijft **byte-identiek** op een dunne
  `__main__`-delegatie na (§4). De 99 bestaande tests blijven ongewijzigd groen.
- De gedeelde bundel is byte-identiek op beide hosts (§6.1 migratieontwerp). Deze
  slice wijzigt de bundel op twee plekken (compose `command`, §6.2; en voegt de
  controllerscripts toe); die wijzigingen zijn byte-identiek op beide hosts.
  Hostspecifiek zijn alleen de waarden in `controller.toml`.

## 4. Architectuur — ports & adapters

Het beslis-hart blijft puur; alle neveneffecten leven achter smalle interfaces
zodat ze in tests vervangbaar zijn en het hart onaangeraakt blijft.

| Bestand | Rol | Nieuw? |
|---|---|---|
| `scripts/forgejo_runner_cycle.py` | Puur beslis-hart. Krijgt onderaan enkel: `if __name__ == "__main__": from cycle_runtime import main; raise SystemExit(main())`. `SystemExit` is builtin en `main()` leest zelf `sys.argv` ⇒ **geen** extra import in het hart. Verder ongewijzigd. | bestaand + 2 regels |
| `scripts/cycle_runtime.py` | `main(argv=None)` (default `sys.argv[1:]`): config laden, adapters bedraden, de serialiseerde poll-loop, signal-handling, logging. | nieuw |
| `scripts/cycle_adapters.py` | De neveneffect-adapters achter interfaces: `TransportProbe`, `DindHealth`, `TrustVerdict`, `RunnerLifecycle`, `Scrub`, `Reconcile`, `Clock`. | nieuw |

`main` construeert de echte adapters en injecteert ze in een `Runtime`; tests
injecteren fakes. De unit-`ExecStart` blijft ongewijzigd naar
`forgejo_runner_cycle.py` wijzen.

> **M6-fix (B2 in de review):** de eerdere delegatie riep `main(sys.argv[1:])` aan
> zónder `sys` in het hart te importeren — een NameError bij elke start. `main()`
> leest nu zelf `sys.argv`; het hart heeft geen `sys` nodig.

## 5. Runtime-model — één geserialiseerde poll-loop

Eén thread, geen asyncio (afgewezen: meer oppervlak, moeilijker deterministisch
te testen; het beslis-hart is al synchroon). De loop tikt elke `poll_interval`
(default 1 s); de readiness-probe + gates draaien op de `retry`-cadans (30 s).

**Niet-blokkerend (M7-fix):** elke potentieel trage subprocess — image-pull, scrub
en het runner-child — draait als een `Popen` die de loop **niet-blokkerend pollt**
(`poll()`), zodat de 60 s-watchdog en de `SIGTERM`-flag in élke iteratie aan bod
komen. Korte subprocessen (DinD-health, versie-probe) krijgen een harde
subprocess-timeout. De controller doet zelf geen netwerk-API-calls (§6.3).

Per iteratie, in deze volgorde:

1. **Klok**: `now, wall = clock()` (`time.monotonic()`, `time.time()`).
2. **Readiness + gates (op de 30 s-cadans, gecacht ertussen)**:
   - transport-probe → `classify_probe(probe)` → `ReadinessClass`; onthoud de klasse
     als `laatste_readiness`; `event = loop.submit("readiness", {"klasse": klasse})`;
     `controller.on_event(event)`.
   - `gates_groen = trust_verdict_groen and dind_healthy`; zet `controller.gates_groen`.
     Trust en DinD zijn **gates**, geen readinessklasse (`classify_probe` gaat
     alleen over de Forgejo-bron).
3. **Watchdog**: `controller.tick(now, wall)` (commit een verlopen fence — dit is
   óók het fence-herstelpad, §7.5).
4. **Reconciliatie (eenmalig, vóór de eerste childstart)**: zie §6.1 stap 0.
5. **Start-conditie (B1-fix)**: start een child alleen als
   `controller.mag_child_starten` **én** `controller.state == State.WAITING` **én**
   `laatste_readiness is READY`. Dus **nooit** vanuit `SOURCE_WAIT`. Loopt er al
   een child → poll zijn exit niet-blokkerend.
6. **Slaap** `poll_interval`.

> **Waarom de extra start-condities (B1):** `mag_child_starten` (hart) is
> `fence is None and not drain_gevraagd and gates_groen and state in
> {WAITING, SOURCE_WAIT}` — het accepteert expliciet óók `SOURCE_WAIT` en toetst
> geen bevestigde readiness. Zou de schil daarop alleen afgaan, dan start hij bij
> koude start zodra trust+DinD groen zijn, vóór de eerste READY bevestigd is. Door
> `state == WAITING` te eisen (alleen bereikbaar via bevestigde READY + gates,
> `_on_readiness` regel ~330) én `laatste_readiness is READY` (ingetrokken bij elke
> afwijking) dwingt de schil de bevestigde transport-readiness af zonder het hart
> te wijzigen.

### 5.1 Overgang naar `WAITING`

Vanuit `SOURCE_WAIT` beweegt het hart naar `WAITING` zodra een **bevestigde**
`READY` (twee gelijke probes ≥ 5 s uiteen) samenvalt met `gates_groen` en geen
fence (`_on_readiness`, koude-startpad, regel ~330–333). De schil voedt daarvoor
readiness-events en zet `gates_groen`; hij start pas een child in `WAITING` (§5).

## 6. Adapters (dun)

Alle Docker-toegang tot de **inner** DinD loopt via `docker compose exec dind …`
(zelfde pad als `scrub-dind.sh`), zodat health, pre-pull en scrub consistent één
weg gebruiken en nooit op de host-`docker.sock` terugvallen (§7.5).

| Adapter | Implementatie (dun) | Uitkomst |
|---|---|---|
| `TransportProbe` | `urllib` `GET {forgejo.base_url}/api/v1/version`, timeout `probe_timeout`. **Onderscheidt** `HTTPError` (→ `status=code`) van `URLError`/timeout (→ `error=<str>`), zodat een HTTP 401/403 niet via `error` als SOURCE_WAIT wegvalt. | dict `{"kind":"general","error":<str\|None>,"status":<int\|None>,"schema_ok":<bool>}` voor `classify_probe`. `schema_ok` = JSON met veld `version`. Nooit `kind:"auth"` in deze slice. |
| `DindHealth` | `docker compose exec -T dind docker -H tcp://127.0.0.1:2375 info` (rc 0 = gezond), harde subprocess-timeout. Ook: `docker compose up -d dind` als DinD niet loopt. | bool. |
| `TrustVerdict` | **Lees** `trust_verdict_path` (JSON), gate op `ok == true` én bestandsleeftijd ≤ `trust_verdict_max_age` (§6.3). De controller draait de trustgate-CLI **niet** zelf. | bool (+ reden bij niet-groen/verouderd/afwezig). |
| `RunnerLifecycle` | start: `docker compose --profile cycle run --rm runner` (verse container; het `one-job --wait`-commando staat in compose, §6.2). Niet-blokkerende `Popen`; propageert de exitcode. stop: `SIGTERM` naar het proces, wacht ≤ `child_stop_grace` (afgestemd op de runner-`shutdown_timeout` van 3 m). | `Popen`; bij exit de returncode. |
| `Scrub` | bestaande `scrub-dind.sh` als niet-blokkerende `Popen`; exit 0 = schoon. | bool. |
| `Reconcile` | `docker compose ps`/`docker ps` gefilterd op de compose-projectlabels om achtergebleven beheerde runnercontainers te vinden (§6.1 stap 0). | lijst container-ID's. |
| `Clock` | `(time.monotonic(), time.time())`. | tuple. |

### 6.1 De cyclus (§7.9), dun

**Stap 0 — startup-reconciliatie (B3-fix), eenmalig vóór de eerste childstart:**
identificeer via de compose-projectlabels of er een **beheerde runnercontainer**
bestaat (achtergebleven na een SIGKILL/onschone stop; het ontbreken van een lokaal
`Popen` bewijst dat niet). Bestaat er één → **fail-closed**: geen start, alarm, tot
hij gecontroleerd is afgehandeld. DinD draait onafhankelijk (`restart: always`,
blijvend volume), dus bewijs daarna een schone DinD-beginstaat via `scrub-dind.sh`
+ het schoonbewijs (§7.9 stap 8) vóór de eerste start.

Wanneer daarna `state == WAITING` + `laatste_readiness is READY` (§5):

1. **trust-verdict** groen én vers (§6.3), anders §7.4;
2. **DinD-health** groen, anders §7.4;
3. **toegestane images**: parse `allowed-job-images.txt` in het **bestaande
   formaat** — sla lege regels en `#`-commentaar over, splits elke dataregel op
   `<digest>\t<bytes>`, valideer alleen de **digest** (`…@sha256:<64hex>`), en geef
   uitsluitend die digest als los argv-element aan `docker compose exec -T dind
   docker pull <digest>`. De groottekolom is voor `preflight.sh`, niet voor pull.
   Een ongeldige digest of pull-fout ⇒ §7.4 (geen start);
4. **start** exact één `docker compose --profile cycle run --rm runner` (het
   `one-job --wait`-commando komt uit compose, §6.2).

Daarna poll de schil de child-exit niet-blokkerend (§7.3).

### 6.2 `compose.yaml`: het one-job-commando vastleggen (M4-fix)

De runnerservice heeft nu **geen** `command`/`entrypoint`; `docker compose run
--rm runner` zou de image-default draaien (een profiel selecteert alleen de
service, het verandert de opdracht niet). Deze slice voegt aan de runnerservice
toe:

```yaml
    command: ["one-job", "--wait"]
```

Stap B valideerde al dat de gepinde Runner-12.10.1-image `one-job --wait`
accepteert; het config-pad wordt via de mount `…/config.yml` gevonden. **Bring-up-
verificatie (stap D):** `docker inspect` op de gepinde image om entrypoint + de
resulterende argv te bevestigen vóór productieactivatie; leg dat vast onder
`evidence/`.

### 6.3 De trustgate als deploy-verdict (M6-fix + ontwerpbesluit)

De bestaande `trust_scope_cli.py` is een **geauthenticeerde netwerkclient**: hij
vereist `--allowlist`, `--labels`, `--out` en `FORGEJO_TOKEN` (zonder token exit
`30`) en doet gepagineerde Forgejo-API-calls. Een controller die dat live draait
zou een API-credential nodig hebben — strijdig met de transport-only-keuze "geen
tweede credential in de controller".

**Besluit voor de dunne slice:** de **operator** draait bij deploy (stap D) de
bestaande CLI met token/labels/out en legt `trust-verdict.json` neer op
`trust_verdict_path`. De controller **leest** dat verdict en gate't op
`ok == true` én leeftijd ≤ `trust_verdict_max_age`; hij houdt zelf geen credential
en doet geen trust-API-calls. Een verouderd, ontbrekend of niet-groen verdict ⇒
`gates_groen=False` (§7.4). Gevolg + bewuste beperking: een repo-/allowlist-
wijziging tussen deploys wordt pas bij een nieuw deploy-verdict gezien; de **live
per-cyclus trustgate** (mét credential) is follow-up (§13). Dit staat los van de
readiness-probe en voegt geen readiness-credential toe.

## 7. Toestandsbedrading — hoe de schil het hart voedt

De schil muteert **nooit** `controller.state` rechtstreeks; hij voedt events en
leest `state`/`mag_child_starten`. Dit houdt de "geserialiseerde eventloop" intact.

### 7.1 Events die de schil indient

- `"readiness" {klasse}` — uit de transport-probe (elke 30 s).
- `"child_exit" {code}` — bij runner-exit; het hart → `SCRUBBING`.
- `"scrub_done" {ok}` — na `scrub-dind.sh`; het hart → `WAITING`/`QUARANTINED`.

### 7.2 Gates → `gates_groen`

`gates_groen = trust_verdict_groen and dind_healthy`, op de 30 s-cadans gezet.
Effect via het hart: alleen bij `gates_groen` kan `SOURCE_WAIT`/`QUARANTINED` →
`WAITING` en, met de start-condities uit §5, mag een child starten.

### 7.3 Child-levenscyclus en exitcode (§7.9-exitcodecontract)

`docker compose --profile cycle run --rm runner` propageert de exitcode van de
runnercontainer. De schil pollt niet-blokkerend; bij exit:
`submit("child_exit",{code})` → `SCRUBBING` → `scrub-dind.sh` →
`submit("scrub_done",{ok})`. Het hart beslist:

- `ok` én exit `0` → `WAITING` (volgende cyclus). Groene én rode workflow leveren
  beide exit `0`; de terminale Forgejo-status (groen/rood) wordt **buiten** de
  controller waargenomen (stap-E-bewijs), niet door de controller gecorreleerd.
- exit ≠ 0 (config/init/poller/runtime-fout) of scrub-fout → `QUARANTINED`;
  binnen dezelfde scrubroute niet heropenen (§7.9 stap 5). Een latere bevestigde
  `READY` + `gates_groen` heropent `QUARANTINED` wél via het hart (regel ~330).

**`job_accepted` uitgesteld**: het hart gaat `WAITING`→`RUNNING` pas op een
`job_accepted`-event; runnerlog-parsing daarvoor is bros en enablet de
(uitgestelde) cancel/redispatch. Zonder dat event blijft de zichtbare toestand
`WAITING`→`SCRUBBING`; de job draait en scrubt gewoon (`_on_child_exit` gaat
ongeacht de vorige state naar `SCRUBBING`). De runner draait sowieso tot
`one-job --wait` klaar is; er wordt geen job afgekapt. **Functioneel gevolg
(codex):** een fout die tijdens de job wordt bevestigd wordt zonder `RUNNING`-label
niet als `volgende_state` bewaard; de schil vertrouwt daarom voor de correctheid
op de start-condities (§5) en de reconciliatie (§6.1 stap 0), niet op het
`RUNNING`/`volgende_state`-spoor.

### 7.4 Gate-falen (dun, veilig)

- **trust-verdict niet groen/vers** of **DinD ongezond**: `gates_groen=False` +
  alarm + geen runnerstart. De veiligheidswerking (geen runner bij twijfel) is
  behouden; de toestand blijft `SOURCE_WAIT`/geblokkeerd. **Bewuste beperking:** de
  slice zet hier niet het `QUARANTINED`-label (het hart kent geen
  `trust→QUARANTINED`-overgang en het hart wordt niet aangepast). **Geen crash-loop:**
  de controller blijft draaien en pollt door; hij exit niet. Het volwaardige
  trust-`QUARANTINED`-label komt in de follow-up.
- **pre-pull/image-fout**: idem, geen start; alarm.

### 7.5 Fence-herstel gebeurt in het hart (geen herstart-tak)

Een transport-blip die de controller in `WAITING` fencet (→ `DRAINING`) herstelt
**vanzelf in het hart**, zonder nulbewijs en zonder een runtime-herstart:

- de 60 s-watchdog `tick` (regel ~360–379) commit een verlopen fence naar de
  zwaarste sinds latch waargenomen klasse en reset de bevestiging; bij herstelde
  transport is die klasse `SOURCE_WAIT`;
- daarna geven twee bevestigde `READY`-probes + `gates_groen` via de koude-startpad
  (regel ~330–333) weer `WAITING`.

Herstel duurt dus ~60 s (watchdog) + ~2 probes (~30–60 s). De runtime doet hier
niets bijzonders. (De eerdere "herstart bij gefencete impasse" is **verwijderd**:
hij berustte op de onjuiste premisse dat een fence alleen met nulbewijs wist —
regels 336–338 (bevestigde fout) en 377–379 (watchdog) wissen hem óók.) De enige
herstart is systemd's `Restart=on-failure` bij een echte processcrash.

## 8. `controller.toml` (schema)

```toml
[forgejo]
base_url = "https://git.jp-visser.nl"     # transport-probe target
probe_timeout_seconds = 5

[dind]
compose_file = "/opt/forgejo-runner/compose.yaml"
project      = "forgejo-runner"

[runner]
allowed_images_file = "/opt/forgejo-runner/allowed-job-images.txt"
child_stop_grace_seconds = 200            # ≈ runner-shutdown_timeout 3m + marge, < systemd TimeoutStopSec 300

[trust]
verdict_path = "/opt/forgejo-runner/trust-verdict.json"   # door de operator bij deploy geproduceerd
verdict_max_age_seconds = 86400                            # vers-eis

[docker]
subprocess_timeout_seconds = 30           # harde deadline op korte docker-calls (health/pull-init)

[cadence]
poll_interval_seconds = 1
retry_interval_seconds = 30               # readiness+gates-cadans

[log]
level = "INFO"
```

- **Geen** `confirm_seconds`/`fence_max_age_seconds` in config (MINOR 8-fix):
  `Confirmation` en `Fence` lezen de **moduleconstanten** `CONFIRM_SECONDS` (5) en
  `FENCE_MAX_AGE_SECONDS` (60); config zou die niet wijzigen. Tests versnellen via
  de **fake klok** (die de monotone tijd stuurt), niet via kortere constanten.
- Geen secret in het bestand; het runner-token is een **pad** dat de compose
  al `0600` read-only in de runnercontainer mount (§7.5). `controller.toml` wordt
  met echte hostwaarden in stap D geplaatst en is géén onderdeel van de
  byte-identieke bundel-hash.

## 9. Signal-handling / graceful stop (M7-fix)

`SIGTERM`/`SIGINT` (unit `KillSignal=SIGTERM`, `TimeoutStopSec=300`) zet een flag
die de niet-blokkerende loop élke iteratie leest; roep `controller.drain(now)`.
Dan:

- **geen child**: exit `0`.
- **child loopt**: stuur `SIGTERM` naar het `compose run`-proces (dat de runner
  zijn eigen `shutdown_timeout` van 3 m gunt), poll tot exit ≤ `child_stop_grace`
  (~200 s, binnen systemds 300 s). Laat het hart de child-exit via de normale
  `child_exit`→scrub-route eindigen; **exit `0` alleen na bevestigd child-weg**
  (container afwezig). Scrub-voor-exit is best-effort binnen het resterende budget;
  komt hij niet af, dan zorgt de reconciliatie bij de volgende start (§6.1 stap 0)
  voor de schone beginstaat.
- **child stopt niet op tijd**: geen schone-stopclaim; systemd `SIGKILL` na 300 s
  is een **onschone stop**, en de startup-reconciliatie (§6.1 stap 0) — niet
  "`SOURCE_WAIT` + gates" — maakt de volgende start veilig.

> De runnerpolicy heeft `timeout: 3h` en `shutdown_timeout: 3m` (`runner-config.policy.yml`).
> Een 3-uursjob past niet binnen systemds 300 s; deze slice belooft daarom **geen**
> gegarandeerde graceful afronding van een lopende job, maar wel een veilige
> volgende start via reconciliatie. (De eerdere claim "300 s dekt een job ruim" is
> verwijderd.)

## 10. Logging

Gestructureerde regels (`logging`, stdout → journald): runner-ID, cyclusnummer,
begin/eindtijd, toestand, exitcode, en geanonimiseerde tellingen. **Nooit** namen,
tokens of metadata die secrets kunnen bevatten (§7.9). Alarm-events uit het hart
(`alarm`, `fence_set`, `cancel_en_redispatch`) worden gelogd op `WARNING`; in deze
dunne slice is een alarm log-only (geen queue/Forgejo-sink).

## 11. Teststrategie

- **Beslis-hart**: de 99 bestaande tests blijven ongewijzigd draaien (regressiegate).
- **Runtime (nieuw)** `test_cycle_runtime_*.py`, stdlib `unittest`, met **fake
  adapters** (geïnjecteerd; geen echte Docker/Forgejo/subprocess), een **fake
  clock** en een gedreven loop (stap-voor-stap i.p.v. `sleep`). Dekking:
  1. koude start: gates groen + eerste (onbevestigde) READY → **géén** start;
     pas na bevestigde READY (state `WAITING`) → start (B1);
  2. `state`/`laatste_readiness`-start-conditie: nooit starten vanuit `SOURCE_WAIT`;
  3. start-stappen in de volgorde van `cycle_stappen()`;
  4. child exit `0` → scrub ok → `WAITING`; child exit ≠ 0 of scrub-fout →
     `QUARANTINED`;
  5. transport-fout → `SOURCE_WAIT`; herstel → `WAITING`; fence-blip → watchdog →
     `SOURCE_WAIT` → `WAITING`, **zonder** herstart (§7.5);
  6. trust-verdict niet groen / verouderd / afwezig → geen start, geen crash-loop;
  7. **startup-reconciliatie** (B3): achtergebleven beheerde runnercontainer →
     fail-closed geen start; schone begintoestand → wel door;
  8. **image-parser** (M5): echt bestandsformaat (`#`-comment + `digest\tbytes`) →
     alleen de digest aan pull; ongeldige digest → geen start;
  9. **stop-contract** (M7): `SIGTERM` → child krijgt SIGTERM; exit 0 alleen na
     bevestigd child-weg; child dat de grens overschrijdt → geen schone-stopclaim;
  10. **niet-blokkerend** (M7): een hangende pull/scrub blokkeert de watchdog en de
      SIGTERM-flag niet (fake Popen die "nog niet klaar" pollt);
  11. **RunnerLifecycle-argv** (M4): het gestarte commando bevat `one-job --wait`.
- **Config**: `controller.toml` laadt en valideert (ontbrekende sleutel → nette
  fout, geen stacktrace).
- **Integratie-smoke op max2** (stap D/E, handmatig via SSH, geen CI): deploy-
  verdict geplaatst; `docker inspect` bevestigt de runner-entrypoint/argv; DinD
  omhoog; controller start; runner online in Forgejo; één groene + één rode
  smoke-workflow; groene scrub; `SIGTERM` stopt schoon. Bewijs onder `evidence/`.
- `ruff` schoon; `shellcheck` op eventueel gewijzigde shell; secret-scan
  pre-commit hook actief.

## 12. Verificatie-commando's

```
cd forgejo-runner
python3 -m unittest discover -s tests -p 'test_*.py'   # hart + runtime
ruff check scripts/
```

## 13. Follow-up (na deze slice, buiten scope)

1. assignment-nulbewijs-adapter (Forgejo-API) → volwaardige `DRAINING` + in-place
   fence-herstel via de READY-recoverypad (naast het watchdog-pad).
2. **live per-cyclus trustgate** (mét credential) → vervangt het deploy-verdict
   (§6.3).
3. geauthenticeerde probe → echte `CREDENTIAL_ERROR`.
4. maintenance-record arming (stap F).
5. cancel/redispatch + `job_accepted`-detectie + terminale-status-correlatie.
6. trust-hardfout → echt `QUARANTINED`-label.

## 14. Risico's / open punten

- **Trustgate-deploy-verdict (§6.3)** is een ontwerpbesluit dat de transport-only-
  keuze doortrekt naar de trustgate; JP kan besluiten de controller tóch een
  credential + live trustgate te geven.
- **`compose run` + `command` (§6.2)** en de image-entrypoint/argv moeten in de
  max2-smoke met `docker inspect` bevestigd worden.
- **Stop van een lopende job**: een 3-uursjob wordt bij `SIGTERM` niet gegarandeerd
  gracefully afgerond binnen systemds 300 s; veiligheid komt van de reconciliatie,
  niet van een graceful-afrondgarantie.
- **`scrum4me-server` Python-versie** (stap G, byte-identieke bundel) moet
  `tomllib` (3.11+) hebben; te meten vóór stap G, niet in deze slice.

## Review record

Loop: delta-variant, één cross-model reviewer `mac:codex` (de spec is
claude-authored). Documentcommit bij ronde 1: `3e87342`.

### Ronde 1 — mac:codex — NO-GO (3 BLOCKER, 4 MAJOR, 1 MINOR)

Alle bevindingen geverifieerd tegen de boom en aanvaard:

- **B1** — lus start vóór bevestigde readiness (`mag_child_starten` accepteert
  `SOURCE_WAIT`). Fix: start-conditie eist `state == WAITING` én
  `laatste_readiness is READY`; nooit vanuit `SOURCE_WAIT` (§5).
- **B2** — `sys` ongebonden in de delegatie. Fix: `main()` leest zelf `sys.argv`;
  hart-`__main__` = `raise SystemExit(main())`, geen `sys`-import (§4).
- **B3** — herstart bewijst geen schone beginstaat. Fix: startup-reconciliatie
  (§6.1 stap 0) — achtergebleven beheerde runnercontainer → fail-closed; schone
  DinD-beginstaat bewijzen/scrubben vóór de eerste start; §9-claim "SOURCE_WAIT +
  gates vangt een onschone stop op" verwijderd.
- **M4** — `compose run` legt `one-job --wait` niet vast. Fix: `command:
  ["one-job","--wait"]` in compose (§6.2) + `docker inspect`-verificatie bij bring-up.
- **M5** — image-parser past niet op het bestandsformaat. Fix: skip comment/lege
  regels, split `digest\tbytes`, valideer/pull alleen de digest (§6.1 stap 3).
- **M6** — trustgate vereist `--labels/--out/FORGEJO_TOKEN` en doet live API-calls.
  Fix + besluit: controller leest een bij deploy geproduceerd, vers, groen
  `trust-verdict.json`; geen controllercredential, geen live trust-API (§6.3).
- **M7** — stop-/watchdogtermijnen niet afdwingbaar met blokkerende adapters +
  verkeerde termijnen. Fix: niet-blokkerende `Popen`-polling (pull/scrub/child),
  bounded subprocess-timeouts, `child_stop_grace` ≈ 3 m afgestemd op de
  runnerpolicy, exit 0 alleen na bevestigd child-weg (§5, §6, §8, §9).
- **MINOR 8** — config verandert hartconstanten niet. Fix: `confirm_seconds`/
  `fence_max_age_seconds` uit config; tests versnellen via de fake klok (§8, §11).
- **Correctie §7.5** — de "herstart bij gefencete impasse" berustte op een
  verkeerde premisse; de hart-watchdog herstelt de fence. Herstart-tak verwijderd.

Verdict ronde 1: **NO-GO**. Fixes toegepast; ronde 2 opnieuw naar `mac:codex`.
