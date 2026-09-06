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
  Forgejo-API-calls (§6.3, M6). De controller draait die in deze slice NIET zelf;
  hij gate't op een bij deploy geproduceerd, vers en gebonden verdict (§6.3). Een
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
  `time`, `json`, `sys`, `hashlib`.
- Het beslis-hart `forgejo_runner_cycle.py` blijft **byte-identiek** op een dunne
  `__main__`-delegatie na (§4). De 99 bestaande tests blijven ongewijzigd groen.
- De gedeelde bundel is byte-identiek op beide hosts (§6.1 migratieontwerp). Deze
  slice wijzigt de bundel op twee plekken (compose `command`, §6.2; en voegt de
  controllerscripts toe); byte-identiek op beide hosts. Hostspecifiek zijn alleen
  de waarden in `controller.toml` en het deploy-verdict.

## 4. Architectuur — ports & adapters

Het beslis-hart blijft puur; alle neveneffecten leven achter smalle interfaces
zodat ze in tests vervangbaar zijn en het hart onaangeraakt blijft.

| Bestand | Rol | Nieuw? |
|---|---|---|
| `scripts/forgejo_runner_cycle.py` | Puur beslis-hart. Krijgt onderaan enkel: `if __name__ == "__main__": from cycle_runtime import main; raise SystemExit(main())`. `SystemExit` is builtin en `main()` leest zelf `sys.argv` ⇒ **geen** extra import in het hart. Verder ongewijzigd. | bestaand + 2 regels |
| `scripts/cycle_runtime.py` | `main(argv=None)` (default `sys.argv[1:]`): config laden, adapters bedraden, de serialiseerde poll-loop, de twee runtime-preconditions (§5.2), signal-handling, logging. | nieuw |
| `scripts/cycle_adapters.py` | De neveneffect-adapters achter interfaces: `TransportProbe`, `DindHealth`, `TrustVerdict`, `RunnerLifecycle`, `Scrub`, `Reconcile`, `Clock`. | nieuw |

`main` construeert de echte adapters en injecteert ze in een `Runtime`; tests
injecteren fakes. De unit-`ExecStart` blijft ongewijzigd naar
`forgejo_runner_cycle.py` wijzen.

## 5. Runtime-model — één geserialiseerde poll-loop

Eén thread, geen asyncio (afgewezen: meer oppervlak, moeilijker deterministisch
te testen; het beslis-hart is al synchroon). De loop tikt elke `poll_interval`
(default 1 s); de readiness-probe + gates draaien op de `retry`-cadans (30 s).

**Niet-blokkerend (M7-fix):** elke potentieel trage cyclus-operatie — image-pull,
scrub en het runner-child — draait als een `Popen` die de loop **niet-blokkerend
pollt** (`poll()`), zodat de 60 s-watchdog en de `SIGTERM`-flag in élke iteratie
aan bod komen. De runtime houdt een register van **alle** actieve cyclus-Popens
bij (child, pull, scrub) t.b.v. het stopcontract (§9). Korte subprocessen
(DinD-health, versie-probe) krijgen een harde subprocess-timeout. De controller
doet zelf geen netwerk-API-calls (§6.3).

Per iteratie, in deze volgorde:

1. **Klok**: `now, wall = clock()` (`time.monotonic()`, `time.time()`).
2. **Readiness + gates (op de 30 s-cadans, gecacht ertussen)**:
   - transport-probe → `classify_probe(probe)` → `ReadinessClass`;
     `event = loop.submit("readiness", {"klasse": klasse})`; `controller.on_event(event)`.
   - **`readiness_confirmed`** (runtime-vlag, B1-fix): pas twee gelijke `READY`-probes
     ≥ `CONFIRM_SECONDS` uiteen zetten hem `True`; **élke** niet-`READY` klasse trekt
     hem onmiddellijk in (`False`). Een scrub of hart-statuswissel kent hem nooit toe.
   - `gates_groen = trust_verdict_groen and dind_healthy`; zet `controller.gates_groen`.
     Trust en DinD zijn **gates**, geen readinessklasse.
3. **Watchdog**: `controller.tick(now, wall)` (commit een verlopen fence — óók het
   fence-herstelpad, §7.5).
4. **Start-conditie**: start een child alleen als **alle vier** waar zijn —
   `controller.mag_child_starten`, `controller.state == State.WAITING`,
   `readiness_confirmed` én `clean_proven` (§5.2). De schil borgt `clean_proven`
   vóór de launch via de scrub-en-bewijs-stap (§6.1). Loopt er al een child → poll
   zijn exit niet-blokkerend.
5. **Slaap** `poll_interval`.

### 5.1 Overgang naar `WAITING`

Vanuit `SOURCE_WAIT` beweegt het hart naar `WAITING` zodra een **bevestigde**
`READY` samenvalt met `gates_groen` en geen fence (`_on_readiness`, koude-startpad,
regel ~330–333). De schil voedt daarvoor readiness-events en zet `gates_groen`; hij
start pas een child als óók §5.2 groen is.

### 5.2 Twee runtime-preconditions die het hart niet kent

`controller.mag_child_starten` is een **noodzakelijke, geen voldoende** toestemming:
het accepteert óók `SOURCE_WAIT`, en het hart kan `WAITING`/`QUARANTINED` bereiken
langs paden die géén verse readiness of schone DinD bewijzen. De schil bewaart
daarom twee eigen preconditions, allebei fail-closed, elk **alleen door zijn eigen
bewijs** te herstellen (m2): `readiness_confirmed` uitsluitend door zijn eigen
twee-waarnemingenbevestiging (nooit door een hart-statuswissel of een scrub);
`clean_proven` uitsluitend door een geslaagde scrub+bewijs (nooit door
readiness-herstel):

- **`readiness_confirmed` (B1).** Sluit het gat dat `_on_scrub_done` (regel 417) bij
  groene gates rechtstreeks naar `WAITING` gaat en dat "de laatste probe was READY"
  al waar is bij één **onbevestigde** `READY`. Tegenvoorbeeld dat de schil moet
  weigeren (30 s-probes): READY t=0/30 → WAITING; transport-fout `SOURCE_WAIT`
  t=60/90 (tijdens de child, dus zonder `job_accepted` bevestigd); `child_exit(0)`
  t=91; `scrub_done(ok)` t=92 → hart `WAITING` zonder fence; **eerste, nog
  onbevestigde** READY t=120. Zonder deze vlag zijn alle andere condities waar en
  start de schil op één probe. Met `readiness_confirmed` — ingetrokken op de
  `SOURCE_WAIT` t=60 — start hij pas na de tweede bevestigde READY (t≈150).
- **`clean_proven` (B2).** DinD is aantoonbaar schoon sinds de laatste child.
  Ingetrokken zodra een child start én bij een scrub-fout; toegekend **alleen** na
  een geslaagde scrub + schoonbewijs (§7.9 stap 8). Nodig omdat het hart na een
  **scrub-fout** (`scrub_done(ok=False)` → `QUARANTINED`, regel 397) bij een latere
  bevestigde READY + gates weer naar `WAITING` opent (regel 330–333) **zonder nieuwe
  scrub**. `clean_proven` blijft dan `False`; de schil start niet en draait eerst
  opnieuw scrub+bewijs (§6.1). Readiness-herstel kan dit niet omzeilen.

Geen permanente koude-startdeadlock: aanhoudend groene gates + bevestigde READY +
een geslaagde scrub leveren uiteindelijk alle vier de condities.

## 6. Adapters (dun)

Alle Docker-toegang tot de **inner** DinD loopt via `docker compose exec dind …`
(zelfde pad als `scrub-dind.sh`), zodat health, pre-pull en scrub consistent één
weg gebruiken en nooit op de host-`docker.sock` terugvallen (§7.5).

| Adapter | Implementatie (dun) | Uitkomst |
|---|---|---|
| `TransportProbe` | `urllib` `GET {forgejo.base_url}/api/v1/version`, timeout `probe_timeout`. **Onderscheidt** `HTTPError` (→ `status=code`) van `URLError`/timeout (→ `error=<str>`), zodat een HTTP 401/403 niet via `error` als SOURCE_WAIT wegvalt. | dict `{"kind":"general","error":<str\|None>,"status":<int\|None>,"schema_ok":<bool>}`. `schema_ok` = JSON met veld `version`. Nooit `kind:"auth"`. |
| `DindHealth` | `docker compose exec -T dind docker -H tcp://127.0.0.1:2375 info` (rc 0 = gezond), harde subprocess-timeout. Ook: `docker compose up -d dind` als DinD niet loopt. | bool. |
| `TrustVerdict` | **Lees** `trust.verdict_path` (JSON) en valideer §6.3: `ok==true`, `measured_at` ≤ `verdict_max_age`, en binding (`forgejo_target`, `labels_sha256`, `allowlist_sha256`) == de actuele controllerconfig/bestanden. Draait de trustgate-CLI **niet**. | bool (+ reden bij niet-groen/verouderd/mismatch/afwezig). |
| `RunnerLifecycle` | start: `docker compose --profile cycle run --rm runner` (verse container; `one-job --wait` staat in compose, §6.2). Niet-blokkerende `Popen` in het register (§9); propageert de exitcode. stop: `SIGTERM` naar het proces, wacht ≤ `child_stop_grace` (≈ runner-`shutdown_timeout` 3 m). | `Popen`; bij exit de returncode. |
| `Scrub` | bestaande `scrub-dind.sh` als niet-blokkerende `Popen` in het register (§9); exit 0 = schoon. | bool. |
| `Reconcile` | `docker compose ps`/`docker ps` gefilterd op de compose-projectlabels om achtergebleven beheerde runnercontainers te vinden (§6.1 stap 0). | lijst container-ID's. |
| `Clock` | `(time.monotonic(), time.time())`. | tuple. |

### 6.1 De cyclus (§7.9), dun — schoon-vóór-elke-start

**`clean_proven`-levenscyclus (B2):** `False` bij programmastart, ingetrokken zodra
een child start en bij een scrub-fout; **toegekend uitsluitend** door stap 8
hieronder. De start-conditie (§5 stap 4) eist `clean_proven`, dus elke start —
koud, na een geslaagde job, of na een eerdere scrub-fout — passeert eerst een
geslaagd schoonbewijs.

**Stap 0 — startup-reconciliatie (B3), eenmalig vóór de eerste childstart:**
identificeer via de compose-projectlabels of er een **beheerde runnercontainer**
bestaat (achtergebleven na een SIGKILL/onschone stop; het ontbreken van een lokaal
`Popen` bewijst dat niet). Bestaat er één → **fail-closed**: geen start, alarm, tot
hij gecontroleerd is afgehandeld. Controleer óók de **operatiemarker** (§6.4):
aanwezig → DinD herstarten, volledige scrub, schoonbewijs, marker wissen; geen start
tot dat rond is.

Wanneer `state == WAITING` + `readiness_confirmed` (§5) en er nog geen child loopt:

1. **trust-verdict** groen, vers én gebonden (§6.3), anders §7.4;
2. **DinD-health** groen, anders §7.4;
3. **toegestane images**: parse `allowed-job-images.txt` in het **bestaande
   formaat** — sla lege regels en `#`-commentaar over, splits elke dataregel op
   `<digest>\t<bytes>`, valideer alleen de **digest** (`…@sha256:<64hex>`), en geef
   uitsluitend die digest als los argv-element aan `docker compose exec -T dind
   docker pull <digest>` (niet-blokkerende Popen). De groottekolom is voor
   `preflight.sh`, niet voor pull. Ongeldige digest of pull-fout ⇒ §7.4;
8. **scrub + schoonbewijs**: als `clean_proven` nog `False` is (koude start,
   overleefde vorige scrub-fout, of onderbroken scrub), draai `scrub-dind.sh`
   (niet-blokkerende Popen) en bewijs schoon (§7.9 stap 8). Slaagt dit → zet
   `clean_proven=True`. Faalt het → blijf geblokkeerd (geen start), alarm, en
   probeer opnieuw op de volgende cyclus. Readiness-herstel zet `clean_proven`
   nooit;
9. **start** exact één `docker compose --profile cycle run --rm runner`; **trek
   `clean_proven` in** op het moment van starten.

(De stapnummers volgen §7.9; stap 4–7 — child starten, wachten, bewijzen geen
runnerproces, scrub na exit — lopen via §7.3.)

### 6.2 `compose.yaml`: het one-job-commando vastleggen (M4-ronde1)

De runnerservice heeft nu **geen** `command`/`entrypoint`; een profiel selecteert
alleen de service, het verandert de image-opdracht niet. Deze slice voegt aan de
runnerservice toe:

```yaml
    command: ["one-job", "--wait"]
```

Stap B valideerde al dat de gepinde Runner-12.10.1-image `one-job --wait`
accepteert; het config-pad wordt via de mount `…/config.yml` gevonden.
**Bring-up-verificatie (stap D):** `docker inspect` op de gepinde image bevestigt
entrypoint + de resulterende argv vóór productieactivatie; leg dat vast onder
`evidence/`.

### 6.3 De trustgate als deploy-verdict (M6-ronde1 + M3-ronde2)

De bestaande `trust_scope_cli.py` is een **geauthenticeerde netwerkclient**: hij
vereist `--allowlist`, `--labels`, `--out` en `FORGEJO_TOKEN` (zonder token exit
`30`) en doet gepagineerde Forgejo-API-calls. Een controller die dat live draait
zou een API-credential nodig hebben — strijdig met de transport-only-keuze.

**Besluit voor de dunne slice:** de **operator** produceert het verdict bij deploy;
de controller **leest** het. Dit is bewust een **zwakkere, tijdgebonden** garantie
dan een live gate (§13-follow-up), maar moet binnen die grens strikt fail-closed
blijven. Daarvoor een expliciet **publicatiecontract** (M3):

- draai de CLI naar een **verse, lege** `--out`-directory;
- publiceer **alleen na CLI-exit `0`** atomair (rename) een verdict-artifact voor
  de controller; een mislukte meting (exit 30 door ontbrekend token, onleesbare
  inventaris of niet-goedgekeurde allowlist — `trust_scope_cli.py:188–208,231–238`)
  **laat het oude groen niet** als nieuwe deployvalidatie gelden;
- het artifact bevat naast de CLI-`ok` een **meettijd** `measured_at` en een
  **binding**: `forgejo_target`, `labels_sha256`, `allowlist_sha256` (de bestaande
  verdict-JSON, regels 236–241, bevat die niet; de deploy-wrapper voegt ze toe).

De controller-adapter `TrustVerdict` gate't groen **alleen** als: `ok==true`, én
`measured_at` een geldig tijdformaat heeft én `0 ≤ now - measured_at ≤ verdict_max_age`
(de **ondergrens** weigert een meettijd in de toekomst — m3 — zodat een foutieve/
toekomstige timestamp niet langdurig vals-vers blijft; getoetst op de **meettijd**,
niet de bestands-mtime, zodat kopiëren met verse mtime niet vals-vers wordt), én de
binding gelijk is aan de target/labels/allowlist die de controller nu gebruikt. Anders → `gates_groen=False`
(§7.4). Gevolg + bewuste beperking: een repo-/allowlist-wijziging tussen deploys
wordt pas bij een nieuw deploy-verdict gezien.

### 6.4 Operatie-exclusiviteit in DinD (crashbestendig, M1)

Pre-pull en scrub draaien via `docker compose exec dind …`; hun proces leeft onder
DinD's PID 1 en **overleeft een SIGKILL van de controller** (DinD is `restart: always`
met blijvend volume). Het lokale Popen-register (§5) en een schone-objectensnapshot
bewijzen dus niet dat een oude DinD-side operatie is geëindigd. Daarom een
crashbestendige uitvoeringsgrens:

- **Operatiemarker (overleeft een crash):** vóór elke pull/scrub schrijft de schil
  een markerbestand op een **apart, persistent controlepad** (een eigen mount, niet
  het docker-datavolume, zodat de scrub het niet raakt) met operatienaam en
  starttijd; ná afronding (succes óf fout) verwijdert hij de marker.
- **Startup-uitsluiting (onderdeel van §6.1 stap 0):** is de marker bij start
  aanwezig, dan is een operatie onderbroken en is de DinD-toestand onbekend. De schil
  **herstart DinD** (`docker compose kill dind && docker compose up -d dind`) — dat
  beëindigt élk achtergebleven operatieproces deterministisch — draait daarna een
  **volledige scrub**, bewijst schoon, en verwijdert pas dán de marker. **Geen launch**
  tot de marker door een bewezen-schone scrub gewist is. Afwezige marker → geen
  onderbroken operatie, normaal door.
- **Normale stop (§9):** loopt een operatie, dan staat de marker; de stop wacht
  bounded op afronding + markerwis; bij SIGKILL blijft de marker staan voor de
  volgende startup.

Zo is de grens crashbestendig: een onderbroken operatie is bij herstart detecteerbaar
(marker), de oude operatie wordt deterministisch beëindigd (DinD-herstart) vóór een
nieuwe scrub én launch, en er start niets tot die uitsluiting bewezen is. De runtime
is single-threaded, dus binnen één proces lopen nooit twee operaties tegelijk; de
marker dekt uitsluitend het crash-/herstartgeval.

## 7. Toestandsbedrading — hoe de schil het hart voedt

De schil muteert **nooit** `controller.state` rechtstreeks; hij voedt events en
leest `state`/`mag_child_starten` + zijn eigen preconditions (§5.2).

### 7.1 Events die de schil indient

- `"readiness" {klasse}` — uit de transport-probe (elke 30 s).
- `"child_exit" {code}` — bij runner-exit; het hart → `SCRUBBING`.
- `"scrub_done" {ok}` — na `scrub-dind.sh`; het hart → `WAITING`/`QUARANTINED`.

### 7.2 Gates → `gates_groen`

`gates_groen = trust_verdict_groen and dind_healthy`, op de 30 s-cadans gezet.
Alleen bij `gates_groen` kan het hart `SOURCE_WAIT`/`QUARANTINED` → `WAITING`; een
start vereist bovendien §5.2.

### 7.3 Child-levenscyclus en exitcode (§7.9-exitcodecontract)

`docker compose --profile cycle run --rm runner` propageert de exitcode. De schil
pollt niet-blokkerend; bij exit: `submit("child_exit",{code})` → `SCRUBBING` →
`scrub-dind.sh` → `submit("scrub_done",{ok})`. Het hart beslist:

- `ok` én exit `0` → `WAITING`; groene én rode workflow leveren beide exit `0`; de
  terminale Forgejo-status wordt buiten de controller waargenomen (stap-E-bewijs).
- exit ≠ 0 of scrub-fout → `QUARANTINED`. Het hart kan `QUARANTINED` bij een latere
  bevestigde READY + gates heropenen (regel 330–333), **maar** een start vereist
  `clean_proven` (§5.2/§6.1 stap 8), dat na een scrub-fout `False` is en alleen door
  een nieuwe geslaagde scrub hersteld wordt — readiness-herstel omzeilt de scrub dus
  niet (B2).

**`job_accepted` uitgesteld**: zonder dat event blijft de zichtbare toestand
`WAITING`→`SCRUBBING`; de job draait en scrubt gewoon (`_on_child_exit` gaat
ongeacht de vorige state naar `SCRUBBING`). De runner draait tot `one-job --wait`
klaar is; er wordt geen job afgekapt. Omdat een tijdens de job bevestigde bronfout
zónder `RUNNING`-label niet als `volgende_state` wordt bewaard, leunt de
correctheid op de runtime-preconditions (§5.2) en de reconciliatie (§6.1), niet op
het `RUNNING`/`volgende_state`-spoor.

### 7.4 Gate-falen (dun, veilig)

- **trust-verdict niet groen/vers/gebonden** of **DinD ongezond**: `gates_groen=False`
  + alarm + geen runnerstart; de controller blijft draaien (geen crash-loop). De
  toestand blijft `SOURCE_WAIT`/geblokkeerd. **Bewuste beperking:** geen
  `QUARANTINED`-label bij een trust-hardfout (het hart kent die overgang niet en
  wordt niet gewijzigd); dat label is follow-up.
- **pre-pull/image-fout of scrub-fout**: geen start; alarm; `clean_proven` blijft
  `False` tot een geslaagde scrub.

### 7.5 Fence-herstel gebeurt in het hart (geen herstart-tak)

Een transport-blip die de controller in `WAITING` fencet (→ `DRAINING`) herstelt
**vanzelf in het hart**, zonder nulbewijs en zonder runtime-herstart:

- de 60 s-watchdog `tick` (regel ~360–379) commit een verlopen fence naar de
  zwaarste sinds latch waargenomen klasse en reset de bevestiging; bij herstelde
  transport is die klasse `SOURCE_WAIT`;
- daarna geven twee bevestigde `READY`-probes + `gates_groen` via de koude-startpad
  (regel ~330–333) weer `WAITING`.

Herstel duurt ~60 s (watchdog) + ~2 probes. De runtime doet hier niets bijzonders.
(De eerdere "herstart bij gefencete impasse" is verwijderd: hij berustte op de
onjuiste premisse dat een fence alleen met nulbewijs wist — regels 336–338 en
377–379 wissen hem óók.) De enige herstart is systemd's `Restart=on-failure` bij
een echte processcrash.

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
verdict_path = "/opt/forgejo-runner/trust-verdict.json"   # deploy-wrapper-artifact (§6.3)
verdict_max_age_seconds = 86400                            # 0 ≤ now-measured_at ≤ max_age; op measured_at, NIET mtime
labels_file = "/opt/forgejo-runner/labels.txt"            # voor de labels_sha256-binding
allowlist_file = "/opt/forgejo-runner/trusted-actions-scope.yml"  # voor de allowlist_sha256-binding

[docker]
subprocess_timeout_seconds = 30           # harde deadline op korte docker-calls (health/pull-init)

[cadence]
poll_interval_seconds = 1
retry_interval_seconds = 30               # readiness+gates-cadans

[log]
level = "INFO"
```

- **Geen** `confirm_seconds`/`fence_max_age_seconds` in config (MINOR 8): `Confirmation`
  en `Fence` lezen de moduleconstanten `CONFIRM_SECONDS` (5) en `FENCE_MAX_AGE_SECONDS`
  (60). De runtime-`readiness_confirmed` gebruikt óók `CONFIRM_SECONDS`. Tests
  versnellen via de fake klok, niet via config.
- Geen secret in het bestand; het runner-token is een pad dat de compose al `0600`
  read-only mount (§7.5). `controller.toml` en het deploy-verdict zijn hostspecifiek
  en géén onderdeel van de byte-identieke bundel-hash.

## 9. Signal-handling / graceful stop (M7-ronde1 + M4-ronde2)

`SIGTERM`/`SIGINT` (unit `KillSignal=SIGTERM`, `TimeoutStopSec=300`) zet een flag
die de niet-blokkerende loop élke iteratie leest; roep `controller.drain(now)`.
Het stopcontract kijkt naar **alle** actieve cyclus-Popens in het register (§5),
niet alleen naar het runner-child:

- **niets actief**: exit `0`.
- **runner-child actief**: `SIGTERM` naar het `compose run`-proces (dat de runner
  zijn `shutdown_timeout` 3 m gunt), poll ≤ `child_stop_grace` (~200 s, binnen
  systemds 300 s). Laat het hart de exit via `child_exit`→scrub afhandelen.
- **pull of scrub actief (geen runner-child)**: deze muteren DinD; §9 geeft hier
  **niet** onmiddellijk exit 0. Stuur ze `SIGTERM`, wacht bounded op afronding, en
  beschouw een afgekapte pull/scrub als onschone stop.
- **exit `0` alleen na bevestigd einde van álle cyclus-operaties** (child weg,
  geen actieve pull/scrub). Lukt dat niet binnen het budget → geen schone-stopclaim;
  systemd `SIGKILL` na 300 s is een onschone stop. De **volgende start** is dan
  veilig doordat (a) de startup-reconciliatie (§6.1 stap 0) een achtergebleven
  runnercontainer fail-closed afvangt, (b) de operatiemarker (§6.4) een onderbroken
  pull/scrub detecteert en via een DinD-herstart + volledige scrub deterministisch
  uitsluit vóór een nieuwe scrub én launch, en (c) `clean_proven` bij programmastart
  `False` is. Een onderbroken oude scrub/pull kan zo geen nieuwe start overlappen.

> De runnerpolicy heeft `timeout: 3h` en `shutdown_timeout: 3m`
> (`runner-config.policy.yml`). Een 3-uursjob past niet binnen systemds 300 s; deze
> slice belooft daarom **geen** gegarandeerde graceful afronding van een lopende
> job, maar wel een veilige volgende start via reconciliatie + `clean_proven`.

## 10. Logging

Gestructureerde regels (`logging`, stdout → journald): runner-ID, cyclusnummer,
begin/eindtijd, toestand, exitcode, en geanonimiseerde tellingen. **Nooit** namen,
tokens of metadata die secrets kunnen bevatten (§7.9). Alarm-events uit het hart
(`alarm`, `fence_set`, `cancel_en_redispatch`) worden gelogd op `WARNING`; in deze
dunne slice is een alarm log-only (geen queue/Forgejo-sink).

## 11. Teststrategie

- **Beslis-hart**: de 99 bestaande tests blijven ongewijzigd draaien (regressiegate).
- **Runtime (nieuw)** `test_cycle_runtime_*.py`, stdlib `unittest`, met **fake
  adapters**, een **fake clock** en een gedreven loop (stap-voor-stap i.p.v. `sleep`):
  1. koude start: gates groen + eerste (onbevestigde) READY → **géén** start; pas na
     bevestigde READY (§5.2) → start;
  2. **B1-spoor**: READY t=0/30 → WAITING; SOURCE_WAIT t=60/90; `child_exit(0)` t=91;
     `scrub_done(ok)` t=92; **eerste** READY t=120 → **géén** start; tweede
     bevestigde READY t≈150 → start;
  3. **B2**: `scrub_done(ok=False)` → `QUARANTINED`; daarna blijvend groene readiness
     + health → hart mag `WAITING` heropenen, maar **nul nieuwe starts** tot een
     geslaagde scrub `clean_proven` weer zet;
  4. `clean_proven`-levenscyclus: ingetrokken bij childstart en scrub-fout; alleen
     door geslaagde scrub+bewijs gezet;
  5. start-stappen in de volgorde van `cycle_stappen()`;
  6. child exit `0` → scrub ok → `WAITING`; child exit ≠ 0 → `QUARANTINED`;
  7. transport-fout → `SOURCE_WAIT`; fence-blip → watchdog → `SOURCE_WAIT` →
     `WAITING`, **zonder** herstart (§7.5);
  8. **startup-reconciliatie** (B3): achtergebleven beheerde runnercontainer →
     fail-closed geen start;
  9. **image-parser** (M5): echt formaat (`#`-comment + `digest\tbytes`) → alleen de
     digest aan pull; ongeldige digest → geen start;
  10. **trust-verdict** (M3): niet-groen / verouderd op `measured_at` / binding-
      mismatch (target/labels/allowlist) / afwezig → geen start; verse gebonden groen
      → wél; oud groen met verse **mtime**, én een meettijd in de toekomst / ongeldig
      tijdformaat → nog steeds geweigerd;
  11. **stop-contract** (M4): `SIGTERM` tijdens een lopende **pull** en tijdens een
      lopende **scrub** → bounded stop, geen exit-0-vóór-afronding; daarna schone
      herstart; `SIGTERM` met runner-child → child krijgt SIGTERM, exit 0 alleen na
      bevestigd child-weg; en **crash-uitsluiting (M1)**: operatiemarker aanwezig maar
      geen lokaal Popen (client weg, DinD-side operatie leefde nog) → DinD-herstart +
      volledige scrub vóór enige start, geen parallelle scrub/start;
  12. **niet-blokkerend** (M7): een hangende pull/scrub blokkeert watchdog + SIGTERM
      niet;
  13. **RunnerLifecycle-argv** (M4-ronde1): het gestarte commando bevat `one-job --wait`.
- **Config**: `controller.toml` laadt en valideert (ontbrekende sleutel → nette fout).
- **Integratie-smoke op max2** (stap D/E, handmatig via SSH, geen CI): deploy-wrapper
  produceert een gebonden verdict; `docker inspect` bevestigt runner-entrypoint/argv;
  DinD omhoog; controller start; runner online in Forgejo; groene + rode
  smoke-workflow; groene scrub; `SIGTERM` stopt schoon. Bewijs onder `evidence/`.
- `ruff` schoon; `shellcheck` op gewijzigde shell (deploy-wrapper); secret-scan hook.

## 12. Verificatie-commando's

```
cd forgejo-runner
python3 -m unittest discover -s tests -p 'test_*.py'   # hart + runtime
ruff check scripts/
```

## 13. Follow-up (na deze slice, buiten scope)

1. assignment-nulbewijs-adapter (Forgejo-API) → volwaardige `DRAINING` + in-place
   fence-herstel via het READY-recoverypad.
2. **live per-cyclus trustgate** (mét credential) → vervangt het deploy-verdict (§6.3).
3. geauthenticeerde probe → echte `CREDENTIAL_ERROR`.
4. maintenance-record arming (stap F).
5. cancel/redispatch + `job_accepted`-detectie + terminale-status-correlatie.
6. trust-hardfout → echt `QUARANTINED`-label.

## 14. Risico's / open punten

- **Trustgate-deploy-verdict (§6.3)** is een zwakkere, tijdgebonden garantie dan een
  live gate; JP kan besluiten de controller tóch een credential + live trustgate te
  geven. Binnen de gekozen grens is hij strikt fail-closed gemaakt (M3).
- **`compose run` + `command` (§6.2)** en de image-entrypoint/argv moeten in de
  max2-smoke met `docker inspect` bevestigd worden.
- **Stop van een lopende job**: een 3-uursjob wordt bij `SIGTERM` niet gegarandeerd
  gracefully afgerond binnen systemds 300 s; veiligheid komt van reconciliatie +
  `clean_proven`, niet van een graceful-afrondgarantie.
- **`scrum4me-server` Python-versie** (stap G, byte-identieke bundel) moet `tomllib`
  (3.11+) hebben; te meten vóór stap G, niet in deze slice.

## Review record

Loop: delta-variant, één cross-model reviewer `mac:codex` (spec claude-authored).

### Ronde 1 — commit `3e87342` — mac:codex — NO-GO (3 BLOCKER, 4 MAJOR, 1 MINOR)

Alle bevindingen geverifieerd tegen de boom en aanvaard:

- **B1** — lus start vóór bevestigde readiness. Fix (r1): start-conditie
  `state==WAITING` + `laatste_readiness READY`. (r2: onvoldoende, zie hieronder.)
- **B2** — `sys` ongebonden in de delegatie. Fix: `main()` leest zelf `sys.argv` (§4). ✔ r2 bevestigd.
- **B3** — herstart bewijst geen schone beginstaat. Fix: startup-reconciliatie (§6.1 stap 0). ✔ r2 bevestigd (mits detectie/bewijs slagen; normale scrub-fout zie r2-B2/M4).
- **M4** — `compose run` mist `one-job`-command. Fix: `command` in compose (§6.2) + inspect-verificatie. ✔ r2 bevestigd.
- **M5** — image-parser past niet op het bestandsformaat. Fix: `digest\tbytes`-parser (§6.1 stap 3). ✔ r2 bevestigd.
- **M6** — trustgate vereist credential/labels/out. Fix: deploy-verdict lezen (§6.3). ✔ r2: credentialafhankelijkheid weg; artifactcontract hardened in r2 (zie M3).
- **M7** — stop/watchdog niet afdwingbaar. Fix: niet-blokkerende Popen-polling + termijnen op runnerpolicy (§5/§6/§9). ✔ r2: bediening ok; stop van niet-child-ops zie r2-M4.
- **MINOR 8** — config↔hartconstanten. Fix: uit config; fake-klok in tests. ✔ r2 bevestigd.
- **§7.5** — herstart-tak verwijderd (hart-watchdog herstelt de fence). ✔ r2 bevestigd.

### Ronde 2 — commit `1d3a5dd` — mac:codex — NO-GO (2 BLOCKER, 2 MAJOR)

Alle bevindingen geverifieerd tegen de boom (twee reproduceerbare event-sporen op
het ongewijzigde hart) en aanvaard:

- **B1 (r2)** — `_on_scrub_done` (regel 417) → `WAITING` zonder verse readiness, en
  `laatste_readiness READY` is al waar bij één onbevestigde probe. Fix: runtime-vlag
  **`readiness_confirmed`** (eigen 2-waarnemingenbevestiging, ingetrokken bij elke
  afwijking, nooit door scrub/hart toegekend) (§5.2, §5 stap 4; test 1/2).
- **B2 (r2)** — na `scrub_done(ok=False)` → `QUARANTINED` heropent het hart via
  READY+gates naar `WAITING` zonder nieuwe scrub (regel 397 → 330–333). Fix:
  runtime-vlag **`clean_proven`** — ingetrokken bij childstart + scrub-fout, alleen
  door geslaagde scrub+bewijs gezet, readiness-herstel kent hem nooit toe; elke start
  borgt eerst een geslaagde scrub (§5.2, §6.1 stap 8; test 3/4).
- **M3 (r2)** — bestands-mtime bewijst geen verse, geslaagde, gebonden trustmeting.
  Fix: publicatiecontract (verse out-dir, atomair publiceren alleen bij CLI-exit 0)
  + verdict met `measured_at` + binding (`forgejo_target`/`labels_sha256`/
  `allowlist_sha256`); adapter toetst `ok`+`measured_at`+binding, niet mtime (§6.3,
  §8; test 10).
- **M4 (r2)** — stopcontract vergat actieve pull/scrub-Popens. Fix: register van
  álle cyclus-Popens; §9 stopt/awacht ze bounded; exit 0 alleen na einde van álle
  operaties; onderbroken scrub/pull afgevangen door `clean_proven` + reconciliatie
  bij de volgende start (§5, §9; test 11).

Verdict ronde 2: **NO-GO**. Fixes toegepast; ronde 3 opnieuw naar `mac:codex`.

### Ronde 3 — commit `3e2be5a` — mac:codex — NO-GO (0 BLOCKER, 1 MAJOR, 2 MINOR)

B1 en B2 bevestigd opgelost (codex reproduceerde de modelsporen op het echte hart);
M3 implementeerbaar bevonden zonder de CLI te wijzigen. Resterend, geverifieerd en
aanvaard:

- **M1 (r3)** — een `docker compose exec dind` pull/scrub overleeft een
  controller-SIGKILL (DinD PID 1, `restart: always`); het Popen-register is na een
  crash weg en de reconciliatie zocht alleen runnercontainers, niet een verweesde
  exec. Fix: §6.4 crashbestendige **operatiemarker** + DinD-herstart + volledige scrub
  bij een onderbroken operatie, gewired in §6.1 stap 0 en §9; geen start tot de
  uitsluiting bewezen is (test 11).
- **m2 (r3)** — de §5.2-zin "geen van beide door readiness-herstel toe te kennen"
  sprak `readiness_confirmed` tegen. Fix: elke vlag wordt alleen door zijn eigen bewijs
  hersteld (§5.2).
- **m3 (r3)** — de versheidsformule accepteerde een meettijd in de toekomst. Fix:
  `0 ≤ now - measured_at ≤ verdict_max_age` + geldig tijdformaat (§6.3, §8, test 10).

Verdict ronde 3: **NO-GO**. Fixes toegepast; ronde 4 opnieuw naar `mac:codex`.
