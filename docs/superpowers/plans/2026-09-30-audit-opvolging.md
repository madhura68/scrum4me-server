# Plan — opvolging repo-audit 2026-09-30

Status: **concept, wacht op akkoord van JP.** Er wordt niets gematerialiseerd of uitgevoerd vóór akkoord.
Bron: `docs/repo-audit/` (PR #83), met name `findings.json` (33 bevindingen) en
`pbi-candidates.md` (18 kandidaten).

## Doel

In JP's woorden: de audit omzetten in werk. Uitgewerkt: de runnerpool en de hosttools zo maken dat
(a) een compromis van een runnerhost niet de hele forge raakt, (b) de controller niet stil kan
vastlopen, en (c) wat de repo belooft (geen secrets in Git, tests bewijzen gedrag, documentatie klopt)
ook waar is. Dit gebeurt **vóór stap G**: die zet de bundel op de productiehost, en daar wegen deze
bevindingen het zwaarst.

## Eerst bruikbare resultaat

Increment 1: het trust-scan-token op max2 kan niets meer schrijven. De secret-scan laat de
gereproduceerde bypasses niet meer door. Eén commando draait alle tests en meldt welke tests zijn
overgeslagen. `CLAUDE.md`, `AGENTS.md` en `README.md` beschrijven de repo zoals hij is.

**Zichtbaar bewijs:**
- Een schrijfaanroep met het nieuwe token op max2 geeft 403, terwijl het verdict groen blijft.
- De reproducties uit `verification.md` (rename, bash 3.2, UUID-regel) geven exit 70.
- Het verify-commando faalt op een opzettelijk kapotte test.

## Niet-doelen

- Geen wijziging aan het geaccepteerde risico van privileged DinD (AUDIT-001); rootless DinD blijft fase 2.
- Het one-job window (AUDIT-003) wordt niet dichtgebouwd, alleen vastgelegd (besluit JP 30 sep).
- Geen CI die deployt. Een read-only CI-job is een aparte beslissing (zie open punten).
- Geen imageupgrade van runner/DinD in deze opvolging. Alleen de backportvraag en een cadans (PBI-16).
- Stap G zelf valt buiten dit plan. Dit plan levert de bundelcommit waarop stap G uitrolt.

## Increments

Volgorde op risicoreductie per moeite. Increment 3 is onafhankelijk en kan parallel lopen.

### Increment 1 — Snelle risicoreductie, geen ontwerpwijziging

| PBI | Wat | Waar | Bewijs |
|---|---|---|---|
| PBI-09 | Eigen token voor de trust-scan met alleen `read:repository`, `read:admin` (en `read:organization` als die voor teams nodig blijkt). Eerst uitzoeken wat `FREX_RUNNER` nog meer gebruikt; daarna roteren. README noemt de scopes; inline-tokenvoorbeelden vervangen. | host max2 (credentialbestand), Forgejo-UI (**JP maakt het token aan**), `forgejo-runner/README.md`, `implementatieplan-forgejo-15.0.7.md` | `systemctl start forgejo-runner-trust.service` geeft exit 0 en een nieuwe `measured_at`; schrijf-probe 403; `access_token`-scope gemeten zoals in de audit |
| PBI-01 | `secret-scan.sh`: staged blobs incl. renames, fail-closed zonder bash 4, geen hele-regel-uitzondering, bredere sleutel- en bestandsnamen, gelijk met `compose-git-pre-commit` | `forgejo-runner/scripts/secret-scan.sh`, `tests/test_secret_scan.bats` | nieuwe bats-cases; de reproducties uit de audit geven 70 |
| PBI-13 | Documented `--check` werkt echt en controleert paden en bereiken | `cycle_runtime.py` (main-guard of doc-correctie), `controller.toml.example`, bring-up-runbook | ontbrekend configbestand geeft exit 2 via het gedocumenteerde commando |
| PBI-10 | Eén verify-entrypoint (alle suites + shellcheck op alle scripts), exitcodes geaggregeerd, skips bij naam | nieuw `scripts/verify.sh` (of vergelijkbaar), vermeld in `CLAUDE.md`/`AGENTS.md` | opzettelijk falende test in een niet-laatste file geeft exit ≠ 0; skiplijst op mac vs. op een host |
| PBI-14 | Topleveldocs en hygiëne: tabel "Rol van deze repo", versies met datum, unitcomment en README-stap 10, `.pyc` untracken, root-`.gitignore` | `CLAUDE.md`, `AGENTS.md`, `README.md`, `forgejo-runner-cycle.service`, `forgejo-runner/README.md`, `.gitignore` | grep na de fix; `git status` schoon na een testrun |

De unitcomment in `forgejo-runner-cycle.service` valt onder de bundelhash. Die wijziging gaat mee in
de bundelcommit van increment 2, zodat max2 maar één keer opnieuw uitrolt.

### Increment 2 — Controller: geen stille stilstand, ontwerp en code weer gelijk

Vereist **één delta-review met GO** op `migratieontwerp.md` en `controller-entrypoint-ontwerp.md`,
volgens de hardstopregel voor post-GO-wijzigingen. De delta bevat:

- **AUDIT-003:** het geaccepteerde one-job window (PBI-03).
- **AUDIT-006:** quarantaine na runnerfout blijft staan, of heropent met backoff. Hierover moet JP beslissen (PBI-04).
- **AUDIT-007:** fence-herstel zonder assignment-nulbewijs in de thin slice (PBI-04).
- **AUDIT-005:** retry met backoff voor pre-pullfouten; de latch alleen voor mensenwerk. Het ontwerp zegt nu "blijft QUARANTINED" (PBI-02).

Daarna in de code:

| PBI | Wat | Bewijs |
|---|---|---|
| PBI-17 (eerst) | Harness uitbreiden: scriptbare probe en trustresultaat; scenariotests A–E uit `verification.md`; één begrensde run van `Runtime.run` | tests falen op huidige code waar de bevinding dat zegt |
| PBI-02 | Deadline per operatie (scrub/pull), latch met reden en retry, top-level exceptiongrens, logregel per gatewissel (DinD-health, blocked) | scenariotests D en E slagen; journal toont een reden voor elke toestand zonder runner |
| PBI-05 | Scrub-bewijs eist een levend daemon-antwoord | bats-case met falende docker-stub geeft ≠ 0 |
| PBI-04, PBI-03 | Code conform de delta | scenariotests A en C; test die het geaccepteerde window vastlegt |

**Praktijkproef:** nieuwe bundelcommit handmatig uitrollen op max2 (enige host met de bundel),
`verify-stack.sh` groen, één groene en één rode testjob, en één bewust getriggerde pre-pullfout
(onbereikbare digest in een wegwerpkopie van `allowed-job-images.txt`) die zichtbaar herstelt. Een
rollout vereist een apart akkoord van JP, zoals altijd.

### Increment 3 — Mirror en retention (onafhankelijk)

| PBI | Wat | Bewijs |
|---|---|---|
| PBI-11 (eerst) | bats met fake `curl`/`git`/`docker`/`jq`/`flock` | handmatige mutatie van elke bewaakte regel laat een test falen |
| PBI-07 | Tokens uit URL's en argv (header uit 0600-bestand of `GIT_ASKPASS`, data via stdin); rotatiekaart aanvullen | fake-`git`/`curl` legt argv vast zonder token |
| PBI-12 | State-write niet fataal, alleen 404 = "geen workflows", retention weigert bij mislukte enumeratie. Tag-paginering en naamsanering als goedkope guards, want ze zijn latent | tests uit PBI-11 |

**Praktijkproef:** installeren op scrum4me-server volgens de mirror-README en `DRY_RUN=1` voor één repo.
Daarna één echte nachtrun; controleer met `ps` tijdens de run dat er geen token in argv staat.

### Increment 4 — Onderzoek en verharding, deels in stap G

| PBI / bevinding | Wat | Koppeling |
|---|---|---|
| PBI-06 | Meten wie de DinD-bridge kan bereiken, TLS-besluit en de scrubgarantie vastleggen | delta-review; meetbaar op max2 nu, op srv na stap G |
| PBI-08 | Trust-scan: `X-Total-Count` controleren, label-loze risky trigger hard, deploy keys | delta §7.7 |
| PBI-15 | Drift-gate: fail-closed zonder `ss`, unit- en configvergelijking; mirror-unit en retention-planning in de repo | past bij stap G-fase F (host-overlay) |
| AUDIT-033 | Bundel root-owned uitrollen (`install -o root`), eigenaar controleren in `verify-stack.sh` | opnemen in stap G-taak T03/T06 en in een her-uitrol op max2 |
| PBI-16 | Backportvraag Runner 13.0.0-fix beantwoorden; cadans voor digestvergelijking | los onderzoek |
| PBI-18 | Restgaten in `rotate-env-credential` | los, lage prioriteit |

## Materialisatie (na akkoord)

Voorstel voor de hiërarchie in Scrum4Me op product `scrum4me-server`:
- **Sprint 1:** increment 1 + 2, met als doel "Runnerpool klaar voor stap G: geen schrijvend token op de runnerhost, geen stille stilstand, ontwerp = code".
- **Sprint 2:** increment 3.
- **Increment 4:** als PBI's zonder sprint (backlog), zodat JP prioriteert. AUDIT-033 wordt als notitie toegevoegd aan stap G-taak T03.

Eén PBI per auditkandidaat, één story per PBI, taken per laag. Na materialisatie geldt de hardstop:
uitvoering vereist een aparte opdracht.

## Open punten voor JP

1. **FREX_RUNNER:** weet je waarvoor dit token nog meer gebruikt wordt? Anders zoek ik dat eerst uit
   (read-only: grep over hosts en repo's naar de tokennaam en `token_last_eight`-matches in env-bestanden).
2. **Quarantaine na runnerfout (AUDIT-006):** sticky tot handmatige vrijgave, of heropenen met
   backoff? Dit bepaalt de delta van increment 2.
3. **Read-only CI** die het verify-commando draait bij elke push: gewenst? De hardstop verbiedt deployen
   via Actions, niet controleren. CI zou wel draaien op dezelfde runnerpool die het test.
4. **Reviewvorm:** moet dit plan zelf door een review-loop, of alleen de delta van increment 2
   (verplicht)?
