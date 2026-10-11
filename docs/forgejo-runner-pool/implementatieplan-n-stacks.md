# Implementatieplan — N runnerstacks op `max2` (M52, delta R17)

> **Status:** plan bij ontwerpdelta R17 (`migratieontwerp.md` §13), opgesteld 11 oktober 2026, in review-loop (ronde 1 verwerkt, zie "Review record"); **niet uitgevoerd**. Dit document wijzigt geen host. Fase 1 is repo-werk (code en tests); fase 2 is read-only; fase 3 en later vragen een afzonderlijke opdracht van JP en worden op `max2` uitgevoerd (`max2:claude`). Credential- en adminstappen zijn JP-only. Bij een rode gate: stop en meld JP; geen gate versoepelen.

**Doel:** stack `max2-forgejo-runner-03` naast de bestaande `-02` op `max2` live brengen, met N = 2 als goedgekeurde grens (`-04` is parametriseerbaar maar niet goedgekeurd), zodat drie runners (twee op `max2`, één op `scrum4me-server`) de CI-vraag van typisch 15–20 gelijktijdige jobs bedienen in plaats van twee.

**Eerste bruikbare resultaat:** `-03` online, exact de labels van `labels.txt`, isolatie tussen stacks bewezen vóór de controller jobs aanneemt, drie jobs gelijktijdig verdeeld, en een gemeten mediane wachttijd van Scrum4Me daarna. **Niet-doelen:** Runner 13 en zijn canary, rootless DinD, een poolscheduler, een commandokanaal tussen stacks, een hostbrede scrubvergrendeling, een nieuw drain-subsysteem in de controller, een wijziging aan `scrum4me-server` of aan stack `02` (behalve de ene `.env`-toevoeging van fase 2b).

**Spec:** `migratieontwerp.md` §13 "Delta R17" (normatief), met §3–§12 zoals daar gewijzigd. Bronbestanden: `forgejo-runner/compose.yaml`, `controller.toml.example`, `forgejo-runner-cycle.service`, `forgejo-runner-dind-guard.service`, `scripts/{dind-guard,verify-stack,preflight,cycle_adapters,cycle_runtime}.*`.

## Global constraints

- Geen secrets, tokens, UUID's of `.runner`-inhoud in Git, bewijs, antwoorden of issues.
- Nooit een compose-bestand kopiëren om een stack te maken; alle stacks gebruiken `forgejo-runner/compose.yaml` met `-p <projectnaam>` en `--env-file <per-stack-env>`. Compose-acties altijd met expliciete projectnaam, check-first (`ps`), nooit op het project `forgejo-runner` van stack `02` tenzij die stack zelf het onderwerp is.
- Stack `02` en de runner op `scrum4me-server` worden niet herstart, herconfigureerd of verplaatst; de enige toegestane wijziging aan `02` is de niet-herstartende `.env`-toevoeging van fase 2b. **Nooit `forgejo-runner-dind-guard.service` herstarten terwijl een cycle-unit actief is** (`Requires=` herstart dan ook de cycle-unit en breekt een lopende job af).
- Caps per stack blijven gelijk (runner 1,0 vCPU/1 GiB/256 PID; DinD 11,5 vCPU/5 GiB/2048 PID). Geen lagere caps alleen op `max2`.
- `preflight.sh` wordt niet versoepeld. Een waiver is een gedocumenteerd besluit van JP (D7), geen groene gate.
- Er bestaat geen niet-onderbrekende drain (README "Een lopende job niet onderbreken"). Stoppen van een controller gebeurt alleen na een pauze van het runnerrecord in Forgejo door JP en de drie README-controles; er komt geen drain-code bij.
- Controleer vóór iedere hostactie dat er geen Forgejo 17.0-venster, ISS-5-compose-opruiming of Stap G-uitvoering loopt.

## Voorwaarden

| # | Voorwaarde | Geldt vóór | Bewijs |
|---|---|---|---|
| P1 | R16 heeft GO en R17 bouwt op die tekst | GO op R17 | reviewrecord in §13 |
| P2 | ISS-49 (DinD-guard) is voor `fr-dind0` bewezen werkend; voor `fr-dind1` bewezen vóór de controller van `-03` wordt ingeschakeld | fase 3, stap 6 (`fr-dind1`) | gedragsproef per bridge (G3) |
| P4 | 24-uursmeting U2 afgerond (tot 2026-10-12 05:03 UTC) en besluitrecord U4 met D7 genomen: de *projectie* van de N = 2-belasting. Een caps-wijziging binnen §7.8 kan N = 2 op geheugen niet groen maken (de ondergrenzen alleen, 10 GiB, overschrijden het budget van 9,79 GiB); de echte opties zijn een waiver, meer hostgeheugen of vrijgemaakte `MemAvailable`, of een §7.8-methodewijziging met een eigen delta | fase 3 | U4-record |
| P5 | Vernieuwde, gedateerde acceptatie door JP: N privileged DinD's en one-job-venster per stack | fase 3 | besluitrecord |

P3 (oorzaak van het rode trustverdict van 2026-10-04 22:02:48Z tot 2026-10-05 09:30:04Z) is **geen voorwaarde**; het is alleen de trigger voor T8. P6 (waargenomen jobduur en `MemAvailable` onder N = 2) is **geen voorwaarde vooraf**: N = 2 bestaat pas na fase 3 en P6 is de acceptatiepoort aan het einde van fase 3 (stap 11).

## Fase 1 — bundelwijzigingen (repo-werk, geen host)

Branch van `main` op `janpeter/scrum4me-server`, expliciete paden, PR via de Forgejo API. Iedere taak: eerst de test (rood om de juiste reden), dan de wijziging.

- **T1 — compose-sjabloon parametriseren.** `forgejo-runner/compose.yaml`: `STACK_BRIDGE`, `STACK_VOLUME`, `STACK_CONFIG`, `STACK_TOKEN` zonder standaardwaarde (`${VAR:?…}`). `.env.example` blijft de **eenstack-waarden van `-02`** dragen (en krijgt de vier variabelen met de `-02`-waarden), zodat Stap G A2 (`cp .env.example .env`) ongewijzigd blijft; per-stack-envs worden uit de §5-tabel van R17 geschreven en nooit uit `.env.example` gekopieerd. *Acceptatie:* `tests/test_compose_contract.bats` uitgebreid: (a) met alle vier gezet verschilt `docker compose config` niet van het huidige resultaat voor stack `02` (byte-gelijk); (b) ontbreekt één variabele, dan faalt `config -q`; (c) twee stacks met dezelfde waarde falen in het statische deel van T4. *Let op:* `${VAR:?}` laat ook `stop`/`down` falen zonder env: README noemt `--env-file` bij ieder subcommando.
- **T2 — controller geeft env-file door.** `scripts/cycle_adapters.py`, `scripts/cycle_runtime.py`, `controller.toml.example`: optionele sleutel `env_file` in `[dind]`; indien gezet voegt de compose-opdracht `--env-file <pad>` toe, anders ongewijzigd gedrag (stack `02` zet hem niet). De padvalidatie van ISS-47 (leesbaarheid, geen `/home`) geldt ook voor `env_file`. Daarnaast valideert `cycle_runtime --check` dat de stack-id in het configpad twee cijfers is. *Acceptatie:* nieuwe unittests (`tests/test_cycle_*`): met en zonder `env_file`; onleesbaar pad geeft exit 2 van `--check`; ongeldig stack-id geeft exit 2; bestaande suite groen.
- **T3 — template-unit.** `forgejo-runner-cycle@.service`: gelijk aan de bestaande cycle-unit, maar `--config /opt/forgejo-runner-stacks/%i/controller.toml`, `Requires`/`After` op `forgejo-runner-dind-guard.service`, zelfde hardening. Systemd kan instantienamen niet beperken; de validatie van `%i` gebeurt in `ExecStartPre=` (`cycle_runtime.py --check`, zie T2). README "Uitrollen" krijgt de installatie van de template (`install -o root -g root`). *Acceptatie:* `systemd-analyze verify` op de unit; een test die `--check` met `%i` = `3`, `abc` of `0003` laat falen en `03` laat slagen.
- **T4 — `verify-stack.sh` N-bewust, twee delen.** `--stacks "02 03"` met `--pre-start` (statisch) of zonder (runtime). *Statisch deel (exit 66, vóór enige start):* per aangekondigde stack unieke projectnaam, bridge, volume en tokenpad uit de **effectieve** waarden van `docker compose -p <project> [--env-file …] config`; `controller.toml` en per-stack-env wijzen naar dezelfde waarden; alle niet-`STACK_*`-sleutels (image-pins, caps) zijn gelijk over alle per-stack-envs; tokenbestanden onderling verschillend (SHA-256-vergelijking, niets printen). *Runtime-deel (exit 66):* waargenomen DinD-set (label `com.docker.compose.service=dind`, project begint met `forgejo-runner`) gelijk aan de verwachte set; de fail-closed-regel voor een ontbrekende DinD (`verify-stack.sh:77`) blijft. *Exit 63:* ook `forgejo-runner-cycle@.service` byte-gelijk met de bundelkopie; een instantie zonder template of een afwijkende template faalt. *Exit 64:* ook iedere aangekondigde per-stack-map (root-eigendom, niet groep-/wereldschrijfbaar) met uitzondering van `credentials/`. *Exit 65:* de gedragsproef neemt nu **alle** DinD-containers in plaats van `head -n 1` (`verify-stack.sh:73-74`; de `ss`-isolatiecontrole, exit 62, blijft op :57-61). Zonder `--stacks` blijft het gedrag identiek aan nu. *Acceptatie:* `tests/test_verify_stack.bats` met een test per exit (60–66), gestubde `docker`, `ss`, `systemctl`, inclusief dubbele bridge, dubbel volume, dubbel tokenbestand, afwijkende pins tussen per-stack-envs, ontbrekende template, ontbrekende DinD, en een **volgordetest** die drie toestanden onderscheidt: "voorbereid" (statisch groen, geen DinD: runtime-deel niet vereist), "alleen DinD" (statisch en runtime groen, controller gestopt) en "runner ingeschakeld" (alle controles plus de guardproef).
- **T5 — `dind-guard.sh` voor alle bridges.** `BRIDGE` wordt de wildcard `fr-dind+`; `apply` en `check` blijven idempotent; de unittekst (`forgejo-runner-dind-guard.service`) volgt. *Acceptatie:* `tests/test_dind_guard.bats` met gestubde iptables: (a) schone wildcardfixture geeft de regelvorm `-o fr-dind+ -p tcp --dport 2375/2376 -j REJECT --reject-with tcp-reset`; (b) **overgangstest**: een fixture met alleen de oude `-o fr-dind0`-regels geeft na `apply` de wildcardregels, en `check` slaagt pas daarna; de oude regels blijven onschadelijk. Bridgenamen blijven ≤ 15 tekens (`fr-dind0`..`fr-dind9`).
- **T6 — `preflight.sh` N-bewust.** `--stacks N` (standaard 1): vCPU-som en geheugensom worden `N ×` per-stack; de schijfregel wordt `N × (images + 20 GiB)`. `preflight.sh` rekent inline (`python3 -c`, regels 40-41) en roept `compute_caps.py` niet aan; `compute_caps.py` en zijn tests blijven ongewijzigd. *Acceptatie* (`tests/test_preflight.bats`): op de Stap-A-gegevens van `max2` (28 vCPU; 21.029.359.616 bytes) is N = 1 groen (exit 0), N = 2 rood op vCPU én geheugen (exit 40, beide redenen genoemd), N = 3 rood; zonder `--stacks` is de uitvoer byte-gelijk aan die van vandaag.
- **T7 — bundelhash en README.** `bundle-hash.sh` ongewijzigd (de template zit in de gehashte verzameling; per-stack-mappen staan buiten de bundel); README beschrijft de per-stack-map met eigendomsinvariant, de naamconventie van R17 §5 en het rollbackrecept per stack. *Acceptatie:* `bundle-hash.sh --list` bevat de template en geen per-stack-bestand; `secret-scan.sh` groen.
- **T8 — trustcadans (voorwaardelijk).** Alleen als de oorzaak van het rode verdict (P3) een snellere hermeting rechtvaardigt; anders vervalt T8. *Acceptatie* dan: een test die het gedrag bij een rood, niet-hard verdict toont, zonder dat een hard of onleesbaar verdict sneller wordt vrijgegeven.

Spike **S1** (read-only op een wegwerpmap, geen host): bewijs dat `docker compose -f <bundel>/compose.yaml -p <naam> --env-file <elders>/.env config` de relatieve paden (`./runner-config.yml`, `./allowed-job-images.txt`) naar de bundelmap laat verwijzen, niet naar de map van het env-bestand; en dat met `--env-file` gezet en een ontbrekende variabele `config` **faalt** en niet terugvalt op de `.env` van de projectmap. Valt het eerste anders uit, dan wordt `STACK_CONFIG` een absoluut pad per stack en blijft T1 ongewijzigd.

Verificatie fase 1: volledige testsuite van `forgejo-runner/tests` groen, `docker compose config -q` met de vier variabelen, `shellcheck` waar de bundel dat al eist, en de bundelcommit-SHA plus de canonieke hash genoteerd (nodig voor fase 2b/3 en voor de pinverschuiving van Stap G).

## Fase 2 — read-only metingen op `max2` (door `max2:claude`, alleen metingen)

- **G2.** `preflight.sh --stacks 2` met live facts van `max2`: **verwacht rood op vCPU en geheugen** (exit 40); de uitvoer wordt bij het D7-besluit bewaard. Een groene uitkomst betekent dat de aannames uit R17 §7.8 niet kloppen: stop en meld.
- **G4.** Geen hostlistener op 2375/2376 (`ss -ltn`); geen host-Docker-socket in de runnerservice (`docker inspect`).
- **G5.** Het hostverdict is groen, de bindinghashes kloppen met `labels.txt` en `trusted-actions-scope.yml`, `measured_at` is vers.
- **G6.** De Forgejo-runnerrecords: uitsluitend `-02` en de runner op `scrum4me-server` bieden `ubuntu-latest` aan; geen ander record dat de labels kan aanbieden.
- **G7.** Inventariseer de huidige guardregels (`iptables -S OUTPUT | grep fr-dind`), de `.env` van `-02` (alleen sleutelnamen) en welke units actief zijn; leg dit vast als voor-staat van fase 2b.

## Fase 2b — overgang van de levende stack `-02` naar de R17-bundel (geordend, niet read-only)

Dit is de enige mutatie aan `-02` en gebeurt zonder herstart van `-02`. Stop bij elke afwijking.

1. Back-up van `/opt/forgejo-runner/.env` (mode 0600, onder `/srv/_attic/<datum>/` met MANIFEST) en toevoegen van de vier legacy-equivalente, niet-geheime waarden voor `-02`: `STACK_BRIDGE=fr-dind0`, `STACK_VOLUME=forgejo-runner-dind-data`, `STACK_CONFIG=./runner-config.yml`, `STACK_TOKEN=/opt/forgejo-runner/credentials/forgejo-token`.
2. **G1.** Render de nieuwe `compose.yaml` vanuit een stagingkopie tegen die `.env` (`docker compose --project-directory /opt/forgejo-runner -p forgejo-runner -f <staging>/compose.yaml config`) en vergelijk byte voor byte met de huidige uitvoer, vóór installatie. Afwijking: stop.
3. Installeer de bundelcommit uit fase 1 (`install -o root -g root`), schrijf `BUNDLE_COMMIT`.
4. Pas de wildcardregel van de guard toe met `bash /opt/forgejo-runner/scripts/dind-guard.sh apply`, direct; herstart de guard-unit niet.
5. Herinstalleer de gewijzigde vaste units (inclusief de guard-unittekst) en voer `systemctl daemon-reload` uit **zonder** herstart van een unit.
6. `verify-stack.sh <SHA> <HASH>` zonder `--stacks` (groen) en **G3a**: de guardproef voor `fr-dind0` (TCP-connect vanaf de host naar het DinD-adres op 2375 en 2376 faalt).
7. Controleer dat `-02` onaangeroerd is: containerstarttijden ongewijzigd, geen herstart van de cycle-unit, de eerstvolgende job loopt normaal.

## Fase 3 — uitrol stack `-03` (door `max2:claude`, JP-stappen aangegeven; na P1, P2 voor `fr-dind0`, P4, P5)

1. **[JP]** Maak het global runnerrecord `max2-forgejo-runner-03` met exact het label van `labels.txt`; plaats het token zelf in `/opt/forgejo-runner-stacks/03/credentials/forgejo-token` (map 0700, bestand 0600, eigenaar de runner-UID). Geef alleen de UUID door.
2. Maak `/opt/forgejo-runner-stacks/03/` met root-eigendom en niet groep-/wereldschrijfbaar voor map, `.env`, `controller.toml`, `runner-config.yml` en `state/` (alleen `credentials/forgejo-token` is van de runner-UID, 0600). `.env` bevat alleen niet-geheime waarden, geschreven uit de §5-tabel van R17 (`STACK_BRIDGE=fr-dind1`, `STACK_VOLUME=forgejo-runner-03-dind-data`, `STACK_CONFIG=/opt/forgejo-runner-stacks/03/runner-config.yml`, `STACK_TOKEN=/opt/forgejo-runner-stacks/03/credentials/forgejo-token`, imagepins en caps gelijk aan `-02`).
3. Render de config: `bash /opt/forgejo-runner/scripts/render-config.sh --uuid <UUID> --labels /opt/forgejo-runner/labels.txt --policy /opt/forgejo-runner/runner-config.policy.yml --out /opt/forgejo-runner-stacks/03/runner-config.yml`. Maak `controller.toml` met `project = "forgejo-runner-03"`, eigen `marker_path`, `env_file`, `compose_file = "/opt/forgejo-runner/compose.yaml"` en het hostverdict als `verdict_path`. `cycle_runtime.py --config controller.toml --check` geeft exit 0.
4. **Statisch deel van exit 66:** `verify-stack.sh <SHA> <HASH> --stacks "02 03" --pre-start` groen. Een rood resultaat is een stop.
5. **Alleen de DinD starten, controller gestopt.** `docker compose -p forgejo-runner-03 -f /opt/forgejo-runner/compose.yaml --env-file /opt/forgejo-runner-stacks/03/.env up -d dind` (eerst `ps` tonen). `forgejo-runner-cycle@03.service` blijft gestopt en niet ingeschakeld.
6. **Isolatiebewijs vóór de controller.** (a) Runtime-deel van exit 66 groen (`--stacks "02 03"`); (b) **G3b**: guardproef voor `fr-dind1`; (c) cross-stackproef in een gecontroleerde testcontext: een container in de DinD van `-03` bereikt de DinD-API van `02` niet en ziet geen containers van `02`, en omgekeerd (Docker-isolatie tussen bridges, FORWARD `fr-dind1` ↔ `fr-dind0`); een mislukte probe is een stop voor `-03`. Daarna `ss` en `docker inspect` (G4).
7. Pas nu `systemctl enable --now forgejo-runner-cycle@03.service` en volg tot `WAITING`; draai opnieuw het runtime-deel van exit 66.
8. **Bewijzen** (iedere stap met runner-ID en job-URL): `-03` online en exact de labels (**exact-labelgelijkheidsproef**: de config en de Forgejo-weergave dragen precies `labels.txt`; het verdict dwingt dat niet af); drie gelijktijdige jobs verdelen zich over de drie runners; één bewust groene en één bewust rode testjob geven procesexit 0, groene scrub en terugkeer naar `WAITING`; een ongeldige testconfig in een geïsoleerde aanroep geeft quarantaine met de wachttijd van §7.9; `docker ps`, `ss`, `docker inspect` tonen geen hostlistener, geen socket en geen token in omgeving of command.
9. **Failovertest zonder herstart van `-02`.** JP pauzeert het runnerrecord van `-02` in Forgejo (runner-ID-gebonden; geen herstart of herconfiguratie van `-02`); jobs landen op `-03` of op `scrum4me-server`; JP heropent `-02`. Daarna hetzelfde voor `-03`. Iedere pauze met de drie README-controles en het Forgejo-side nulbewijs (twee snapshots, tien seconden uiteen).
10. Leg bundelcommit, canonieke hash, stackset, `verify-stack.sh`-uitvoer en de bewijzen vast onder `evidence/n-stacks/`, zonder secrets of UUID's.
11. **Acceptatiepoort (P6):** na 24 uur met N = 2: gemeten jobduur en `MemAvailable` onder echte N = 2-belasting en de mediane en p90-wachttijd voor Scrum4Me en Ops-dashboard, vergeleken met de baseline van M52-U1 (370–440 s mediaan). Bij een host-OOM, throttling van productie of lage `MemAvailable` volgt de rollback hieronder.

## Fase 4 — stabiliteit en monitoring

Zeven aaneengesloten dagen het deelcriterium van R17 §9 (per stack plus stackstel, inclusief de terugkerende cross-stackproef); ieder afwijkend incident reset de teller van alle `max2`-stacks. Monitoring volgens R17 §10: per stack-id gelabeld, plus hostsom tegen het budget van §7.8; een afwezige DinD is alleen toegestaan voor een stack in een gedocumenteerde niet-`WAITING`-toestand. Een meting van gelijktijdig scrubben op `max2` (aantal, duur, IO) beantwoordt of een hostbrede scrubvergrendeling ooit nodig is; zonder die meting komt hij er niet.

## Rollback

Per stack, zonder drain-subsysteem: (1) JP pauzeert het runnerrecord van die stack in Forgejo (runner-ID-gebonden); (2) de drie README-controles ("Een lopende job niet onderbreken") en het Forgejo-side nulbewijs tonen dat de stack idle is; (3) `systemctl stop` en `disable` van `forgejo-runner-cycle@03.service`; (4) `docker compose -p forgejo-runner-03 -f /opt/forgejo-runner/compose.yaml --env-file /opt/forgejo-runner-stacks/03/.env ps` tonen en bevestigen, dan `… down` (zonder `-v`; het volume blijft); (5) runnerrecord `-03` naar disabled; (6) token en per-stack-map blijven tot de rollbackperiode sluit en gaan daarna weg. Stack `02`, de runner op `scrum4me-server` en de bundel blijven ongemoeid. De bundelwijziging draait terug met een revert en dezelfde uitrol op beide hosts; de `.env`-toevoeging van fase 2b blijft staan (onschadelijk) of wordt uit de back-up hersteld.

## Open punten

Zie R17 "Open beslispunten": ISS-49-status (P2), vernieuwde acceptatie (P5), D7 (P4), oorzaak van het rode verdict (alleen trigger voor T8), verhuizing van stack `02`, `-04`. Verschuiving van de bundelcommit raakt `implementatieplan-stap-g.md` (pin in A1): bump de pin vóór Stap G start.

## Review record

### Ronde 1 — 11 oktober 2026 — NO-GO (verwerkt)

**Reviewers:** Codex-dispatchjob (request `a130d8a0-4e1e-49be-8ee4-7e0718745bde`, root_message_id `a46c1fac-f673-4d69-b56a-09f9479dcf14`, idempotency-key `75068a27-ff77-42a9-89be-87fdbcedc22f`) en Claude-dispatchjob (request `ea6509db-c0ac-49ab-b6f5-d0a2ebeda7c4`, root_message_id `b9f21a32-808e-453e-a7ae-38ec8f113e1e`, idempotency-key `fd7bd18c-c50d-42c4-8f21-828649734185`).

**Pins:** `migratieontwerp.md` sha256 `d3d08d5dbeef5c75b31724958cb629e3f1599a6db2c7a9246c5f7ee36224c75b` en `implementatieplan-n-stacks.md` sha256 `429435d41b4b6307b3b30ab22b46c60be7933a1b388a40062c2b14a3f69d9f68` @ `40a5c43f0289247e21b17737c5a45162c3039ca5` (base_sha idem).

**Verdicten:** beide NO-GO. Codex: 2 BLOCKER / 3 MAJOR / 2 MINOR. Claude: 0 BLOCKER / 3 MAJOR / 8 MINOR. Alle bevindingen zijn tegen de boom gecontroleerd en geaccepteerd; geen afgewezen.

| # | Bevinding | Oordeel | Remedie |
|---|---|---|---|
| F1 | exit 66 kon vóór de start niet slagen; guardproef kwam na `WAITING` | accept | exit 66 gesplitst (statisch `--pre-start`, runtime); fase 3 herordend: DinD-only-bootstrap met gestopte controller, isolatiebewijs, dan pas `enable --now`; volgordetest in T4 |
| F2 | P6 vereiste een N = 2-meting vóór N = 2 bestaat | accept | projectie (P4) gescheiden van waargenomen prestatie; P6 verplaatst naar acceptatiepoort (fase 3, stap 11) |
| F3 | overgang van levende `-02` ontbrak (`.env`, guardwildcard, guard-herstart, "read-only" fase installeerde) | accept | fase 2 echt read-only; nieuwe fase 2b met geordende overgang; `.env`-toevoeging als enige toegestane wijziging aan `-02`; guard direct toepassen; overgangstest in T5 |
| F4 | "DRAINING, daarna stop" bestaat niet (SIGTERM breekt job af) | accept | Forgejo-kant-pauze per runner-ID + README-controles; failovertest zonder herstart van `-02`; §11, fase 3 stap 9 en rollback aangepast; geen nieuw drain-subsysteem |
| F5 | D7-optie "caps-wijziging" werkt niet voor geheugen | accept | zin in ontwerp §7.8, open punt 4 en P4: de ondergrenzen alleen (10 GiB) overschrijden het budget van 9,79 GiB |
| F6 | S1 miste test op `--env-file` zonder terugval op projectmap-`.env` | accept | test toegevoegd aan S1 |
| F7 | pins en caps gedupliceerd in per-stack-envs zonder gelijkheidscontrole | accept | statisch deel van exit 66 vergelijkt alle niet-`STACK_*`-sleutels |
| F8 | per-stack-map zonder eigendomsinvariant | accept | root-eigendom vastgelegd; exit 64 uitgebreid naar aangekondigde stackmappen (behalve `credentials/`) |
| F9 | onjuiste boomclaims (i–vi) | accept | (i) `head -n 1` zit in de guardproef (exit 65, :73-74), `ss` is exit 62 (:57-61); (ii) `marker_path` staat in `controller.toml`; (iii) 20 GiB; (iv) volledig `render-config.sh`-commando met `--out`; (v) verdict wordt tegen het eigen `labels_file` getoetst, exact-labelproef blijft nodig; (vi) `%i`-validatie in `--check` via `ExecStartPre=`, niet via systemd |
| F10 | inter-bridge-isolatie niet benoemd | accept | Docker-isolatie (FORWARD) als beheersing benoemd, probe in terugkerend §9-criterium, mislukte probe = stop voor `-03` |
| F11 | `headroom_ok(stacks=)` is dode wijziging; P3 onterecht voorwaarde | accept | `compute_caps.py` ongewijzigd, alleen `preflight.sh --stacks N`; P3 alleen trigger voor T8; kop eenduidig |
| F12 | `.env.example` en Stap G A2 | accept | `.env.example` draagt de eenstackwaarden van `-02`; per-stack-envs nooit uit `.env.example` |

**Scope-delta ronde 1:** geen nieuwe component. P6 verplaatst naar de canary-acceptatie; P3 uitgesteld naar T8; `compute_caps.headroom_ok(stacks=)` geschrapt; toegevoegd zijn twee volgordestappen (fase 2b en de DinD-only-bootstrap), de statisch/runtime-splitsing van exit 66 en een eigendomsinvariant. Eerste bruikbare resultaat (een bouwbaar ontwerp voor `-03`) en praktijkproef (canary van `-03` na U2/D7/acceptatie) ongewijzigd.
