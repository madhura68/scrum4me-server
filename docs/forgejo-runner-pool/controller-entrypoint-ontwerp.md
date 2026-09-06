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
- **Transport-only readiness-probe** (geen tweede hostcredential).

## 2. Niet-doelen (expliciet uitgesteld naar de follow-up)

Deze staan bewust NIET in deze slice; het beslis-hart ondersteunt ze al, de
adapters komen later:

- **assignment-nulbewijs / volwaardige `DRAINING`**: de twee Forgejo-side
  snapshots (assigned/running per runner-ID, §7.9) vergen API-toegang die de
  transport-only-keuze niet biedt. `controller.nulbewijs_ok` blijft dus `False`.
- **maintenance-record arming** (cross-host onderhoudsvenster, stap F).
- **`CREDENTIAL_ERROR`-detectie** (geauthenticeerde probe, 401/403).
- **cancel/redispatch** van een op/na-latch geaccepteerde job (§7.7).
- **terminale-Forgejo-jobstatus-correlatie** per job (vergt API-toegang); de
  slice beslist op de **procesexitcode** (§7.9 exitcodecontract).
- **`job_accepted`-detectie** via runnerlog-parsing (zie §7.3).

## 3. Uitgangspunten (gemeten)

- max2: Python **3.14.4** (`tomllib` aanwezig), Docker **Compose v2**, `curl`
  aanwezig; bereikbaar als `ssh janpeter@max2` (tailscale). Gemeten 2026-09-06.
- De unit draait system-`/usr/bin/python3` zonder venv ⇒ **alleen stdlib**:
  `tomllib`, `urllib.request`, `subprocess`, `signal`, `logging`, `time`.
- Het beslis-hart `forgejo_runner_cycle.py` blijft **byte-identiek**; deze slice
  voegt er alleen een dunne `__main__`-delegatie aan toe (§4). De 99 bestaande
  tests blijven ongewijzigd groen.
- De bundel is byte-identiek op beide hosts (§6.1 migratieontwerp); niets in deze
  slice is hostspecifiek behalve de waarden in `controller.toml`.

## 4. Architectuur — ports & adapters

Het beslis-hart blijft puur; alle neveneffecten leven achter smalle interfaces
zodat ze in tests vervangbaar zijn en het hart onaangeraakt blijft.

| Bestand | Rol | Nieuw? |
|---|---|---|
| `scripts/forgejo_runner_cycle.py` | Puur beslis-hart. Krijgt onderaan een `if __name__ == "__main__": from cycle_runtime import main; raise SystemExit(main(sys.argv[1:]))`. Verder ongewijzigd. | bestaand + 3 regels |
| `scripts/cycle_runtime.py` | `main(argv)`: config laden, adapters bedraden, de serialiseerde poll-loop, signal-handling, logging. | nieuw |
| `scripts/cycle_adapters.py` | De neveneffect-adapters achter interfaces: `TransportProbe`, `DindHealth`, `TrustGate`, `RunnerLifecycle`, `Scrub`, `Clock`. | nieuw |

`main` construeert de echte adapters en injecteert ze in een `Runtime`; tests
injecteren fakes. De unit-`ExecStart` blijft ongewijzigd naar
`forgejo_runner_cycle.py` wijzen.

## 5. Runtime-model — één geserialiseerde poll-loop

Eén thread, geen asyncio (afgewezen: meer oppervlak, moeilijker deterministisch
te testen; het beslis-hart is al synchroon). De loop tikt elke `poll_interval`
(default 1 s); de zwaardere probe draait op de `retry`-cadans (30 s).

Per iteratie, in deze volgorde:

1. **Klok**: `now, wall = clock()` (`time.monotonic()`, `time.time()`).
2. **Readiness-cadans (elke 30 s)**: draai de transport-probe →
   `classify_probe(probe)` → `ReadinessClass`; `event = loop.submit("readiness",
   {"klasse": klasse})`; `controller.on_event(event)`.
3. **Gates (op dezelfde 30 s-cadans, gecacht ertussen)**: bepaal
   `gates_groen = trustgate_groen and dind_healthy` en zet `controller.gates_groen`.
   De trustgate (subprocess) en DinD-health draaien dus op 30 s, niet elke
   poll-tik. Trust en DinD zijn **gates**, geen readinessklasse (`classify_probe`
   gaat alleen over de Forgejo-bron); de definitieve trust+DinD-check herhaalt
   sowieso als cyclusstap 1–2 vlak vóór een runnerstart (§6.1), zodat een gecachte
   gate nooit een verkeerd-vertrouwde start veroorzaakt.
4. **Watchdog**: `controller.tick(now, wall)` (commit een verlopen fence).
5. **Cyclus**: als `controller.mag_child_starten` én er geen runner-child loopt →
   voer de start-stappen uit (§7.2). Loopt er een child → poll zijn exit
   niet-blokkerend (`Popen.poll()`), zodat de readiness-probe tijdens een job
   blijft draaien.
6. **Slaap** `poll_interval`.

`mag_child_starten` (beslis-hart) = `fence is None and not drain_gevraagd and
gates_groen and state in (WAITING, SOURCE_WAIT)`. De schil beslist dus nooit
zélf of hij mag starten; hij vraagt het het hart.

### 5.1 Overgang naar `WAITING`

Vanuit `SOURCE_WAIT` beweegt het hart naar `WAITING` zodra een **bevestigde**
`READY` (twee gelijke probes ≥ 5 s uiteen) samenvalt met `gates_groen` en geen
fence (`_on_readiness`, koude-startpad). De schil hoeft hiervoor niets extra's te
doen dan readiness-events voeden en `gates_groen` correct zetten.

## 6. Adapters (dun)

Alle Docker-toegang tot de **inner** DinD loopt via `docker compose exec dind …`
(zelfde pad als `scrub-dind.sh`), zodat health, pre-pull en scrub consistent één
weg gebruiken en nooit op de host-`docker.sock` terugvallen (§7.5).

| Adapter | Implementatie (dun) | Uitkomst |
|---|---|---|
| `TransportProbe` | `urllib` `GET {forgejo.base_url}/api/v1/version`, timeout `probe_timeout`. | dict `{"kind":"general","error":<str\|None>,"status":<int\|None>,"schema_ok":<bool>}` voor `classify_probe`. `error` bij transport/timeout/refused; `schema_ok` = JSON met veld `version`. Nooit `kind:"auth"` in deze slice. |
| `DindHealth` | `docker compose exec -T dind docker -H tcp://127.0.0.1:2375 info` (rc 0 = gezond). | bool. Ook: `docker compose up -d dind` als DinD niet loopt. |
| `TrustGate` | shell-out naar bestaande `trust_scope_cli.py` tegen `trusted-actions-scope.yml`; exit 0 = groen. | bool (+ reden bij niet-groen). |
| `RunnerLifecycle` | start: `docker compose --profile cycle run --rm runner` (verse container, `one-job --wait`, propageert de exitcode; `--profile cycle` want de runnerservice is profielgated). stop: `SIGTERM` naar het `compose run`-proces, wacht `shutdown_timeout`. | `Popen`; bij exit de returncode. |
| `Scrub` | bestaande `scrub-dind.sh`; exit 0 = schoon. | bool. |
| `Clock` | `(time.monotonic(), time.time())`. | tuple. |

### 6.1 De start-stappen (cyclus §7.9 stap 1–4, dun)

Wanneer `mag_child_starten`:

1. **trustgate** groen (anders §7.4);
2. **DinD-health** groen (anders §7.4);
3. **toegestane images**: elke regel in `allowed-job-images.txt` is een
   `naam@sha256:…`-digest; pre-pull ontbrekende **per digest** via
   `docker compose exec -T dind docker pull <digest>`; een niet-digest-regel of
   pull-fout ⇒ §7.4 (geen start);
4. **start** exact één `docker compose --profile cycle run --rm runner`.

Daarna poll de schil de child-exit (§7.3).

## 7. Toestandsbedrading — hoe de schil het hart voedt

De schil muteert **nooit** `controller.state` rechtstreeks; hij voedt events en
leest `state`/`mag_child_starten`. Dit houdt de "geserialiseerde eventloop"
intact.

### 7.1 Events die de schil indient

- `"readiness" {klasse}` — uit de transport-probe (elke 30 s).
- `"child_exit" {code}` — bij runner-exit; het hart → `SCRUBBING`.
- `"scrub_done" {ok}` — na `scrub-dind.sh`; het hart → `WAITING`/`QUARANTINED`.

### 7.2 Gates → `gates_groen`

`gates_groen = trustgate_groen and dind_healthy`, elke iteratie gezet. Effect via
het hart: alleen bij `gates_groen` kan `SOURCE_WAIT`/`QUARANTINED` → `WAITING` en
mag een child starten.

### 7.3 Child-levenscyclus en exitcode (§7.9-exitcodecontract)

`docker compose run --rm runner` propageert de exitcode van de runnercontainer.
De schil pollt niet-blokkerend; bij exit: `submit("child_exit",{code})` →
`SCRUBBING` → `scrub-dind.sh` → `submit("scrub_done",{ok})`. Het hart beslist:

- `ok` én exit `0` → `WAITING` (volgende cyclus). Groene én rode workflow leveren
  beide exit `0`; de terminale Forgejo-status (groen/rood) wordt **buiten** de
  controller waargenomen (stap-E-bewijs), niet door de controller gecorreleerd.
- exit ≠ 0 (config/init/poller/runtime-fout) of scrub-fout → `QUARANTINED`;
  binnen dezelfde scrubroute niet heropenen (§7.9 stap 5).

**`job_accepted` uitgesteld**: het hart gaat `WAITING`→`RUNNING` pas op een
`job_accepted`-event; runnerlog-parsing daarvoor is bros en enablet de
(uitgestelde) cancel/redispatch. Zonder dat event blijft de zichtbare toestand
`WAITING`→`SCRUBBING`; de job draait en scrubt gewoon. De runner draait sowieso
tot `one-job --wait` klaar is, ongeacht de controllertoestand; er wordt geen job
afgebroken.

### 7.4 Gate-falen (dun, veilig)

- **trustgate niet groen** of **DinD ongezond**: `gates_groen=False` + alarm +
  geen runnerstart. De veiligheidswerking (geen runner bij twijfel) is behouden;
  de toestand blijft `SOURCE_WAIT`/geblokkeerd. **Bewuste beperking**: de slice
  zet hier niet het `QUARANTINED`-label (het hart kent geen `trust→QUARANTINED`
  overgang en het hart wordt niet aangepast). Geen crash-loop. Het volwaardige
  trust-`QUARANTINED`-label komt in de follow-up.
- **pre-pull/image-fout**: idem, geen start; alarm.

### 7.5 Fence-herstel = herstart (bewuste beperking van de dunne slice)

Een fence wist alleen als `nulbewijs_ok and gates_groen` (`_on_readiness`,
regel ~321), en echt nulbewijs is uitgesteld (§2). Een transport-blip die de
controller in `WAITING` fencet (→ `DRAINING`) kan dus **niet in-place** herstellen.
Gedrag van de slice: wanneer de controller `DRAINING`/gefencet is, een child noch
loopt noch mag starten, en de transport weer bevestigd `READY` is terwijl de fence
door het ontbrekende nulbewijs niet wist, **beëindigt `main` het proces met een
niet-nul exit**. `systemd Restart=on-failure` herstart dan schoon in `SOURCE_WAIT`
en doorloopt alle gates (unit-commentaar: "een restart begint altijd opnieuw in
SOURCE_WAIT"). In-place fence-herstel komt met de nulbewijs-follow-up.

Deze herstart-tak vuurt **alleen** bij een gefencete/`DRAINING`-impasse mét
herstelde transport — niet bij een aanhoudende trust-/DinD-fout (§7.4, geen
crash-loop) en niet bij `QUARANTINED` uit een runnerfout (dat herstelt via het
hart op de volgende bevestigde `READY`+gates).

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
token_path          = "/opt/forgejo-runner/credentials/forgejo-token"  # alleen pad, nooit de waarde
shutdown_timeout_seconds = 40

[cadence]
poll_interval_seconds = 1
retry_interval_seconds = 30     # readiness-cadans; hart-constante RETRY_INTERVAL_SECONDS = 30
confirm_seconds = 5             # hart-constante CONFIRM_SECONDS = 5
fence_max_age_seconds = 60      # hart-constante FENCE_MAX_AGE_SECONDS = 60

[log]
level = "INFO"
```

De cadans-waarden spiegelen de hart-constanten; ze staan in config zodat tests ze
kunnen versnellen, maar de defaults zijn de hart-constanten. Geen secret in het
bestand; het token is een **pad**, gemount `0600` read-only in de runnercontainer
(compose §7.5). `controller.toml` wordt (met echte hostwaarden) in stap D
geplaatst en is géén onderdeel van de byte-identieke bundel-hash.

## 9. Signal-handling / graceful stop

`SIGTERM` (unit `KillSignal=SIGTERM`, `TimeoutStopSec=300`): zet een flag die de
loop leest, roep `controller.drain(now)` (WAITING→DRAINING; RUNNING laat de job
terminaal worden — in de dunne slice zonder `job_accepted` is er geen
`RUNNING`-label, dus een lopende job wordt niet afgekapt: de schil stuurt `SIGTERM`
naar het `compose run`-proces, wacht `shutdown_timeout`, en laat het beslis-hart
via de normale `child_exit`→scrub-route eindigen). Daarna exit `0`. `SIGINT`
idem. De 300 s `TimeoutStopSec` dekt een lopende job ruim; overschrijding is
systemds `SIGKILL`, wat een niet-schone stop is en bij de volgende start via
`SOURCE_WAIT` + gates alsnog veilig wordt afgevangen.

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
  1. gates groen + bevestigde READY → `WAITING`;
  2. `mag_child_starten` → start-stappen in de volgorde van `cycle_stappen()`;
  3. child exit `0` → scrub ok → `WAITING`;
  4. child exit ≠ 0 → `QUARANTINED`; scrub-fout → `QUARANTINED`;
  5. transport-fout → `SOURCE_WAIT`; herstel → `WAITING`;
  6. trustgate/DinD niet groen → geen start, geen crash-loop;
  7. `SIGTERM` → graceful stop (`compose run`-proces krijgt SIGTERM, exit 0);
  8. gefencete impasse + herstelde transport → niet-nul exit (herstart-tak §7.5);
  9. niet-digest-regel in `allowed-job-images.txt` → geen start.
- **Config**: `controller.toml` laadt en valideert (ontbrekende sleutel → nette
  fout, geen stacktrace).
- **Integratie-smoke op max2** (stap D/E, handmatig via SSH, geen CI): DinD
  omhoog, controller start, runner online in Forgejo; één groene + één rode
  smoke-workflow; groene scrub; `SIGTERM` stopt schoon. Bewijs onder
  `evidence/` (stap D/E).
- `ruff` schoon; `shellcheck` op eventueel gewijzigde shell (geen verwacht);
  secret-scan pre-commit hook actief.

## 12. Verificatie-commando's

```
cd forgejo-runner
python3 -m unittest discover -s tests -p 'test_*.py'   # hart + runtime
ruff check scripts/
```

## 13. Follow-up (na deze slice, buiten scope)

1. assignment-nulbewijs-adapter (Forgejo-API) → volwaardige `DRAINING` + in-place
   fence-herstel (vervangt de herstart-tak §7.5).
2. geauthenticeerde probe → echte `CREDENTIAL_ERROR`.
3. maintenance-record arming (stap F).
4. cancel/redispatch + `job_accepted`-detectie + terminale-status-correlatie.
5. trust-hardfout → echt `QUARANTINED`-label.

## 14. Risico's / open punten

- **Herstart-tak (§7.5)** is een bewuste degradatie; codex-review moet toetsen of
  hij nooit een crash-loop wordt (voorwaarde: alleen bij herstelde transport +
  gefencete impasse; trust/DinD-fout gebruikt hem niet).
- **`docker compose run` exitcode-propagatie** moet de runner-exit trouw
  doorgeven; te bevestigen in de max2-smoke.
- **`job_accepted` uitstellen** verliest het `RUNNING`-label en de
  `_commit_of_onthoud`-uitstel tijdens een job; te bevestigen dat dit alleen
  toestand-rapportage raakt, niet de jobafhandeling.
- **`scrum4me-server` Python-versie** (stap G, byte-identieke bundel) moet
  `tomllib` (3.11+) hebben; te meten vóór stap G, niet in deze slice.
