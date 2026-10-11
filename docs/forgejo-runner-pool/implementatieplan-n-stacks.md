# Implementatieplan — N runnerstacks op `max2` (M52, delta R17)

> **Status:** plan bij ontwerpdelta R17 (`migratieontwerp.md` §13), opgesteld 11 oktober 2026, **nog niet gereviewd en niet uitgevoerd**. Dit document wijzigt geen host. Fase 1 is repo-werk (code en tests); fase 2 en later vragen een afzonderlijke opdracht van JP en worden op `max2` uitgevoerd (`max2:claude`). Credential- en adminstappen zijn JP-only. Bij een rode gate: stop en meld JP; geen gate versoepelen.

**Doel:** stack `max2-forgejo-runner-03` naast de bestaande `-02` op `max2` live brengen, met N = 2 als goedgekeurde grens (`-04` is parametriseerbaar maar niet goedgekeurd), zodat drie runners (twee op `max2`, één op `scrum4me-server`) de CI-vraag van typisch 15–20 gelijktijdige jobs bedienen in plaats van twee.

**Eerste bruikbare resultaat:** `-03` online, exact de labels van `labels.txt`, isolatie tussen stacks bewezen, drie jobs gelijktijdig verdeeld, en een gemeten mediane wachttijd van Scrum4Me daarna. **Niet-doelen:** Runner 13 en zijn canary, rootless DinD, een poolscheduler, een commandokanaal tussen stacks, een hostbrede scrubvergrendeling, een wijziging aan `scrum4me-server` of aan stack `02`.

**Spec:** `migratieontwerp.md` §13 "Delta R17" (normatief), met §3–§12 zoals daar gewijzigd. Bronbestanden: `forgejo-runner/compose.yaml`, `controller.toml.example`, `forgejo-runner-cycle.service`, `scripts/{dind-guard,verify-stack,preflight,compute_caps,cycle_adapters}.*`.

## Global constraints

- Geen secrets, tokens, UUID's of `.runner`-inhoud in Git, bewijs, antwoorden of issues.
- Nooit een compose-bestand kopiëren om een stack te maken; alle stacks gebruiken `forgejo-runner/compose.yaml` met `-p <projectnaam>` en `--env-file <per-stack-env>`. Compose-acties altijd met expliciete projectnaam, check-first (`ps`), nooit op het project `forgejo-runner` van stack `02` tenzij die stack zelf het onderwerp is.
- Stack `02` en de runner op `scrum4me-server` worden niet herstart, herconfigureerd of verplaatst.
- Caps per stack blijven gelijk (runner 1,0 vCPU/1 GiB/256 PID; DinD 11,5 vCPU/5 GiB/2048 PID). Geen lagere caps alleen op `max2`.
- `preflight.sh` wordt niet versoepeld. Een waiver is een gedocumenteerd besluit van JP (D7), geen groene gate.
- Controleer vóór iedere hostactie dat er geen Forgejo 17.0-venster, ISS-5-compose-opruiming of Stap G-uitvoering loopt.

## Voorwaarden (alle groen vóór fase 3; P1–P3 ook vóór GO op het ontwerp waar vermeld)

| # | Voorwaarde | Bewijs |
|---|---|---|
| P1 | R16 heeft GO en R17 bouwt op die tekst | reviewrecord in §13 |
| P2 | ISS-49 (DinD-guard) is voor de bestaande bridge `fr-dind0` bewezen werkend; voor `fr-dind1` bewezen vóór `-03` live gaat | gedragsproef per bridge (G3) |
| P3 | Oorzaak van het rode trustverdict van 2026-10-04 22:02:48Z tot 2026-10-05 09:30:04Z is vastgesteld | journal `forgejo-runner-trust.service` en controllerlog op `max2` |
| P4 | 24-uursmeting U2 afgerond (tot 2026-10-12 05:03 UTC) en besluitrecord U4 met D7 genomen | U4-record |
| P5 | Vernieuwde, gedateerde acceptatie door JP: N privileged DinD's en one-job-venster per stack | besluitrecord |
| P6 | Gemeten jobduur en `MemAvailable` van `max2` onder N = 2 zijn in U4 verwerkt | U4-record |

## Fase 1 — bundelwijzigingen (repo-werk, geen host)

Branch van `main` op `janpeter/scrum4me-server`, expliciete paden, PR via de Forgejo API. Iedere taak: eerst de test (rood om de juiste reden), dan de wijziging.

- **T1 — compose-sjabloon parametriseren.** `forgejo-runner/compose.yaml`: `STACK_BRIDGE`, `STACK_VOLUME`, `STACK_CONFIG`, `STACK_TOKEN` zonder standaardwaarde (`${VAR:?…}`). `.env.example` en README noemen de vier variabelen. *Acceptatie:* `tests/test_compose_contract.bats` uitgebreid: (a) met alle vier gezet verschilt `docker compose config` niet van het huidige resultaat voor stack `02` (byte-gelijk); (b) ontbreekt één variabele, dan faalt `config -q`; (c) twee stacks met dezelfde waarde falen in de invariantcheck van T4. *Let op:* `${VAR:?}` laat ook `stop`/`down` falen zonder env (zie compose-draaiboekvalkuil): de README noemt `--env-file` bij ieder subcommando.
- **T2 — controller geeft env-file door.** `scripts/cycle_adapters.py`, `scripts/cycle_runtime.py`, `controller.toml.example`: optionele sleutel `env_file` in `[dind]`; indien gezet voegt de compose-opdracht `--env-file <pad>` toe, anders ongewijzigd gedrag. De padvalidatie van ISS-47 (leesbaarheid, geen `/home`) geldt ook voor `env_file`. *Acceptatie:* nieuwe unittests (`tests/test_cycle_*`): met en zonder `env_file`, onleesbaar pad geeft exit 2 van `--check`; bestaande suite groen. *Alternatief als `--env-file` niet volstaat* (bijvoorbeeld bij relatieve paden in het sjabloon): spike S1 hieronder vóór T2 afronden.
- **T3 — template-unit.** `forgejo-runner-cycle@.service`: gelijk aan de bestaande cycle-unit, maar `--config /opt/forgejo-runner-stacks/%i/controller.toml`, `Requires`/`After` op `forgejo-runner-dind-guard.service`, zelfde hardening (`NoNewPrivileges`, `ProtectHome`, `TimeoutStopSec=300`). `README` "Uitrollen" krijgt de installatie van de template (`install -o root -g root`). *Acceptatie:* `systemd-analyze verify` op de unit, en een test die bewijst dat `%i` alleen `[0-9]{2}` accepteert.
- **T4 — `verify-stack.sh` N-bewust.** Argument `--stacks "02 03"`; vergelijk `forgejo-runner-cycle@.service` met de bundelkopie (exit 63 bij drift of ontbrekende template terwijl een instantie bestaat); loop de gedragsproef over **alle** DinD-containers (labels `com.docker.compose.service=dind`, project begint met `forgejo-runner`) in plaats van `head -n 1`; nieuwe stackinvariantcontrole, **exit 66**: unieke projectnaam, bridge, volume en tokenbestand per stack, en gelijke verwachte en waargenomen DinD-set. Zonder `--stacks` blijft het gedrag identiek aan nu (één stack `02`). *Acceptatie:* `tests/test_verify_stack.bats` met een test voor iedere exit (60–66) met gestubde `docker`, `ss`, `systemctl`, inclusief dubbele bridge, dubbel volume, ontbrekende template, ontbrekende DinD.
- **T5 — `dind-guard.sh` voor alle bridges.** `BRIDGE` wordt de wildcard `fr-dind+`; `apply` en `check` blijven idempotent; de unit en de tests volgen. *Acceptatie:* `tests/test_dind_guard.bats` met gestubde iptables bewijst de regelvorm `-o fr-dind+ -p tcp --dport 2375/2376 -j REJECT --reject-with tcp-reset`; de gedragsproef per bridge is G3 (host). Bridgenamen blijven ≤ 15 tekens (`fr-dind0`..`fr-dind9`).
- **T6 — `preflight.sh` en `compute_caps.py` N-bewust.** `--stacks N` (standaard 1) en `headroom_ok(caps, vcpu, lowest_mem_available, stacks=1)`: vCPU-som en geheugensom worden `N ×` per-stack; de schijfregel wordt `N × (images + 20 GiB)`. *Acceptatie* (`tests/test_compute_caps.py`, `test_preflight.bats`): op de Stap-A-gegevens van `max2` (28 vCPU; 21.029.359.616 bytes) is N = 1 groen (exit 0), N = 2 rood op vCPU én geheugen (exit 40, beide redenen genoemd), N = 3 rood; met gelijke invoer is N = 1 byte-gelijk aan de uitvoer van vandaag.
- **T7 — bundelhash en README.** `bundle-hash.sh` ongewijzigd (de template zit in de gehashte verzameling; de per-stack-mappen staan buiten de bundel); README beschrijft de per-stack-map, de naamconventie van R17 §5 en het rollbackrecept per stack. *Acceptatie:* `bundle-hash.sh --list` bevat de template en geen enkel per-stack-bestand; `secret-scan.sh` groen.
- **T8 — trustcadans (voorwaardelijk).** Alleen als P3 een oorzaak toont die een snellere hermeting rechtvaardigt; anders vervalt T8. *Acceptatie* dan: een test die het gedrag bij een rood, niet-hard verdict toont, zonder dat een hard of onleesbaar verdict sneller wordt vrijgegeven.

Spike **S1** (read-only op een wegwerpmap, geen host): bewijs dat `docker compose -f <bundel>/compose.yaml -p <naam> --env-file <elders>/.env config` de relatieve paden (`./runner-config.yml`, `./allowed-job-images.txt`) naar de bundelmap laat verwijzen, niet naar de map van het env-bestand. Valt het anders uit, dan wordt `STACK_CONFIG` een absoluut pad per stack en blijft T1 ongewijzigd.

Verificatie fase 1: volledige testsuite van `forgejo-runner/tests` groen, `docker compose config -q` met de vier variabelen, `shellcheck` waar de bundel dat al eist, en de bundelcommit-SHA plus de canonieke hash genoteerd (nodig voor fase 3 en voor de pinverschuiving van Stap G).

## Fase 2 — read-only gates op `max2` (door `max2:claude`, na P1–P6)

- **G1.** `docker compose config` van stack `02` vóór en na het uitrollen van de nieuwe bundel (zonder herstart): byte-gelijk; geen containers opnieuw aangemaakt (`docker ps` startijden ongewijzigd).
- **G2.** `preflight.sh --stacks 2` met live facts van `max2`: **verwacht rood op vCPU en geheugen** (exit 40); de uitvoer wordt bij het D7-besluit bewaard. Een groene uitkomst zou betekenen dat de aannames uit R17 §7.8 niet kloppen: stop en meld.
- **G3.** ISS-49 per bridge: de regel `fr-dind+` staat; voor iedere bestaande DinD faalt een TCP-connect vanaf de host naar het DinD-adres op 2375 en 2376 (`verify-stack.sh` exit 0 met `--stacks "02"`). Voor `fr-dind1` wordt dezelfde proef gedaan nadat de DinD van `-03` draait (fase 3).
- **G4.** Geen hostlistener op 2375/2376 (`ss -ltn`); geen host-Docker-socket in de runnerservice (`docker inspect`).
- **G5.** Het hostverdict is groen, de bindinghashes kloppen met `labels.txt` en `trusted-actions-scope.yml`, `measured_at` is vers.
- **G6.** De Forgejo-runnerrecords: uitsluitend `-02` en de runner op `scrum4me-server` bieden `ubuntu-latest` aan; geen ander record dat de labels kan aanbieden.

## Fase 3 — uitrol stack `-03` (door `max2:claude`, JP-stappen aangegeven)

1. **[JP]** Maak het global runnerrecord `max2-forgejo-runner-03` met exact het label van `labels.txt`; plaats het token zelf in `/opt/forgejo-runner-stacks/03/credentials/forgejo-token` (map 0700, bestand 0600, eigenaar de runner-UID). Geef alleen de UUID door.
2. Rol de bundelcommit uit naar `/opt/forgejo-runner` (zelfde SHA als in fase 1; `install -o root -g root`), installeer `forgejo-runner-cycle@.service`, schrijf `BUNDLE_COMMIT`.
3. Maak `/opt/forgejo-runner-stacks/03/` met `.env` (alleen niet-geheime waarden: `STACK_BRIDGE=fr-dind1`, `STACK_VOLUME=forgejo-runner-03-dind-data`, `STACK_CONFIG`, `STACK_TOKEN`, imagepins en caps zoals `-02`), `runner-config.yml` via `render-config.sh --uuid <UUID> --labels labels.txt --policy runner-config.policy.yml`, en `controller.toml` met `project = "forgejo-runner-03"`, eigen `marker_path`, `env_file`, hostverdict als `verdict_path`. `cycle_runtime.py --config controller.toml --check` geeft exit 0.
4. `verify-stack.sh <SHA> <HASH> --stacks "02 03"` voor de start: exit 66 mag niet optreden; daarna `systemctl enable --now forgejo-runner-cycle@03.service` en volg tot `WAITING`.
5. **Bewijzen** (iedere stap met runner-ID en job-URL): `-03` online en exact de labels; guard per bridge (G3 voor `fr-dind1`); jobcontainer in `-03` bereikt de DinD-API van stack `02` niet en ziet geen containers van `02`, en omgekeerd; drie gelijktijdige jobs verdelen zich over de drie runners; één bewust groene en één bewust rode testjob geven procesexit 0, groene scrub en terugkeer naar `WAITING`; ongeldige testconfig in een geïsoleerde aanroep geeft quarantaine met de wachttijd van §7.9; `docker ps`, `ss`, `docker inspect` tonen geen hostlistener, geen socket en geen token in omgeving of command.
6. Drain-test per stack: drain `-02`, jobs landen op `-03` of op `scrum4me-server`; herstel; drain `-03`, idem; elke drain met het Forgejo-side nulbewijs van §7.9.
7. Leg bundelcommit, canonieke hash, stackset, `verify-stack.sh`-uitvoer en de gemeten wachttijd (mediaan en p90 voor Scrum4Me en Ops-dashboard, 24 uur) vast onder `evidence/n-stacks/`, zonder secrets of UUID's.

## Fase 4 — stabiliteit en monitoring

Zeven aaneengesloten dagen het deelcriterium van R17 §9 (per stack plus stackstel); ieder afwijkend incident reset de teller van alle `max2`-stacks. Monitoring volgens R17 §10: per stack-id gelabeld, plus hostsom tegen het budget van §7.8. Een meting van gelijktijdig scrubben op `max2` (aantal, duur, IO) beantwoordt of een hostbrede scrubvergrendeling ooit nodig is; zonder die meting komt hij er niet.

## Rollback

Per stack: `DRAINING` en nulbewijs; `systemctl stop` en `disable` van `forgejo-runner-cycle@03.service`; `docker compose -p forgejo-runner-03 -f /opt/forgejo-runner/compose.yaml --env-file /opt/forgejo-runner-stacks/03/.env ps` tonen en bevestigen, dan `… down` (zonder `-v`; het volume blijft); runnerrecord `-03` naar disabled in Forgejo; token en per-stack-map blijven tot de rollbackperiode sluit en gaan daarna weg. Stack `02`, de runner op `scrum4me-server` en de bundel blijven ongemoeid. De bundelwijziging draait terug met een revert en dezelfde uitrol op beide hosts.

## Open punten

Zie R17 "Open beslispunten": ISS-49-status (P2), vernieuwde acceptatie (P5), oorzaak van het rode verdict (P3), D7 (P4), verhuizing van stack `02`, `-04`. Verschuiving van de bundelcommit raakt `implementatieplan-stap-g.md` (pin in A1): bump de pin vóór Stap G start.
