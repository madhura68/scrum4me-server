# Implementatieplan — Stap G: `scrum4me-server` normaliseren

> **Voor uitvoerders:** dit is een **operator-gedreven migratie** op een productiehost, geen code-implementatie. Er is **geen nieuwe bundelcode**: `scrum4me-server` rolt exact dezelfde byte-identieke bundel uit die `max2` al draait (gepinde commit-SHA). Voer stap voor stap uit met de verificatiegate ná elke fase; bij een rode gate: **stop en meld JP** (niet forceren, niet de gate versoepelen). Elke fase is afzonderlijk terug te draaien (zie Rollback).

**Doel:** de bestaande legacy Forgejo-runner op `scrum4me-server` (oud `.runner`-registratiemodel, permanente `daemon`, ongecapt, ~179 GB DinD-cache — gemeten 8 sep 2026) vervangen door dezelfde architectuur als `max2`: Runner 12.10.1 `server.connections`-config + de systemd-cyclecontroller (`one-job --wait` per job, volledige scrub tussen jobs), met de gedeelde caps.

**Architectuur:** ports & adapters cyclecontroller (byte-identiek hart), gedeelde bundel uit de `scrum4me-server`-repo op één gepinde SHA, trustgate als deploy-verdict, exclusieve DinD per host. Zie `migratieontwerp.md` §3, §6, §7.3, §7.5.

**Spec:** `docs/forgejo-runner-pool/migratieontwerp.md` — §8 stap G (normativ), §7.2 (volgorde), §7.3 (legacy→nieuw, 10 stappen), §7.4 (labels), §7.5 (DinD-isolatie), §7.7 (trust), §7.8 (headroomgate), §7.9 (drain + assignment-nulbewijs), §9 (stabiliteit), §11 (rollback). Bring-up-precedent: `evidence/stap-d/bring-up-runbook.md` (stap D/E op max2).

---

## Global Constraints (bindend, uit de spec + `CLAUDE.md`)

- **Caps zijn gelijk op beide hosts** (`evidence/stap-a/caps.env`: runner 1,0 vCPU/1 GiB, DinD 11,5 vCPU/5 GiB). Niet verlagen voor alleen `scrum4me-server`. Zelfde label = zelfde minimale uitvoeromgeving.
- **`preflight.sh` is een pre-mutatie-gate (§7.8)** — met één vastgelegde uitzondering: op `scrum4me-server` is de headroomgate **gewaiverd** (Voorwaarde 0, JP-besluit, `migratieontwerp.md` §7.8), dus daar rapporteert hij terecht ROOD en is de gedocumenteerde waiver de basis om door te gaan. De gate wordt **niet versoepeld**, geldt op `max2` onverkort, en de caps worden nergens verlaagd.
- **Geen secrets/UUID in Git** (`CLAUDE.md`-hardstop). Token uitsluitend als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`, eigendom van de runner-UID. UUID nooit in bewijs- of docbestanden.
- **Bundel niet dupliceren:** zelfde gepinde commit-SHA als `max2`. Hart byte-identiek.
- **`max2` dekt de pool tijdens elke mutatie op `scrum4me-server`** (stap D/E af, stap F groen). Geen venster waarin beide runners weg zijn zonder dat jobs kunnen queuen.
- **Control-plane-impact vereist een gearmd maintenance-record** (Forgejo + Postgres draaien op deze host; §7.7/§7.9).
- **Host-Dockerdaemon blijft draaien;** geen `/etc/docker/daemon.json`-wijziging, geen daemon-herstart, geen hostbrede prune.

---

## Voorwaarde 0 — §7.8-gate GEWAIVERD (JP-besluit 8 september 2026); geen hardware nodig

- **Gemeten 8 september 2026:** `scrum4me-server` is een **fixed fysieke box van 8 vCPU / 15 GiB** (~6,7 GiB in swap). De §7.8-gate is daar **ROOD** en de vCPU-fail is **structureel** (cap-som 12,5 > 50% × 8 = 4,0; DinD-cap 11,5 > 8 fysieke cores) — niet met ontlasten op te lossen; geheugen (~10 < 12 GiB) is last-gerelateerd.
- **Besluit JP (8 september 2026, record-and-proceed, eigen verantwoordelijkheid):** de §7.8-**headroomgate wordt voor `scrum4me-server` gewaiverd** (design-delta in `migratieontwerp.md` §7.8). Grond: de runner draait daar al maanden **ongecapt** naast productie zonder incident — sterker bewijs dan een synthetische 2×-headroomdrempel; de formele proof (preflight) is de werkelijke struikelblok, niet de capaciteit. Scoped tot `scrum4me-server`; op `max2` blijft de gate onverkort gelden.
- **Caps blijven** (identiek op beide hosts): strikt veiliger dan de huidige ongecapte legacy-runner (DinD-CPU als `cpu_period`/`cpu_quota` — de `cpus:`/NanoCpus-vorm werd door Docker geweigerd op 8 cores, gefixt in de bundel; 11,5-quota bindt niet op 8 cores; de 5 GiB DinD-geheugencap voegt een plafond toe dat de ongecapte legacy mist). Compenserende controls: `capacity: 1`, CPU-prioriteit voor productie, monitoring met auto-pause (§10) bij productie-OOM/throttle of lage `MemAvailable`, en pool-redundantie (`max2` primair; deze runner is sinds stap D/E redundant).

**Gate 0 — voor het record, NIET blokkerend (gewaiverd):**
```sh
# op scrum4me-server, vanuit de gedeployde bundel:
bash scripts/capture-host-facts.sh --out /tmp/facts.tsv
bash scripts/preflight.sh --facts /tmp/facts.tsv --caps <caps.env> --images allowed-job-images.txt
echo "exit=$?"   # ROOD/40 verwacht op deze host; preflight.sh blijft eerlijk, wordt NIET versoepeld
```
Leg de ROOD-uitkomst vast in `evidence/stap-g/` samen met een verwijzing naar de §7.8-waiver; de basis om door te gaan is de gedocumenteerde waiver, niet een groene gate. **Geen hardware-upgrade nodig, geen stackmigratie** (de eerder overwogen optie "host vergroten" is vervallen).

**Overige preconditions (blijven gelden):** stap D+E af op `max2` (✓ 8 sep 2026 — `max2` kan `scrum4me-server` vervangen bij uitval); **stap F groen** (poolgedrag + failover bewezen). Zonder deze twee mag `scrum4me-server` niet worden aangeraakt (§7.2: nooit de enige werkende runner uitschakelen).

---

> **Uitvoervolgorde (belangrijk — niet de alfabetische fase-volgorde):** A (voorbereiden) → B (cutover; **B0 hermeet éérst de schijf** — onder de drempel: C vóór E; **incl. D1/D2 direct ná Gate B: oude credentials intrekken + oud record disablen, §7.3-9**) → **E (bewijzen)** → **C (beide legacy containers verwijderen, oud volume + cert-volumes afvoeren)** → F (evidence, loopt mee) → **stap H (7 dagen stabiliseren)** → **D3 (quarantainebestand wissen ná sluiting van de rollbackperiode, §7.3-10)**. Bewijzen (E) gaat vóór afvoeren (C), tenzij B0 onder de schijfdrempel valt. Rollback loopt in élke fase via §11 (nieuwe stack), nooit via legacy — er is geen "point-of-no-return". Zie Rollback.

## Fase A — voorbereiden náást de draaiende legacy runner (§7.2, geen impact)

De legacy runner blijft in deze fase gewoon jobs uitvoeren.

- **A1.** Deploy de bundel op de gepinde SHA naar `/opt/forgejo-runner/` op `scrum4me-server` (`git archive <SHA>:forgejo-runner | tar -x` → `sudo cp -a` → schrijf `BUNDLE_COMMIT`). Zelfde SHA als `max2`. Verificatie: `BUNDLE_COMMIT` klopt, `scripts/` aanwezig.
- **A2.** `cp .env.example .env`; `docker pull` de gepinde `RUNNER_IMAGE`/`DIND_IMAGE`/`JOB_IMAGE`.
- **A3.** §4-argv-sanity (zoals `tests/test_compose_runner_exec.bats`): `docker inspect` (Entrypoint=null, Cmd=[/bin/forgejo-runner]); dan het gerenderde command tegen de image mét een read-only **mount** van een minimale dummy-config op `/etc/forgejo-runner/config.yml` (+ dummy-token op het credentialpad), `--network none` en een `timeout` → het binary is bereikt (geen `$PATH`-fout) én de config laadt (geen "No configuration file specified", geen "0 connections") — dat is de ISS-15-fix (`-c` verplicht in het compose-`command`). Gebruik géén echte registratiecredentials voor deze sanity.
- **A4.** `credentials/`-map aanmaken (0700). **[JP]** registreer het vervangend runnerrecord `scrum4me-srv-runner-01` in Forgejo op de bestaande **global** scope met het canonieke label `ubuntu-latest` → nieuwe **UUID** + **token** (§5, §7.3-3). Geef mij de UUID; plaats het token zelf als `/opt/forgejo-runner/credentials/forgejo-token`, mode 0600, eigendom runner-UID (§7.3-4). **Credential- en admin-stappen zijn JP-only.**
- **A5.** `bash scripts/render-config.sh --uuid <nieuwe-UUID> --labels labels.txt --policy runner-config.policy.yml --out runner-config.yml`. `cp controller.toml.example controller.toml`; `python3 scripts/cycle_runtime.py --config controller.toml --check` → exit 0.
- **A6.** Trust-verdict publiceren. **[JP]** in eigen shell met persoonlijk `FORGEJO_TOKEN`: `scripts/publish-trust-verdict.sh --cli-py scripts/trust_scope_cli.py --labels /opt/forgejo-runner/labels.txt --allowlist /opt/forgejo-runner/trusted-actions-scope.yml --target https://git.jp-visser.nl --out /opt/forgejo-runner/trust-verdict.json`. Verifieer `"ok":true`, verse `measured_at`, binding-hashes = de gedeployde bestanden.

**Gate A:** alle bovenstaande verificaties groen; de legacy runner draait nog ongestoord.

---

## Fase B — cutover in een onderhoudsvenster (§7.3-1..8; `max2` dekt de pool)

Kies een moment waarop `max2` de pool kan dragen. Geen Forgejo/Postgres-reboot nodig — dit raakt alleen de runner op deze host — maar plan het als onderhoud.

0. **B0 — schijf hermeten + drempel (JP-besluit 8 sep 2026: hermeten+drempel).** Vlak vóór de cutover, ná A2 (images gepulld): `df -h /` (waar `/var/lib/docker` staat), `docker system df -v`, en `du -sh` van het legacy anonieme volume (`_data`). **Drempel: ≥ 40 GB vrij op `/`** (= 2× de §7.8-werkruimtegate van 20 GiB; onderbouwing: in het B→E-venster staan het legacy volume, de nieuwe stack, de gepulde images én de E3-buildjob naast elkaar, op een host die óók Forgejo+Postgres draagt). **Onder de drempel: voer Fase C (dispose) vóór Fase E uit** — §11 rekent voor rollback niet op het oude volume. Leg de meting vast in `evidence/stap-g/`. Gemeten 8 sep 2026: volume **179 GB**, `/` **61 GB vrij / 87 %** — de stap-A-waarde (139 GB / 29 %) is achterhaald; **citeer nooit een oude meting als huidige toestand** (`CLAUDE.md`).
1. **B1 (§7.3-1).** Inventariseer het bestaande legacy record; wacht tot de legacy runner **idle** is.
2. **B2 (§7.3-2, §7.9) — de drainprocedure (hergebruikt in E2/E4).** Blokkeer nieuwe jobtoewijzing aan de oude runner (Forgejo → pause). Dan: `DRAINING` → graceful stop → **wacht minimaal de effectieve `fetch_timeout` + 10 s** (§7.9, sluit het FetchTask-ambiguïteitsvenster) → bewijs runnerrecord offline → **Forgejo-side assignment-nulbewijs** gebonden aan de runner-ID (twee snapshots 10 s uiteen, nul assigned/running). Vind je een toegewezen job zonder lokaal proces → `QUARANTINED`, wacht `min(T_requeue+30 s, 10 min)` = **10 min** (`T_requeue`=600 s, `evidence/stap-a/t-requeue.md`; brondefault + bevestiging, géén live-meting — de wachttak is dus toegestaan; herbevestig de effectieve Forgejo-versie/config vóór het venster), anders cancel + redispatch. **[JP: Forgejo-UI pauze; ik: drain/nulbewijs-meting.]**
3. **B3 (§7.3-5) — eerst de herstart-fence, dán stoppen.** De legacy containers draaien met **`restart: always`** en de legacy runner heeft een **zelf-registrerend entrypoint** (`if [ ! -f /data/.runner ]; then forgejo-runner register … --name scrum4me-srv-runner --labels "ubuntu-latest:…"; fi; exec … daemon`; het registratietoken staat nog in zijn env — `evidence/stap-a/scrum4me-server/containers.json`). Zonder fence zou de container bij de eerstvolgende herstart (reboot, automatische security-updates, `compose up`) zichzelf **opnieuw registreren** als spookrecord met het canonieke label en jobs claimen — ná Fase C zonder DinD, dus die jobs stranden. Daarom, in deze volgorde: **(a)** `docker update --restart=no scrum4me-forgejo-runner scrum4me-forgejo-dind` (beide legacy containers; bewijs: `docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' <id>` = `no` voor beide); **(b)** stop **alleen** de oude runner*container* (niet de host-daemon, niet de andere productiecontainers). De legacy **DinD** (`scrum4me-forgejo-dind`, `docker:dind`, TLS 2376, met het anonieme legacy volume — gemeten 179 GB) blijft in deze fase **draaien** en wordt in Fase C gestopt, verwijderd en afgevoerd (ná Fase E, of vóór E als B0 dat vereist). Raak het legacy compose-project verder niet aan (geen `compose down`, geen prune).
4. **B4 (§7.3-6).** Verplaats de legacy `.runner` uit het gemounte runnerpad naar een root-only quarantaine `legacy-runner.revoked.json`, mode 0600, zodat alleen `server.connections` actief is. Veilig **omdat** B3(a) de herstart-fence al heeft gezet: zonder die fence zou juist dít bestand-weghalen de herregistratie in het entrypoint triggeren. Het bestand blijft bestaan als **ingetrokken record** (§7.3-10, §9: root-only, 0600, met vastgelegde vernietigingsdatum) — **niet** als rollback-pad (§11 gebruikt de legacy `.runner` nooit).
5. **B5 (§7.3-7).** Installeer + start de cyclecontroller-unit (`forgejo-runner-cycle.service`, zoals `max2`): `docker compose -p forgejo-runner up -d --wait dind` → `systemctl daemon-reload` → `enable --now`. Volg de journal: `SOURCE_WAIT` → `READY` → `scrub ok=True` → `runner gestart` → `runner: scrum4me-srv-runner-01 … declared successfully`.
6. **B6 (§7.3-8).** Bewijs dat **alleen** het credentialbestand het actieve token draagt: `stat` op `credentials/forgejo-token`; `docker inspect` van de runnercontainer (geen token in env/command, geen socket-mount); een geschoonde configweergave. Geen secrets in `Config.Cmd`/env.

**Gate B:** `scrum4me-srv-runner-01` online/idle in Forgejo; geen token buiten het credentialbestand; `max2` bleef de pool dekken; beide legacy containers `RestartPolicy=no`. **Direct ná Gate B: D1/D2 (§7.3-9) — oude credentials definitief intrekken + oud record disablen** (zie Fase D). Dat is de spec-volgorde én de voorwaarde waaronder stap H later überhaupt groen kán worden (§9 eist het ingetrokken quarantainebestand gedurende de 7 dagen).

---

## Fase C — beide legacy containers verwijderen en het oude volume afvoeren (apart maintenance-record, §8 stap G) — ná Fase E, of vóór E als B0 dat vereist

Standaard **ná** de bewijzen van Fase E: pas als de nieuwe stack bewezen werkt, voer je het oude weg. Valt B0 onder de schijfdrempel, dan C vóór E — veilig, omdat §11 het oude volume nooit als actief rollback-pad gebruikt (alleen forensisch, en alleen met een afzonderlijk herstelbesluit). De nieuwe stack pint het volume op naam (`forgejo-runner-dind-data`, al door B5 gemaakt) en koppelt het oude anonieme legacy-volume **nooit** aan; `scrub-dind.sh` kan die data dus niet bereiken. De handeling is een **dispose**, geen scrub — een **bewuste afwijking van §7.9's volgorde** (die de bestaande DinD éérst scrubt en dán een schoon volume maakt; hier bestaat het schone benoemde volume al en draait het). **Schijf: zie B0** — citeer géén oude meting; budgetteer op de dán gemeten omvang (8 sep 2026: 179 GB).

- **C1.** Inventariseer en leg vast: de container-ID's van de legacy `scrum4me-forgejo-runner` (gestopt sinds B3) én `scrum4me-forgejo-dind`; de oude anonieme volume-ID; de **twee named cert-volumes** van de legacy DinD (`forgejo_dind-certs-ca` → `/certs/ca`, `forgejo_dind-certs-client` → `/certs/client`); en de **opnieuw gemeten dataomvang** (`du -sh` op `_data`; verwacht ~179 GB, niet ~121).
- **C2.** Arm een **afzonderlijk** maintenance-record (eigen `maintenance_id`, UTC-start, harde UTC-eindtijd — bepaald uit de **in C1 gemeten** dataomvang + een **proefmeting van een `docker volume rm` op dezelfde storageklasse**; niet uit een oud getal). Dit venster begrenst de dispose; de harde eindtijd + het schoonbewijs (C4) sluiten het. (Er worden **geen** §9-`SCRUBBING`-criteria opgeschort: die gelden voor een scrub-cyclus van de draaiende controller op het verse volume — dat pad draait normaal en juist sneller; de dispose van het losgekoppelde oude volume raakt het niet.)
- **C3 — stoppen, dan verwijderen, dán pas het volume.** **(a)** Stop de legacy `scrum4me-forgejo-dind`-container (restart staat al op `no` sinds B3). **(b)** **Verwijder beide legacy containers**: `docker rm <runner-id> <dind-id>` — uitsluitend deze twee geïnventariseerde ID's; géén `compose down`, géén prune, géén `-v`. Stoppen alleen laat de mount-referentie staan en dan **weigert** `docker volume rm`. **(c)** **No-reference-bewijs:** `docker ps -a --filter volume=<oude-volume-id>` is leeg (dus inclusief gestopte containers) én `docker volume inspect <oude-volume-id>` bestaat nog. **(d)** `docker volume rm <oude-volume-id>`; daarna, met hetzelfde no-reference-bewijs, `docker volume rm forgejo_dind-certs-ca forgejo_dind-certs-client` (TLS-materiaal van een verwijderde DinD; niets refereert ze meer). Raak het benoemde `forgejo-runner-dind-data` (in gebruik door de nieuwe DinD) **niet** aan.
- **C4.** De-arm het maintenance-record expliciet ná groen schoonbewijs; bij de harde eindtijd vervalt het venster automatisch.

**Gate C (schoonbewijs):** beide legacy containers **afwezig** in `docker ps -a`; het oude anonieme volume én de twee cert-volumes **afwezig** in `docker volume ls`; het benoemde `forgejo-runner-dind-data` aanwezig en de nieuwe DinD draait er ongestoord op; `df -h /` toont de vrijgekomen ruimte.

---

## Fase D — oud record + credentials intrekken (§7.3-9) bij cutover; quarantainebestand wissen (§7.3-10) ná de rollbackperiode

Dit volgt de **spec-volgorde**, niet "ná stap H" (dat stond in ronde 2 en was fout: §9's stabiele-pool-definitie eist het **ingetrokken** quarantainebestand al gedurende de 7 dagen, dus intrekken moet vóór stap H, anders is de H-gate circulair). Rollback rekent nergens op de oude credentials (§11).

- **D1 (bij cutover, Fase B).** Roteer de credentials; verwijder secrets uit containermetadata en het actieve runnerpad. De legacy-`.runner` staat gequarantined (`legacy-runner.revoked.json`, B4) als **ingetrokken record**, niet als herstelpad.
- **D2 (§7.3-9) — direct ná Gate B.** **[JP]** verwijder/disable het oude Forgejo-runnerrecord (`scrum4me-srv-runner`) en trek de oude credentials **definitief** in (Forgejo admin + het registratietoken dat nog in de legacy-container-env stond — na B3(a) en C3 machteloos, maar intrekken sluit het definitief). Leg intrekking + UTC-tijd + de vastgelegde **vernietigingsdatum** van het quarantainebestand vast in `evidence/stap-g/`. Vanaf hier is het quarantainebestand "ingetrokken" in de zin van §9.
- **D3 (§7.3-10) — ná sluiting van de rollbackperiode.** Verwijder het quarantainebestand `legacy-runner.revoked.json` op de in D2 vastgelegde vernietigingsdatum (§9: uiterlijk ná de rollbackperiode); het oude token wordt nooit opnieuw gebruikt. Rollbackperiode = tot en met een groene stap H.

---

## Fase E — bewijzen (kern stap E-equivalent, zoals op `max2`) — vóór Fase C

- **E1.** Runner online/idle als `scrum4me-srv-runner-01` (declared successfully), gecorreleerd op runner-ID in de Forgejo-beheerinterface.
- **E2 (§5.1 C1).** Fail-closed host-test: SIGKILL de controller → leftover one-off runner overleeft, gezien door label-filtered `docker ps -a` (niet `compose ps -q`); auto-restart logt `startup: achtergebleven runner — fail-closed`, start geen 2e. Ruim de leftover pas op **ná** een assignment-nulbewijs op zijn runner-ID (§7.9-drainprocedure), zodat je geen inmiddels-toegewezen job afbreekt → schone restart → weer online.
- **E3 — smoke + jobzijdige Docker en isolatie (§7.5, §8 stap F).** Workflow_dispatch op een allowlist-repo, `runs-on: ubuntu-latest`; kies het venster zo (of pauzeer `max2`) dat de jobs op `scrum4me-server` landen, gecorreleerd op runner-ID + job-URL:
  - een **groene** en een **rode** job: beide `runner exit rc=0` + `scrub ok=True`; Forgejo-status groen resp. rood.
  - een job met een **Docker build/run**-stap die de drie §7.5-endpoints raakt: `tcp://127.0.0.1:2375` binnen DinD (healthcheck), `tcp://dind:2375` vanuit de runnercontainer, `tcp://dind.internal:2375` vanuit de job-/stepcontainer.
  - **isolatiebewijs, per uitvoercontext (benoem bij elk bewijs wáár het draaide):** **(1) in de job** — `docker -H tcp://dind.internal:2375 ps` (het job-endpoint uit `runner-config.policy.yml`, of de ingestelde `DOCKER_HOST`) toont alleen DinD-lokale containers en géén hostcontainers (Forgejo/Postgres/legacy); **(2) vanuit de runnercontainer** — `docker -H tcp://dind:2375 ps` idem; **(3) op de host** — `docker inspect` van de runnercontainer toont geen `/var/run/docker.sock`-mount en geen hostpad-volumes.
- **E4.** Nette SIGTERM-stop via de §7.9-drainprocedure (B2, incl. het assignment-nulbewijs): `ExecMainStatus=0`, geen leftover-container, geen operatie-marker.
- **E5.** `verify-stack.sh <SHA> <bundle-hash>` toetst **precies drie dingen**: commit-match, bundelhash-match, en geen host-listener op 2375/2376 (isolatie) — de jobzijdige Docker/endpoint/isolatiebewijzen zijn E3, niet dit. `bundle-hash.sh` pruniert `credentials/`+`state/` en sluit `trust-verdict.json` uit, dus het draait als non-root én het gepubliceerde deploy-verdict verstoort de hash niet.

**Gate E:** alle bewijzen groen; niet-testworkflows en productiecontainers bleven gezond (§8 stap F-10 analoog). **Ná Gate E** volgt Fase C (afvoeren — tenzij B0 het al vóór E vereiste) en daarna stap H.

---

## Fase F — evidence + host-overlay vastleggen

- **F1 (§6.1).** Maak `hosts/scrum4me-server/`: `runner-config.yml` **zonder secretwaarden**, preflight-uitkomsten, hostinventarisatie.
- **F2.** `evidence/stap-g/`: **preflight-ROOD (exit 40) + verwijzing naar de §7.8-waiver** (NIET groen — dat kan per waiver niet en hoeft niet), trust-verdict (geen secrets), runner-online-bewijs, C1-test, smoke groen/rood **+ het §7.5-endpoint- en isolatiebewijs uit E3**, clean-stop, verify-stack, §7.3-8-bewijs (alleen credentialbestand draagt token), legacy-disposal-record (beide containers + 3 volumes, Gate C), **B0-schijfmeting** (+ drempelbesluit), **D2-intrekkingsrecord** (UTC + vernietigingsdatum). **`secret-scan.sh` vóór commit; geen UUID/token in Git.**
- **F3.** Commit apart per fase (zoals `evidence/stap-a`), via branch + Forgejo-PR.

---

## Rollback (§11 "tijdens normalisatie van `scrum4me-server`") — altijd via de nieuwe stack, nooit via legacy

`max2` blijft de pool dekken. Er is in élke fase precies één herstelpad — het §11-pad. Er is **geen** legacy-terugval: §11 zegt "Gebruik nooit het ingetrokken oude token of de legacy `.runner`", en de legacy container zou (zonder de B3-fence) bovendien zichzelf herregistreren. Daarom bestaat er ook geen "point-of-no-return": D2 bij cutover sluit niets af wat rollback nodig heeft.
- **Fence eerst:** zet de nieuwe unit in `DRAINING`, wacht op de terminale job, leg het Forgejo-side assignment-nulbewijs vast (§7.9-drainprocedure, B2); stop + disable de unit; verwijder **alleen** de nieuwe runner- en DinD-containers; disable het nieuwe Forgejo-record; **laat** het benoemde `forgejo-runner-dind-data` staan (onderzoek; verwijderen is apart, goedgekeurd onderhoud).
- **Herstel:** de gepinde Runner-image, Compose-config, cyclecontroller en connectionconfig met het benoemde volume opnieuw uitrollen (Fase A5/B5). Is de vervangende registratie niet bruikbaar → **[JP]** een **nieuw** runnerrecord + credentialbestand (Fase A4), nooit het oude.
- **Oud anoniem volume:** uitsluitend forensische rollbackdata; wordt **niet** opnieuw actief gekoppeld zonder een **afzonderlijk herstelbesluit** van JP (§11). Ná Fase C bestaat het niet meer — dat verandert het herstelpad niet.
- **Nooit** de host-Dockerdaemon herstarten; herstart alleen de runnerstack.

---

## Na stap G: stap H — stabilisatieperiode (§9), daarna D3

Zeven aaneengesloten dagen waarin alle §9-criteria op **beide** hosts groen zijn (incl. de tweevoudige paralleltest + failover in beide richtingen, de een-host-tegelijk-reboottest, en per geplande stop een vastgelegd assignment-nulbewijs). §9 eist daarbij dat het legacy quarantainebestand **al ingetrokken** is (D2, bij cutover) — root-only, 0600, met vastgelegde vernietigingsdatum. Pas dan is de pool "stabiel" en fase 1 klaar. **Ná een groene stap H** sluit de rollbackperiode en volgt **D3** (quarantainebestand wissen, §7.3-10).

---

## Zelf-review (spec-dekking + bevindingen verwerkt)

- **Spec-dekking:** §7.3-1..10 → **Fase A (3–4)** + Fase B (1, 2, 5–8) + **D2 direct ná Gate B (9)** + **D3 ná de rollbackperiode (10)**; §8 stap G oude-volume-afvoer → Fase C (**dispose** incl. `docker rm` van beide legacy containers + cert-volumes); §7.4 labels → hergebruik `labels.txt` (ongewijzigd); §7.5 DinD-isolatie → **E3 (jobzijdig via `tcp://dind.internal:2375`, 3 uitvoercontexten) + E5 (host-listeners)**; §7.8 → Voorwaarde 0 (gewaiverd); §7.9 drain/nulbewijs → B2-drainprocedure, hergebruikt in E2/E4 + Rollback; §6.1 host-overlay → Fase F; §11 rollback → Rollback (**uitsluitend nieuwe-stack-herstel, geen legacy-terugval**); §9/stap H → sluitsectie (eist ingetrokken quarantaine → D2 vóór H), D3 erna. Gedekt.
- **Ronde-1-bevindingen verwerkt:** `cpus:`→`cpu_period`/`cpu_quota` (bundelwijziging, PR #21, main `0bd39e0`, op max2 gehervalideerd); `bundle-hash.sh` sluit `trust-verdict.json`+`state/` uit; F2 preflight-ROOD i.p.v. -GROEN + Global-Constraints gescoped; rollback-grens = D2 + §11-reconciliatie; B2 §7.9-wacht + `T_requeue`; Gate E jobzijdige Docker/endpoints/isolatie; oude legacy-DinD-container expliciet afgevoerd; Fase C = dispose; uitvoervolgorde (E vóór C) expliciet — de "D2/D3 ná H"-deferral uit déze ronde bleek in ronde 2 spec-circulair en is in ronde 3 teruggedraaid (D2 bij cutover); A3 dummy-config-mount + spec-tabel gecorrigeerd.
- **Ronde-2-bevindingen verwerkt:** BLOCKER legacy-herregistratie → B3(a) `docker update --restart=no` op beide legacy containers vóór het stoppen + B4-toelichting; C3 `docker rm` beide legacy containers vóór `docker volume rm` (no-reference-bewijs incl. gestopte); D2 **terug naar §7.3-9 (bij cutover, direct ná Gate B)**, D3 ná de rollbackperiode — mijn ronde-2-deferral "ná stap H" was spec-circulair; Rollback = **uitsluitend §11 nieuwe-stack** (legacy-terugval geschrapt: spec-verboden én gevaarlijk); schijf → B0 hermeten + drempel ≥ 40 GB (JP-besluit 8 sep 2026: hermeten+drempel; C vóór E alleen onder de drempel), C2 budget op gemeten omvang, 121→179 GB; `evidence/stap-a/caps.env` compose-blok → `DIND_CPU_QUOTA`; cert-volumes in C1/C3; E3-isolatiecheck per uitvoercontext (`tcp://dind.internal:2375` in de job).
- **Beantwoorde open vragen:** Fase C = dispose van het losgekoppelde oude volume (§7.9-volgorde bewust omgekeerd, expliciet vastgelegd). `T_requeue`=600 s op record (`evidence/stap-a/t-requeue.md`) → wachttak toegestaan; `min(630,600)=600` ⇒ "max 10 min".
- **Geen placeholders/secrets:** commando's zijn concreet; UUID/token expliciet buiten Git gehouden.

## Uitvoerhandoff

Dit plan is een **concept**. Volgorde vóór uitvoering: (1) §7.8-waiver vastgelegd (✓ 8 sep 2026, design-delta in `migratieontwerp.md` §7.8) — **geen hardware-upgrade nodig**; (2) **stap F** groen (volgende week); (3) **plan-review** (review-loop, cross-model) op dit document → JP-gate; (4) **Scrum4Me-ceremonie** (sprint/PBI/story/taken op product `cmsx8zbdh0002hk7rcgxxr00k`); (5) uitvoeren fase A→F met de gates. De gating-blokkade (Voorwaarde 0) is opgeheven; resteren stap F + de plan-review.

---

## Review record

Plan-fase van de review-loop (twee onafhankelijke cross-model reviewers, JP-armd; zij zien elkaars output niet). Persistente loop-staat.

### Ronde 1 — verzonden 8 september 2026
- **Reviewers:** `scrum4me-server:claude` (ops-routed) + `mac:codex`.
- **Onder review:** dit plan op `origin/main` (het review-request-lichaam noemt de exacte commit-SHA), tegen `migratieontwerp.md` §7.3/§7.8/§7.9/§8 stap G en de as-built bundel `forgejo-runner/`.
- **Scope-noot voor reviewers:** de §7.8-**waiver** (Voorwaarde 0) is een **vastgelegd JP-besluit** (record-and-proceed, `migratieontwerp.md` §7.8) — niet ter herbeoordeling. Wél in scope: of het plan de waiver correct verwerkt (bv. preflight niet als groen voordoet) en of fase A–F/gates/rollback de spec juist uitvoeren.
- **Uitkomst: dubbel NO-GO.** `scrum4me-server:claude` 0B/2M/3m · `mac:codex` 1B/6M/1m. Beide reviews hoge kwaliteit (claude: nul valse boom-claims; codex vond de BLOCKER).
  - **[BLOCKER — GEVERIFIEERD 8 sep]** `compose.yaml:25` `cpus: ${DIND_CPUS}=11.5` wordt door Docker **geweigerd bij container-create op 8 cores**: gemeten op scrum4me-server → `range of CPUs is from 0.01 to 8.00, as there are only 8 CPUs available`. De byte-identieke bundel kan dus NIET as-is op scrum4me-server draaien; de CPU-cap moet host-portabel (bv. `cpu_period`/`cpu_quota`, niet gevalideerd tegen NumCPU). **Gedeelde bundelwijziging** (raakt ook max2 → revalidatie + nieuwe SHA). NB: mijn waiver-rationale "CPU-cap 11,5 bindt niet op 8 cores" was mis voor de gekozen `cpus:`/NanoCpus-vorm — te corrigeren in §7.8.
  - **[MAJOR — GEVERIFIEERD]** `bundle-hash.sh` sluit `trust-verdict.json` (en `state/`-marker) niet uit → het door A6 geschreven verdict vervuilt de bundelhash → `verify-stack` (E5) faalt (exit 61). Latent ook op max2 (mijn verify-stack daar was self-consistent, geen echte repo-drift-check). Fix: verdict + marker aan de excludes (of buiten de gehashte dir).
  - **[MAJOR — GEVERIFIEERD]** legacy DinD = aparte container `scrum4me-forgejo-dind` (`docker:dind`, TLS 2376, eigen ~121 GB anoniem volume). Fase B stopt alleen de oude runner; Fase C voert de oude DinD/volume niet uitvoerbaar af. Plan moet de oude DinD expliciet stoppen + het volume disposen.
  - **[MAJOR — beide]** F2 "preflight-GROEN" ⟂ Voorwaarde 0/Gate 0 (ROOD); Global Constraints "rode preflight verbiedt mutatie" moet met de Voorwaarde-0-waiver gescoped worden.
  - **[MAJOR — beide]** rollback-grens: kop "tot en met D-2" vs body "vóór D2"; reconcileer met §11 (herstelt de NIEUWE stack, niet legacy) + D2-ordening t.o.v. E/H.
  - **[MAJOR — codex]** B2 mist de §7.9 `fetch_timeout+10s`-wacht vóór het nulbewijs; E2–E4 koppelen jobafsluiting+nulbewijs niet aan de mutatie/heropening.
  - **[MAJOR — codex]** Gate E bewijst niet de jobzijdige Docker build/run + de drie §7.5-endpoints + host-isolatie; `verify-stack` dekt enkel commit/hash/listeners.
  - **[MINOR]** C3 dupliceert het volume dat B5 al maakt; C2 schort §9-scrub-criteria op die de dispose niet raakt; spec-tabel plaatst §7.3-3/4 verkeerd (staan in Fase A); A3 dummy-config zonder mount.
  - **Open vragen beantwoord:** Fase C = **dispose** (`docker volume rm` na no-reference-bewijs; §7.9-volgorde-omkering expliciet vastleggen). `T_requeue`=600 s op record → wachttak toegestaan (`min(630,600)=600` ⇒ "max 10 min").
  - **Escalatie → JP:** de BLOCKER (CPU-cap host-portabel) + de bundle-hash-fix zijn **bundelwijzigingen die max2 raken** en revalidatie/review vergen — groter dan één plan-ronde. Volgende stap wacht op JP-richting.
- **Afhandeling (JP-akkoord "1 dan 2 dan 3", 8 september 2026):**
  1. **Bundel gefixt** — PR #21 (`c2cfaef`, merge `0bd39e0` op `main`): DinD-cap `cpus:`→`cpu_period: 100000`/`cpu_quota: ${DIND_CPU_QUOTA}=1150000` (host-portabel; geverifieerd `docker create --cpu-period/--cpu-quota` geaccepteerd op 8 cores) + `bundle-hash.sh` pruniert `state/` en sluit `trust-verdict.json` uit. Op **max2 gehervalideerd** (contract 18/18, bundle-hash 10/10, exec skipt netjes). Nieuwe bundel-SHA = `0bd39e0`.
  2. **Plan herzien** — deze revisie verwerkt alle 8 bevindingen (zie Zelf-review → "Ronde-1-bevindingen verwerkt").
  3. **Ronde 2** — hieronder.

### Ronde 2 — verzonden 8 september 2026
- **Reviewers:** `scrum4me-server:claude` (ops-routed) + `mac:codex` — zelfde paar als ronde 1.
- **Onder review:** deze herziene versie op `origin/main` (het review-request-lichaam noemt de exacte commit-SHA + een fetch-regel), tegen `migratieontwerp.md` §7.3/§7.8/§7.9/§8 stap G en de bijgewerkte bundel `forgejo-runner/` op `0bd39e0`.
- **Wat veranderde t.o.v. ronde 1:** BLOCKER opgelost in de bundel (CPU-cap host-portabel, PR #21); MAJOR bundle-hash opgelost (`trust-verdict.json`+`state/` uitgesloten); legacy-DinD-container expliciet afgevoerd (Fase C = dispose, ná Fase E); F2 preflight-ROOD + Global-Constraints/Voorwaarde-0 gescoped; rollback-grens = D2 + §11-reconciliatie; B2 §7.9-`fetch_timeout+10s`-wacht + `T_requeue`=600 s; Gate E jobzijdige Docker + 3 §7.5-endpoints + host-isolatie (E3); MINOR's (C2/C3, spec-tabel §7.3-3/4 → Fase A, A3 dummy-config-mount) verwerkt; uitvoervolgorde (A→B→E→C→F→stap H→D2/D3) expliciet.
- **Scope-noot voor reviewers (ongewijzigd):** de §7.8-**waiver** (Voorwaarde 0) is een vastgelegd JP-besluit — niet ter herbeoordeling. Wél in scope: verwerkt het plan de waiver correct (preflight niet als groen voorgesteld) en voeren fase A–F/gates/rollback de spec juist uit. **Verifieer de fixes tegen de boom — vertrouw ze niet.**
- **Uitkomst: dubbel NO-GO.** `scrum4me-server:claude` 1B/1M/2m · `mac:codex` 0B/3M/1m. **Alle acht ronde-1-fixes houden stand** — beide reviewers toetsten ze tegen de boom (CPU-cap, bundle-hash, F2-ROOD, drain-wacht, Gate-E-endpoints, MINORs: geverifieerd). De nieuwe bevindingen komen uit de **as-built host** (die alleen `scrum4me-server:claude` meet) + een **spec-conflict dat mijn eigen ronde-2-revisie introduceerde**. Convergentie: BLOCKER + M-C + M-E raken dezelfde kern (legacy-container-levenscyclus).
  - **[BLOCKER — claude, GEVERIFIEERD tegen `evidence/stap-a/scrum4me-server/containers.json`]** de legacy container `scrum4me-forgejo-runner` draait `restart=always` met een zelf-registrerend entrypoint (`if [ ! -f /data/.runner ]; then forgejo-runner register … --name scrum4me-srv-runner --labels "ubuntu-latest:…"; fi; exec … daemon`) en het registratietoken staat nog in de env. B4 (`.runner` → quarantaine) **ontwapent de oude runner niet maar bewapent zijn herregistratie**: bij de eerstvolgende containerherstart (reboot, auto-updates, `compose up`) registreert hij zich opnieuw als spookrecord met het canonieke label en claimt jobs; ná Fase C is zijn DinD weg → die jobs stranden. Fix: `docker update --restart=no scrum4me-forgejo-runner scrum4me-forgejo-dind` vóór B3 + Fase C `docker rm`'t de legacy containers (niet enkel stoppen); evt. het registratietoken uit de legacy-compose halen vóór B4.
  - **[MAJOR — codex, GEVERIFIEERD (`containers.json`)]** C3 stopt de legacy DinD maar verwijdert de **container** niet → `docker volume rm` weigert (nog gerefereerd) → Gate C/C4 onafrondbaar. Fix: expliciete `docker rm` van uitsluitend de geïnventariseerde legacy container ná stop, dan no-reference-bewijs (inspect incl. gestopte), dan `docker volume rm` van enkel dat volume.
  - **[MAJOR — codex, GEVERIFIEERD tegen `migratieontwerp.md` §7.3-9/10 (:181-183) + §9 (:408/:423)]** mijn ronde-2 "D2/D3 pas ná stap H" is **spec-circulair**: §7.3-9 trekt de credentials **bij cutover** in; §9's stabiele-pool-definitie eist dat het **ingetrokken** quarantainebestand al bestaat gedurende de 7 dagen. Alleen §7.3-10 (bestand verwijderen) wacht op sluiting van de rollbackperiode. Fix: **terug naar de spec** — D2 (intrekken + record disablen) bij/na cutover-bewijs en vóór stap H; alleen D3 (bestand wissen) ná de rollbackperiode. (Geen spec-wijziging; mijn deferral was de afwijking.)
  - **[MAJOR — codex, GEVERIFIEERD tegen §11 (:466-468)]** de legacy-terugval-rollback die ik schreef is **spec-verboden**: §11 voor scrum4me-server herstelt de **nieuwe** stack + connectionconfig en zegt "Gebruik nooit het ingetrokken oude token of de legacy `.runner`"; het oude volume koppelt alleen met een afzonderlijk herstelbesluit. Fix: rollback = nieuwe-stack-herstel (zo nodig nieuw record), legacy-terugval schrappen als standaardpad.
  - **[MAJOR — claude, host-meting]** de schijf-onderbouwing van "E vóór C" is achterhaald: het legacy anonieme volume is **179 GB** (niet ~121) en `/` heeft **61 GB vrij / 87% gebruikt** (niet de geciteerde 139 GB/29% uit stap-A). In het B→E-venster staan beide stacks + image-pulls + de E3-buildjob naast elkaar uit 61 GB, op een host die óók Forgejo+Postgres draagt; C2's harde eindtijd (op 121 GB gebudgetteerd) is ~48% te kort. Fix: schijf **hermeten vlak vóór Fase B** met drempel (bv. "≥ X GB vrij, anders C vóór E") + C2 budgetteren op de dán gemeten omvang. **[Design-keuze voor JP: hermeten+drempel vs. C eerder (dispose vóór E) om ruimte vrij te maken.]**
  - **[MINOR — claude]** `evidence/stap-a/caps.env` draagt nog `DIND_CPUS=11.5` (geen `DIND_CPU_QUOTA`) → `docker compose config` met die env faalt hard (fail-closed). Fix: caps.env-blok → `DIND_CPU_QUOTA=1150000` of schrappen + naar `.env.example` verwijzen.
  - **[MINOR — claude]** Fase C laat twee named cert-volumes (`forgejo_dind-certs-ca`, `forgejo_dind-certs-client`) van de legacy DinD staan; Gate C claimt "schoonbewijs". Fix: benoem ze in C1, beslis in C3.
  - **[MINOR — codex]** E3's isolatiecheck gebruikt `docker -H tcp://dind:2375 ps` (runner-endpoint) waar de **jobcontext** bedoeld is (`tcp://dind.internal:2375`, `runner-config.policy.yml:14/24`). Fix: job draait de check met `docker -H tcp://dind.internal:2375 ps`; host-/runner-inspecties apart met benoemde context.
  - **Escalatie → JP:** ronde 2 = NO-GO met **geverifieerde, convergente** bevindingen. De ronde-3-fixes zijn **plan/evidence-only** (géén bundelwijziging → géén max2-revalidatie, géén spec-wijziging — ze lijnen het plan terug naar de spec). Twee ervan **draaien mijn ronde-2-keuzes terug** (D2-deferral; legacy-terugval) omdat die van de spec afweken. Eén (schijf/volgorde) draagt een echte design-keuze.
  - **JP-besluit (8 sep 2026):** "fix + ronde 3"; schijf/volgorde = **hermeten + drempel** (C vóór E alleen onder de drempel, niet als standaard).

### Ronde 3 — verzonden 9 september 2026
- **Reviewers:** `scrum4me-server:claude` (ops-routed; kan de host meten) + `mac:codex` — zelfde paar.
- **Onder review:** deze herziene versie op `origin/main` (het request-lichaam noemt de exacte commit-SHA + een fetch-regel), tegen `migratieontwerp.md` §7.3/§7.9/§8/§9/§11 en de bundel `forgejo-runner/` op `0bd39e0` — **ongewijzigd sinds ronde 2; géén bundelwijziging deze ronde.**
- **Wat veranderde t.o.v. ronde 2 (plan/evidence-only):** B3(a) `docker update --restart=no` op beide legacy containers vóór het stoppen + bewijs `RestartPolicy=no`, B4-toelichting (BLOCKER); C3 `docker rm` beide legacy containers → no-reference-bewijs (`docker ps -a --filter volume=`) → `docker volume rm`; cert-volumes `forgejo_dind-certs-ca/-client` in C1/C3; Gate C = afwezigheidsbewijs (M-C + m); D2 **terug naar §7.3-9: bij cutover, direct ná Gate B**, D3 ná de rollbackperiode; stap-H-tekst + uitvoervolgorde aangepast; "point-of-no-return" geschrapt (M-D); Rollback = **uitsluitend §11 nieuwe-stack**, legacy-terugval geschrapt (M-E); **B0** schijf hermeten vlak vóór cutover + drempel **≥ 40 GB** (2× de §7.8-werkruimtegate), onder de drempel C vóór E, C2 budget op gemeten omvang, 121→179 GB, "139 GB" alleen nog als achterhaalde meting (M-schijf); `evidence/stap-a/caps.env` compose-blok `DIND_CPUS`→`DIND_CPU_QUOTA=1150000` met gedateerde header-toelichting — preflight.sh leest alleen het eerste blok (m); E3-isolatiecheck per uitvoercontext, in de job via `tcp://dind.internal:2375` (m); Zelf-review: spec-tabel, nieuwe ronde-2-bullet, en de ronde-1-bullet eerlijk gemaakt over de teruggedraaide deferral.
- **Scope-noot (ongewijzigd):** de §7.8-waiver is niet ter herbeoordeling. **Verifieer de fixes tegen de boom — en, voor de `scrum4me-server:claude`-slot, tegen de live host** (de B3(a)-fence-volgorde, de restart-policies, de schijfdrempel).
- **Uitkomst:** _(wacht op beide replies)_
