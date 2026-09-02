# Afsluitgate van stap A en stap B

**Datum:** 2 september 2026
**Branch:** `feat/forgejo-runner-pool-stap-a-b`, stand vóór het afsluiten: `bad244c`
**Plan:** `docs/forgejo-runner-pool/implementatieplan-stap-a-b.md` (22 taken)
**Bundelhash op deze stand:** `c4a47ae3cdc68c241fb491fa3babfcf6e024f4935c062de3f12837ba7a73fbe0` (`bash forgejo-runner/scripts/bundle-hash.sh forgejo-runner`)

## Uitkomst van de gate

| Gate | Uitkomst |
|---|---|
| `bats forgejo-runner/tests/*.bats` | 117 tests, 0 failures |
| unittests (`test_*.py`, per bestand) | 161 tests, 0 failures |
| `shellcheck -x forgejo-runner/scripts/*.sh` | schoon |
| mechanische tellercontrole van het plan | `tellers kloppen`, exit 0 |
| secret-scan over bundel + bewijs | exit 0; pre-commit hook actief in beide werkbomen |
| bewijsbestanden uit de tabel hieronder | 25 van 25 aanwezig |

**Stap A en B zijn uitgevoerd en alle bewijsrijen zijn gedekt.** De laatste rij
(gezondheid van de productiecontainers) is op 2 september via read-only
hostmetingen gesloten; die opname leverde één bevinding voor JP op (zie de rij
en `productiecontainers-voor.txt`).

## Eis uit §8 stap A en B → bewijs

| Eis | Bewijs |
|---|---|
| image-ID's, manifestdigests, Compose, netwerken, volumes, health van de live runnerstack | `scrum4me-server/images.json`, `containers.json` (geredigeerd, zie ISS-8), `networks.json`, `volumes.json` |
| anonieme volume-ID en omvang inner-DinD-data | `scrum4me-server/dind-usage.txt` (118 GB) |
| legacy `.runner`-metadata zonder tokenwaarde, met mode | `scrum4me-server/runner-registration.json`, `runner-registration-stat.txt` |
| volledige labels en global scope | `runner-registration.json`, `forgejo/runners-summary.tsv` |
| alle zichtbare runnerrecords | `forgejo/runners-summary.tsv` |
| `T_requeue` | `t-requeue.md` (600 s; wachttak in §7.9 dus toegestaan) |
| canonieke labelnamen uit de live `.runner` | `shared-label-names.txt` |
| machineleesbare caps voor `preflight.sh` | `caps.env` |
| NTP-status en klokskew op beide hosts | `clock-scrum4me-server.txt`, `max2-clock.txt` |
| trustscope-gate met `.forgejo`/`.github`-fallback en allowlist | `trust/trust-inventory.json`, `trust/trust-verdict.json`, `trust/voorstel-allowlist.yml`, `forgejo-runner/trusted-actions-scope.yml`; 12 repo's op het fork/PR-pad → ISS-9 (stap-C-blocker) |
| vier readinessuitkomsten met stub/testharnas | `testharnas-dekking.md` |
| fence, latch, deadline, maintenance | idem (99 controllertests) |
| piekmeting en caps | `workload-scrum4me-server.tsv` (84 samples), `caps.md` |
| jobduurbaseline | `jobduur-baseline.md` |
| hostfeiten en headroom op beide hosts | `host-facts-*.tsv`, `caps.md`, `preflight-scrum4me-server.txt` (ROOD, exit 40), `preflight-max2.txt` (GROEN, exit 0); besluit JP in R13: doorgaan, gate geldt pas bij stap G |
| productiecontainers gezond vóór aanvang | `productiecontainers-voor.txt` — beide hosts 0 unhealthy, alle gecheckte containers healthy. **Bevinding**: op max2 ligt de video-editor-stack al 10 dagen plat (2× exit 137); de gemeten headroom van max2 is dus zónder die stack — issue op het max2-product, oordeel JP |
| registry-gevalideerde digests | `resolved-digests.tsv`; beide images.json-pins bestaan nog op de registry; `runner:12` is verschoven naar v12.13.2, gepind blijft v12.10.1 |
| Compose statisch gevalideerd | `tests/test_compose_contract.bats` (15), `docker compose config` OK |
| bundel gescand op secrets | `secret-scan-blokkeringsbewijs.txt`; scan over bundel + bewijs exit 0 |
| exact één connection, absoluut `token_url`, `one-job --wait` | `tests/test_render_config.bats` (13), `exitcodecontract.md`, `one-job-help.txt` |
| exitcodecontract vastgelegd | `exitcodecontract.md` (zeven metingen tegen de gepinde 12.10.1-image) |
| ephemeral gemeten en voorgelegd | `ephemeral-spike.md` (geparkeerd, besluit JP) |
| systemd-unit syntactisch geldig, niet geïnstalleerd | `systemd-verify.md` (systemd 255, exit 0) |
| bundelhash en driftdetectie | `tests/test_bundle_hash.bats` (8), `tests/test_verify_stack.bats` (9) |

## Afwijkingen van de plancode

Het plan bevat volledige codeblokken; die zijn illustratief, het migratieontwerp
is normatief. Waar de plancode van de spec afweek is de spec gevolgd en staat de
grond in de commit. Samengevat: nulbewijs alleen bij herstel na een fence;
lopende job niet afbreken en scrubroute omzeilt de fence niet; drain overleeft
bronherstel (controller, §7.7/§7.9); index-digest in plaats van platformdigest
(§4); hostlokale bestanden buiten de bundelhash (§6.1); scrub in POSIX sh en
met buildcache-bewijs (§7.5/§7.9); secret-scan hoofdletterongevoelig en zonder
padvals-positief (§6.1, ISS-8). Details per taak in
`testharnas-dekking.md` en de commitberichten.

## Open besluiten voor JP vóór stap C

- **ISS-8**: `RUNNER_REGISTRATION_TOKEN` staat in de container-env van de
  legacy runner → rotatie.
- **ISS-9**: twaalf repo's op het fork/PR-pad met het gedeelde label → stap-C-blocker.
- **Ephemeral** (Task 4): geparkeerd; raakt §7.3/§7.4 en vraagt een delta-review
  vóór stap C als het alsnog wordt gekozen.
- **Controller-entrypoint**: de unit start
  `forgejo_runner_cycle.py --config controller.toml`; de module heeft nog geen
  CLI/main-loop met echte probes en Docker-aansturing (niet in Task 11–15
  gespecificeerd). Vóór stap D expliciet plannen.
- **Headroomgate scrum4me-server ROOD**: geldt pas bij stap G (besluit R13).
