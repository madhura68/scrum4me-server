# Implementatieplan — Stap G: `scrum4me-server` normaliseren

> **Voor uitvoerders:** dit is een **operator-gedreven migratie** op een productiehost, geen code-implementatie. Er is **geen nieuwe bundelcode**: `scrum4me-server` rolt exact dezelfde byte-identieke bundel uit die `max2` al draait (gepinde commit-SHA). Voer stap voor stap uit met de verificatiegate ná elke fase; bij een rode gate: **stop en meld JP** (niet forceren, niet de gate versoepelen). Elke fase is afzonderlijk terug te draaien (zie Rollback).

**Doel:** de bestaande legacy Forgejo-runner op `scrum4me-server` (oud `.runner`-registratiemodel, permanente `daemon`, ongecapt, ~121 GB DinD-cache) vervangen door dezelfde architectuur als `max2`: Runner 12.10.1 `server.connections`-config + de systemd-cyclecontroller (`one-job --wait` per job, volledige scrub tussen jobs), met de gedeelde caps.

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

> **Uitvoervolgorde (belangrijk — niet de alfabetische fase-volgorde):** A (voorbereiden) → B (cutover) → **E (bewijzen)** → **C (oude legacy-DinD + volume afvoeren)** → F (evidence, loopt mee) → **stap H (7 dagen stabiliseren)** → **D2/D3 (oud record + credentials definitief intrekken — point-of-no-return)**. Bewijzen (E) gaat vóór afvoeren (C); definitief intrekken (D2/D3) pas ná stap H. Zie Rollback voor de grens.

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

1. **B1 (§7.3-1).** Inventariseer het bestaande legacy record; wacht tot de legacy runner **idle** is.
2. **B2 (§7.3-2, §7.9) — de drainprocedure (hergebruikt in E2/E4).** Blokkeer nieuwe jobtoewijzing aan de oude runner (Forgejo → pause). Dan: `DRAINING` → graceful stop → **wacht minimaal de effectieve `fetch_timeout` + 10 s** (§7.9, sluit het FetchTask-ambiguïteitsvenster) → bewijs runnerrecord offline → **Forgejo-side assignment-nulbewijs** gebonden aan de runner-ID (twee snapshots 10 s uiteen, nul assigned/running). Vind je een toegewezen job zonder lokaal proces → `QUARANTINED`, wacht `min(T_requeue+30 s, 10 min)` = **10 min** (`T_requeue`=600 s, `evidence/stap-a/t-requeue.md`; brondefault + bevestiging, géén live-meting — de wachttak is dus toegestaan; herbevestig de effectieve Forgejo-versie/config vóór het venster), anders cancel + redispatch. **[JP: Forgejo-UI pauze; ik: drain/nulbewijs-meting.]**
3. **B3 (§7.3-5).** Stop **alleen** de oude runner*container* (niet de host-daemon, niet de andere productiecontainers). NB: de legacy **DinD** is een aparte container (`scrum4me-forgejo-dind`, `docker:dind`, TLS op 2376, met het anonieme ~121 GB volume) — die blijft in deze fase **draaien** en wordt pas in Fase C gestopt en afgevoerd (ná de bewijzen van Fase E).
4. **B4 (§7.3-6).** Verplaats de legacy `.runner` uit het gemounte runnerpad naar een root-only quarantaine `legacy-runner.revoked.json`, mode 0600, zodat alleen `server.connections` actief is. **Niet verwijderen** (rollback-venster).
5. **B5 (§7.3-7).** Installeer + start de cyclecontroller-unit (`forgejo-runner-cycle.service`, zoals `max2`): `docker compose -p forgejo-runner up -d --wait dind` → `systemctl daemon-reload` → `enable --now`. Volg de journal: `SOURCE_WAIT` → `READY` → `scrub ok=True` → `runner gestart` → `runner: scrum4me-srv-runner-01 … declared successfully`.
6. **B6 (§7.3-8).** Bewijs dat **alleen** het credentialbestand het actieve token draagt: `stat` op `credentials/forgejo-token`; `docker inspect` van de runnercontainer (geen token in env/command, geen socket-mount); een geschoonde configweergave. Geen secrets in `Config.Cmd`/env.

**Gate B:** `scrum4me-srv-runner-01` online/idle in Forgejo; geen token buiten het credentialbestand; `max2` bleef de pool dekken.

---

## Fase C — oude legacy-DinD + anoniem volume afvoeren (apart maintenance-record, §8 stap G) — ná Fase E

Voer dit **ná** de bewijzen van Fase E uit: pas als de nieuwe stack bewezen werkt, voer je het oude weg (dat sluit de legacy-terugval-rollback af, zie Rollback). De nieuwe stack pint het volume op naam (`forgejo-runner-dind-data`, al door B5 gemaakt) en koppelt het oude anonieme legacy-volume **nooit** aan; `scrub-dind.sh` kan die data dus niet bereiken. De handeling is een **dispose**, geen scrub — een **bewuste afwijking van §7.9's volgorde** (die de bestaande DinD éérst scrubt en dán een schoon volume maakt; hier bestaat het schone benoemde volume al en draait het). Schijf is ruim (stap-A: 139 GB vrij).

- **C1.** Leg de container-ID van de legacy `scrum4me-forgejo-dind`, de oude anonieme volume-ID en de **opnieuw gemeten dataomvang** (~121 GB verwacht) vast.
- **C2.** Arm een **afzonderlijk** maintenance-record (eigen `maintenance_id`, UTC-start, harde UTC-eindtijd — bepaald uit de dataomvang + een **proefmeting van een `docker volume rm` op dezelfde storageklasse**). Dit venster begrenst de dispose; de harde eindtijd + het schoonbewijs (C4) sluiten het. (Er worden **geen** §9-`SCRUBBING`-criteria opgeschort: die gelden voor een scrub-cyclus van de draaiende controller op het verse volume — dat pad draait normaal en juist sneller; de dispose van het losgekoppelde oude volume raakt het niet.)
- **C3.** Stop de legacy `scrum4me-forgejo-dind`-container; verwijder daarna het vrijgegeven oude anonieme volume (`docker volume rm <id>` ná bewijs dat geen container het nog refereert). Raak het benoemde `forgejo-runner-dind-data` (in gebruik door de nieuwe DinD) **niet** aan.
- **C4.** De-arm het maintenance-record expliciet ná groen schoonbewijs (oude container weg, oud volume weg); bij de harde eindtijd vervalt het venster automatisch.

**Gate C:** legacy `scrum4me-forgejo-dind` gestopt + oud anoniem volume verwijderd (schoonbewijs); de nieuwe DinD draait ongestoord op het benoemde volume.

---

## Fase D — oud record + credentials definitief intrekken (§7.3-9/10) — point-of-no-return, NÁ stap H

- **D1 (bij cutover, Fase B).** Roteer de credentials; verwijder secrets uit containermetadata en het actieve runnerpad. De legacy-`.runner` blijft gequarantined (`legacy-runner.revoked.json`, B4) — **herstelbaar** t.b.v. rollback.
- **D2 (§7.3-9) — pas ná groen Fase-E-bewijs én de stabilisatieperiode stap H.** **[JP]** verwijder/disable het oude Forgejo-runnerrecord en trek de oude credentials **definitief** in (Forgejo admin + credential). **Dit is het point-of-no-return** (zie Rollback): niet in de lineaire A→F-stroom, maar ná stap H.
- **D3 (§7.3-10, ná D2).** Verwijder het quarantainebestand `legacy-runner.revoked.json`; het oude token wordt nooit opnieuw gebruikt.

---

## Fase E — bewijzen (kern stap E-equivalent, zoals op `max2`) — vóór Fase C

- **E1.** Runner online/idle als `scrum4me-srv-runner-01` (declared successfully), gecorreleerd op runner-ID in de Forgejo-beheerinterface.
- **E2 (§5.1 C1).** Fail-closed host-test: SIGKILL de controller → leftover one-off runner overleeft, gezien door label-filtered `docker ps -a` (niet `compose ps -q`); auto-restart logt `startup: achtergebleven runner — fail-closed`, start geen 2e. Ruim de leftover pas op **ná** een assignment-nulbewijs op zijn runner-ID (§7.9-drainprocedure), zodat je geen inmiddels-toegewezen job afbreekt → schone restart → weer online.
- **E3 — smoke + jobzijdige Docker en isolatie (§7.5, §8 stap F).** Workflow_dispatch op een allowlist-repo, `runs-on: ubuntu-latest`; kies het venster zo (of pauzeer `max2`) dat de jobs op `scrum4me-server` landen, gecorreleerd op runner-ID + job-URL:
  - een **groene** en een **rode** job: beide `runner exit rc=0` + `scrub ok=True`; Forgejo-status groen resp. rood.
  - een job met een **Docker build/run**-stap die de drie §7.5-endpoints raakt: `tcp://127.0.0.1:2375` binnen DinD (healthcheck), `tcp://dind:2375` vanuit de runnercontainer, `tcp://dind.internal:2375` vanuit de job-/stepcontainer.
  - **isolatiebewijs:** de jobcontainer ziet de hostcontainers niet — `docker -H tcp://dind:2375 ps` toont alleen DinD-lokale containers, en `docker inspect` van de runnercontainer toont geen `/var/run/docker.sock`-mount.
- **E4.** Nette SIGTERM-stop via de §7.9-drainprocedure (B2, incl. het assignment-nulbewijs): `ExecMainStatus=0`, geen leftover-container, geen operatie-marker.
- **E5.** `verify-stack.sh <SHA> <bundle-hash>` toetst **precies drie dingen**: commit-match, bundelhash-match, en geen host-listener op 2375/2376 (isolatie) — de jobzijdige Docker/endpoint/isolatiebewijzen zijn E3, niet dit. `bundle-hash.sh` pruniert `credentials/`+`state/` en sluit `trust-verdict.json` uit, dus het draait als non-root én het gepubliceerde deploy-verdict verstoort de hash niet.

**Gate E:** alle bewijzen groen; niet-testworkflows en productiecontainers bleven gezond (§8 stap F-10 analoog). **Pas ná Gate E** volgt Fase C (afvoeren) en daarna stap H.

---

## Fase F — evidence + host-overlay vastleggen

- **F1 (§6.1).** Maak `hosts/scrum4me-server/`: `runner-config.yml` **zonder secretwaarden**, preflight-uitkomsten, hostinventarisatie.
- **F2.** `evidence/stap-g/`: **preflight-ROOD (exit 40) + verwijzing naar de §7.8-waiver** (NIET groen — dat kan per waiver niet en hoeft niet), trust-verdict (geen secrets), runner-online-bewijs, C1-test, smoke groen/rood **+ het §7.5-endpoint- en isolatiebewijs uit E3**, clean-stop, verify-stack, §7.3-8-bewijs (alleen credentialbestand draagt token), oude-legacy-DinD/volume-disposal-record. **`secret-scan.sh` vóór commit; geen UUID/token in Git.**
- **F3.** Commit apart per fase (zoals `evidence/stap-a`), via branch + Forgejo-PR.

---

## Rollback (§11, README §Terugdraaien) — mogelijk tot D2 (point-of-no-return)

`max2` blijft de pool dekken. De grens ligt **vóór D2** (definitief intrekken); welk herstelpad beschikbaar is hangt af van hoe ver je bent:
- **§11-pad (nieuwe stack) — beschikbaar zolang D2 niet is uitgevoerd:** zet de nieuwe unit in `DRAINING`, wacht op de terminale job, leg het Forgejo-side nulbewijs vast; stop + disable de nieuwe unit; verwijder **alleen** de nieuwe runner- en DinD-containers; disable het nieuwe Forgejo-record; **laat** het benoemde volume staan. Herstel loopt daarna via de gepinde connectionconfig + cyclecontroller, zo nodig met een nieuwe registratie (`migratieontwerp.md` §11; "de oorspronkelijke runner blijft jobs uitvoeren" geldt via een herstelde óf nieuwe registratie).
- **legacy-terugval — alleen zolang Fase C het oude volume nog NIET heeft afgevoerd:** herstel de legacy `.runner` uit `legacy-runner.revoked.json` en herstart de oude runnercontainer. Omdat Fase C ná Fase E draait, bestaat dit pad tot je C uitvoert; ná C rest alleen het §11-pad.
- **Ná D2/D3:** rollback is voorbij (record + credentials definitief ingetrokken); een nieuwe host-installatie loopt via een nieuw record (Fase A). Daarom D2/D3 **pas ná** groen Fase-E-bewijs én de stabilisatieperiode (stap H).
- **Nooit** de host-Dockerdaemon herstarten.

---

## Na stap G: stap H — stabilisatieperiode (§9), daarna D2/D3

Zeven aaneengesloten dagen waarin alle §9-criteria op **beide** hosts groen zijn (incl. de tweevoudige paralleltest + failover in beide richtingen, de een-host-tegelijk-reboottest, en per geplande stop een vastgelegd assignment-nulbewijs). Pas dan is de pool "stabiel" en fase 1 klaar. **Ná een groene stap H** voer je D2/D3 uit (oud record + credentials definitief intrekken, quarantaine verwijderen) — bewust als laatste, point-of-no-return.

---

## Zelf-review (spec-dekking + bevindingen verwerkt)

- **Spec-dekking:** §7.3-1..10 → **Fase A (3–4)** + Fase B (1, 2, 5–8) + Fase D (9–10); §8 stap G oude-volume-afvoer → Fase C (**dispose**, geen scrub); §7.4 labels → hergebruik `labels.txt` (ongewijzigd); §7.5 DinD-isolatie → **E3 (jobzijdig, 3 endpoints) + E5 (host-listeners)**; §7.8 → Voorwaarde 0 (gewaiverd); §7.9 drain/nulbewijs → B2-drainprocedure, hergebruikt in E2/E4; §6.1 host-overlay → Fase F; §11 rollback → Rollback (grens = D2); §9/stap H → sluitsectie, D2/D3 erna. Gedekt.
- **Ronde-1-bevindingen verwerkt:** `cpus:`→`cpu_period`/`cpu_quota` (bundelwijziging, PR #21, main `0bd39e0`, op max2 gehervalideerd); `bundle-hash.sh` sluit `trust-verdict.json`+`state/` uit; F2 preflight-ROOD i.p.v. -GROEN + Global-Constraints gescoped; rollback-grens = D2 + §11-reconciliatie; B2 §7.9-wacht + `T_requeue`; Gate E jobzijdige Docker/endpoints/isolatie; oude legacy-DinD-container expliciet afgevoerd; Fase C = dispose; uitvoervolgorde (E vóór C, D2/D3 ná H) expliciet; A3 dummy-config-mount + spec-tabel gecorrigeerd.
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
  - **Escalatie → JP:** ronde 2 = NO-GO met **geverifieerde, convergente** bevindingen. De ronde-3-fixes zijn **plan/evidence-only** (géén bundelwijziging → géén max2-revalidatie, géén spec-wijziging — ze lijnen het plan terug naar de spec). Twee ervan **draaien mijn ronde-2-keuzes terug** (D2-deferral; legacy-terugval) omdat die van de spec afweken. Eén (schijf/volgorde) draagt een echte design-keuze. Wacht op JP-akkoord voor ronde 3 + die keuze.
