# Implementatieplan — Stap G: `scrum4me-server` normaliseren

> **Voor uitvoerders:** dit is een **operator-gedreven migratie** op een productiehost, geen code-implementatie. Er is **geen nieuwe bundelcode**: `scrum4me-server` rolt exact dezelfde byte-identieke bundel uit die `max2` al draait (gepinde commit-SHA). Voer stap voor stap uit met de verificatiegate ná elke fase; bij een rode gate: **stop en meld JP** (niet forceren, niet de gate versoepelen). Elke fase is afzonderlijk terug te draaien (zie Rollback).

**Doel:** de bestaande legacy Forgejo-runner op `scrum4me-server` (oud `.runner`-registratiemodel, permanente `daemon`, ongecapt, ~121 GB DinD-cache) vervangen door dezelfde architectuur als `max2`: Runner 12.10.1 `server.connections`-config + de systemd-cyclecontroller (`one-job --wait` per job, volledige scrub tussen jobs), met de gedeelde caps.

**Architectuur:** ports & adapters cyclecontroller (byte-identiek hart), gedeelde bundel uit de `scrum4me-server`-repo op één gepinde SHA, trustgate als deploy-verdict, exclusieve DinD per host. Zie `migratieontwerp.md` §3, §6, §7.3, §7.5.

**Spec:** `docs/forgejo-runner-pool/migratieontwerp.md` — §8 stap G (normativ), §7.2 (volgorde), §7.3 (legacy→nieuw, 10 stappen), §7.4 (labels), §7.5 (DinD-isolatie), §7.7 (trust), §7.8 (headroomgate), §7.9 (drain + assignment-nulbewijs), §9 (stabiliteit), §11 (rollback). Bring-up-precedent: `evidence/stap-d/bring-up-runbook.md` (stap D/E op max2).

---

## Global Constraints (bindend, uit de spec + `CLAUDE.md`)

- **Caps zijn gelijk op beide hosts** (`evidence/stap-a/caps.env`: runner 1,0 vCPU/1 GiB, DinD 11,5 vCPU/5 GiB). Niet verlagen voor alleen `scrum4me-server`. Zelfde label = zelfde minimale uitvoeromgeving.
- **`preflight.sh` is een pre-mutatie-gate (§7.8): faalt hij, dan géén mutatie.** Niet versoepelen om verder te kunnen.
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

## Fase A — voorbereiden náást de draaiende legacy runner (§7.2, geen impact)

De legacy runner blijft in deze fase gewoon jobs uitvoeren.

- **A1.** Deploy de bundel op de gepinde SHA naar `/opt/forgejo-runner/` op `scrum4me-server` (`git archive <SHA>:forgejo-runner | tar -x` → `sudo cp -a` → schrijf `BUNDLE_COMMIT`). Zelfde SHA als `max2`. Verificatie: `BUNDLE_COMMIT` klopt, `scripts/` aanwezig.
- **A2.** `cp .env.example .env`; `docker pull` de gepinde `RUNNER_IMAGE`/`DIND_IMAGE`/`JOB_IMAGE`.
- **A3.** §4-argv-sanity: `docker inspect` (Entrypoint=null, Cmd=[/bin/forgejo-runner]) + `docker run --rm <RUNNER_IMAGE> /bin/forgejo-runner -c /etc/forgejo-runner/config.yml one-job --wait` met een dummy-config → geen "0 connections"/`$PATH`-fout (de ISS-15-fix, `-c` verplicht in het compose-`command`).
- **A4.** `credentials/`-map aanmaken (0700). **[JP]** registreer het vervangend runnerrecord `scrum4me-srv-runner-01` in Forgejo op de bestaande **global** scope met het canonieke label `ubuntu-latest` → nieuwe **UUID** + **token** (§5, §7.3-3). Geef mij de UUID; plaats het token zelf als `/opt/forgejo-runner/credentials/forgejo-token`, mode 0600, eigendom runner-UID (§7.3-4). **Credential- en admin-stappen zijn JP-only.**
- **A5.** `bash scripts/render-config.sh --uuid <nieuwe-UUID> --labels labels.txt --policy runner-config.policy.yml --out runner-config.yml`. `cp controller.toml.example controller.toml`; `python3 scripts/cycle_runtime.py --config controller.toml --check` → exit 0.
- **A6.** Trust-verdict publiceren. **[JP]** in eigen shell met persoonlijk `FORGEJO_TOKEN`: `scripts/publish-trust-verdict.sh --cli-py scripts/trust_scope_cli.py --labels /opt/forgejo-runner/labels.txt --allowlist /opt/forgejo-runner/trusted-actions-scope.yml --target https://git.jp-visser.nl --out /opt/forgejo-runner/trust-verdict.json`. Verifieer `"ok":true`, verse `measured_at`, binding-hashes = de gedeployde bestanden.

**Gate A:** alle bovenstaande verificaties groen; de legacy runner draait nog ongestoord.

---

## Fase B — cutover in een onderhoudsvenster (§7.3-1..8; `max2` dekt de pool)

Kies een moment waarop `max2` de pool kan dragen. Geen Forgejo/Postgres-reboot nodig — dit raakt alleen de runner op deze host — maar plan het als onderhoud.

1. **B1 (§7.3-1).** Inventariseer het bestaande legacy record; wacht tot de legacy runner **idle** is.
2. **B2 (§7.3-2, §7.9).** Blokkeer nieuwe jobtoewijzing aan de oude runner (Forgejo → pause). Drain volgens §7.9: `DRAINING` → graceful stop → bewijs runnerrecord offline → **Forgejo-side assignment-nulbewijs** (twee snapshots 10 s uiteen, nul assigned/running). Vind je een toegewezen job zonder lokaal proces → `QUARANTINED`, wacht `min(T_requeue+30 s, 10 min)`, anders cancel + redispatch. **[JP: Forgejo-UI pauze; ik: drain/nulbewijs-meting.]**
3. **B3 (§7.3-5).** Stop **alleen** de oude runnercontainer (niet de host-daemon, niet de andere productiecontainers).
4. **B4 (§7.3-6).** Verplaats de legacy `.runner` uit het gemounte runnerpad naar een root-only quarantaine `legacy-runner.revoked.json`, mode 0600, zodat alleen `server.connections` actief is. **Niet verwijderen** (rollback-venster).
5. **B5 (§7.3-7).** Installeer + start de cyclecontroller-unit (`forgejo-runner-cycle.service`, zoals `max2`): `docker compose -p forgejo-runner up -d --wait dind` → `systemctl daemon-reload` → `enable --now`. Volg de journal: `SOURCE_WAIT` → `READY` → `scrub ok=True` → `runner gestart` → `runner: scrum4me-srv-runner-01 … declared successfully`.
6. **B6 (§7.3-8).** Bewijs dat **alleen** het credentialbestand het actieve token draagt: `stat` op `credentials/forgejo-token`; `docker inspect` van de runnercontainer (geen token in env/command, geen socket-mount); een geschoonde configweergave. Geen secrets in `Config.Cmd`/env.

**Gate B:** `scrum4me-srv-runner-01` online/idle in Forgejo; geen token buiten het credentialbestand; `max2` bleef de pool dekken.

---

## Fase C — oud anoniem DinD-volume opruimen (apart maintenance-record, §8 stap G)

- **C1.** Leg de oude anonieme DinD-volume-ID en de **opnieuw gemeten dataomvang** vast (~121 GB verwacht).
- **C2.** Arm een **afzonderlijk** maintenance-record met eigen `maintenance_id`, UTC-start en harde UTC-eindtijd — bepaald uit de actuele dataomvang + een **proefmeting op dezelfde storageklasse**. Tijdens dit record zijn **alleen** de §9-criteria voor maximale `SCRUBBING`-duur en tijd-tot-`WAITING` tijdelijk opgeschort voor `scrum4me-server`; trustgate, credential/protocol-classificatie, assignment-nulbewijs, geen-nieuwe-runner-tijdens-scrub en **alle** `max2`-criteria blijven gelden.
- **C3.** Maak een schoon **benoemd** `forgejo-runner-dind-data`-volume; **kopieer de oude state niet**; pre-pull alleen de toegestane digest-images (`allowed-job-images.txt`).
- **C4.** De-arm het scrubrecord expliciet ná groen schoonbewijs; bij de harde eindtijd vervalt de uitzondering automatisch en gelden normale alarmen + stabiliteitsreset weer.

> **OPEN VRAAG voor de plan-review:** de spec noemt "de eenmalige scrub" met een dataomvang-afgeleide deadline, maar zegt óók "maak een schoon benoemd volume, kopieer de oude state niet". Te verduidelijken: dekt de deadline het **veilig disposen van het oude ~121 GB anonieme volume** (bv. `docker volume rm` + verificatie), of een eerste scrub-cyclus die de oude data nog aantreft? Meet dit tegen de werkelijke host-toestand vóór uitvoering; verzin geen aanname.

**Gate C:** vers benoemd volume actief; oud volume gedocumenteerd + veilig afgevoerd; schoonbewijs groen.

---

## Fase D — credentials + oud record definitief intrekken (§7.3-9)

- **D1.** Roteer de credentials; verwijder secrets uit containermetadata en het actieve runnerpad.
- **D2 (§7.3-9).** **[JP]** verwijder/disable het oude Forgejo-runnerrecord en trek de oude credentials **definitief** in (Forgejo admin + credential).
- **D3 (§7.3-10, ná de rollbackperiode).** Verwijder het quarantainebestand `legacy-runner.revoked.json`; het oude token wordt nooit opnieuw gebruikt.

---

## Fase E — bewijzen (kern stap E-equivalent, zoals op `max2`)

- **E1.** Runner online/idle als `scrum4me-srv-runner-01` (declared successfully).
- **E2 (§5.1 C1).** Fail-closed host-test: SIGKILL de controller → leftover one-off runner overleeft, gezien door label-filtered `docker ps -a` (niet `compose ps -q`); auto-restart logt `startup: achtergebleven runner — fail-closed`, start geen 2e; opruimen → schone restart → weer online.
- **E3.** Smoke groen + rood (workflow_dispatch, `runs-on: ubuntu-latest`, op een allowlist-repo; `max2` gepauzeerd of het venster zo gekozen dat de jobs op `scrum4me-server` landen): beide `runner exit rc=0` + `scrub ok=True`; Forgejo-status groen resp. rood.
- **E4.** Nette SIGTERM-stop: `ExecMainStatus=0`, geen leftover-container, geen operatie-marker.
- **E5.** `verify-stack.sh <SHA> <bundle-hash>`: commit-match, hash-match, isolatie OK (geen host-listener op 2375/2376). (`bundle-hash.sh` pruniert `credentials/` → werkt als non-root.)

**Gate E:** alle bewijzen groen; niet-testworkflows en productiecontainers bleven gezond (§8 stap F-10 analoog).

---

## Fase F — evidence + host-overlay vastleggen

- **F1 (§6.1).** Maak `hosts/scrum4me-server/`: `runner-config.yml` **zonder secretwaarden**, preflight-uitkomsten, hostinventarisatie.
- **F2.** `evidence/stap-g/`: preflight-GROEN, trust-verdict (geen secrets), runner-online-bewijs, C1-test, smoke groen/rood, clean-stop, verify-stack, §7.3-8-bewijs (alleen credentialbestand draagt token), oude-volume-disposal-record. **`secret-scan.sh` vóór commit; geen UUID/token in Git.**
- **F3.** Commit apart per fase (zoals `evidence/stap-a`), via branch + Forgejo-PR.

---

## Rollback (§11, README §Terugdraaien) — mogelijk tot en met Fase D-2

`max2` blijft de pool dekken. Per fase:
- **Vóór D2/D3** (oude record + `.runner` nog quarantined-maar-herstelbaar): zet de nieuwe unit in `DRAINING`, wacht op terminale job, leg het Forgejo-side nulbewijs vast; stop + disable de nieuwe unit; verwijder **alleen** de nieuwe runner- en DinD-containers; disable het nieuwe Forgejo-record; **laat** het benoemde volume `forgejo-runner-dind-data` staan. **Herstel** de legacy `.runner` uit `legacy-runner.revoked.json` en herstart de oude runnercontainer → de oorspronkelijke runner voert weer jobs uit.
- **Na D2/D3** (oud record + credentials definitief ingetrokken): rollback naar legacy is niet meer bedoeld; herstel loopt dan via een nieuw record zoals Fase A. Voer D2/D3 daarom pas uit ná een groene stabilisatieperiode.
- **Nooit** de host-Dockerdaemon herstarten.

---

## Na stap G: stap H — stabilisatieperiode (§9)

Zeven aaneengesloten dagen waarin alle §9-criteria op **beide** hosts groen zijn (incl. de tweevoudige paralleltest + failover in beide richtingen, de een-host-tegelijk-reboottest, en per geplande stop een vastgelegd assignment-nulbewijs). Pas dan is de pool "stabiel" en fase 1 klaar.

---

## Zelf-review (spec-dekking + open punten)

- **Spec-dekking:** §7.3-1..10 → Fase B (1–8) + Fase D (9–10); §8 stap G volume/scrub → Fase C; §7.4 labels → hergebruik `labels.txt` (ongewijzigd); §7.5 DinD-isolatie → Gate E5; §7.8 → Voorwaarde 0; §7.9 drain/nulbewijs → B2 + rollback; §6.1 host-overlay → Fase F; §11 rollback → Rollback; §9/stap H → sluitsectie. Gedekt.
- **Open punten voor de plan-review (review-loop):**
  1. Fase C — exacte semantiek "eenmalige scrub" vs. dispose van het oude anonieme volume (meet tegen de host).
  2. ~~Sequencing t.o.v. een stackmigratie~~ — vervallen: Voorwaarde 0 is opgeheven via de §7.8-waiver (JP, 8 sep 2026); geen hardware/stackmigratie meer, stap G draait op de huidige box.
  3. Bevestig `T_requeue` (stap A) vóór de drain-wachttak in B2 (§7.9).
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
