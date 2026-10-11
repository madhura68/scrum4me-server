# forgejo-runner — gedeelde bundel

Deze map is de **canonieke bron** van de Forgejo-Runner-poolbundel. Beide hosts
(`scrum4me-server` en `max2`) rollen uit vanaf dezelfde commit-SHA van deze repo.
De `max2`-repo bevat geen kopie; zie §6.1 van het migratieontwerp
(`docs/forgejo-runner-pool/migratieontwerp.md`).

## Wat erin zit

| Bestand | Rol |
|---|---|
| `compose.yaml` | DinD (privileged, `restart: always`) en runner (profiel `cycle`, `restart: "no"`) |
| `.env.example` | imagepins als `repo@sha256:…` en de caps uit `evidence/stap-a/caps.env`; nooit tokens of UUID's |
| `labels.txt` | canonieke, digest-gepinde labellijst (§7.4) |
| `allowed-job-images.txt` | digests die de scrub mag behouden, met grootte in bytes |
| `runner-config.policy.yml` | gedeelde runnerpolicy; `render-config.sh` voegt de hostspecifieke UUID en `token_url` toe |
| `trusted-actions-scope.yml` | trust-allowlist voor global scope (§7.7) |
| `forgejo-runner-cycle.service` | systemd-unit die de Python-cyclecontroller draait |
| `forgejo-runner-dind-guard.service` | oneshot die `scripts/dind-guard.sh apply` draait (iptables-REJECT op de DinD-API) |
| `forgejo-runner-trust.service` + `.timer` | vernieuwen het trust-verdict vóór het verloopt (§7.7 "dagelijks") |
| `scripts/` | preflight, render-config, resolve-digests, scrub-dind, bundle-hash, verify-stack, secret-scan, de cyclecontroller en de read-only inventarisatiescripts |
| `tests/` | bats- en unittest-suite; draait niet mee op de hosts en telt niet mee in de bundelhash |

## Uitrollen

1. `bash scripts/preflight.sh --facts … --caps … --images allowed-job-images.txt`
   moet exit 0 geven. Faalt hij, dan wordt er niets uitgerold. De gate wordt niet
   versoepeld om verder te kunnen (§7.8).
2. Kopieer de bundel naar `/opt/forgejo-runner/` op de host, als `root:root`
   met de modi uit de repo (bestanden `0644`, scripts `0755`), en nooit als een
   onbevoorrechte gebruiker: root-units voeren deze bestanden uit en
   `verify-stack.sh` weigert (exit 64) een bundelmap, een map met bundelbestanden
   (zoals `scripts/`) of een bundelbestand dat niet van uid 0 is of
   groep/wereld-schrijfbaar is (AUDIT-033). Bijvoorbeeld vanuit
   deze map: `sudo rsync -rlpt --chown=root:root --exclude tests/ --exclude
   credentials/ --exclude state/ ./ /opt/forgejo-runner/` (`-p` behoudt de
   repo-modi; `credentials/` en `state/` blijven hostlokaal). Een enkel
   bestand: `sudo install -o root -g root -m 0644 <bestand> <doel>` (`-m 0755`
   voor een script).
3. Schrijf de commit-SHA naar `/opt/forgejo-runner/BUNDLE_COMMIT`.
4. Render de hostconfig: `bash scripts/render-config.sh --uuid <host-uuid>
   --labels labels.txt --policy runner-config.policy.yml --out runner-config.yml`.
5. Zet het token als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`,
   eigendom van de effectieve runner-UID:GID, **zonder afsluitende newline** (de
   runner weigert een token met een newline). Het token komt nooit uit deze repo.
6. `cp .env.example .env` en `docker compose up -d`: dat start uitsluitend DinD; de
   runner staat onder het profiel `cycle` en wordt alleen door de cyclecontroller
   gestart. **Op een eerste uitrol: installeer en activeer eerst de guard**
   (stap 7, tot en met `systemctl enable --now forgejo-runner-dind-guard.service`)
   en draai pas daarna `docker compose up -d`: de DinD-API is zonder guard vanaf
   de host bereikbaar (ISS-49).

   Per stack zijn vier variabelen verplicht, zonder standaardwaarde:
   `STACK_BRIDGE`, `STACK_VOLUME`, `STACK_CONFIG` en `STACK_TOKEN` (R17, §5). Stack
   `02` draagt ze in `.env` (de waarden staan al in `.env.example`); een tweede
   stack krijgt een eigen env-bestand onder `/opt/forgejo-runner-stacks/<id>/` en
   een eigen projectnaam. Ontbreekt een variabele, dan faalt **iedere**
   compose-aanroep, ook `stop`, `down` en `exec`: geef bij een stack met een eigen
   env-bestand dus bij ieder subcommando `--env-file <pad>` en `-p <projectnaam>`
   mee.
7. Installeer de units en laad systemd opnieuw, exact zo (byte-gelijk aan de
   bundelkopie; `verify-stack.sh` vergelijkt ze en faalt met exit 63 bij een
   ontbrekende of afwijkende unit):
   ```sh
   for u in forgejo-runner-cycle.service forgejo-runner-dind-guard.service forgejo-runner-trust.service forgejo-runner-trust.timer; do
     sudo install -o root -g root -m 0644 /opt/forgejo-runner/$u /etc/systemd/system/
   done
   sudo systemctl daemon-reload
   ```
   Daarna `systemctl enable --now forgejo-runner-dind-guard.service` (de
   firewallguard die hostverkeer naar de DinD-API op iedere stackbridge `fr-dind+` weigert,
   T-188) en dan `systemctl enable --now forgejo-runner-cycle.service`; die
   laatste vereist de guard-unit.

   Bestaande stack met de oude, automatisch benoemde bridge: de vaste naam
   `fr-dind0` vraagt een nieuw netwerk. Stop `forgejo-runner-cycle.service`
   pas als aantoonbaar geen job loopt (zie "Een lopende job niet onderbreken"
   hieronder), draai `docker compose down` (het volume
   `forgejo-runner-dind-data` blijft bestaan) en `docker compose up -d`, en start
   daarna de cycle-unit. `verify-stack.sh` faalt met exit 65 als de guardregel
   ontbreekt of de DinD-API vanaf de host bereikbaar is.

7b. Alleen voor een host met een extra stack (R17 §5): installeer ook de
   template-unit, **zonder** `enable` of `start`. Stap 7 installeert en activeert
   uitsluitend de vier vaste units; een instantie als `forgejo-runner-cycle@03`
   wordt pas ingeschakeld nadat de per-stack-map, de DinD van die stack en het
   isolatiebewijs er zijn (zie het implementatieplan, fase 3).
   ```sh
   sudo install -o root -g root -m 0644 /opt/forgejo-runner/forgejo-runner-cycle@.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
   De template leest per instantie `/opt/forgejo-runner-stacks/<id>/controller.toml`
   en heeft geen `ExecStartPre=`: een instantie zonder die map faalt in het
   hoofdproces (exit 2) in plaats van in een herstartlus. `verify-stack.sh` vergelijkt
   de template byte-gelijk met de bundelkopie zodra er een instantie is ingeschakeld
   (exit 63).
8. `bash scripts/verify-stack.sh <commit> <bundelhash>` moet exit 0 geven; de
   bundelhash komt van `bash scripts/bundle-hash.sh .` op dezelfde commit. Op een host
   met meer dan één stack komt daar `--stacks "02 03"` achter, en vóór de eerste start
   van een nieuwe stack `--stacks "02 03" --pre-start` (zie "Meerdere stacks op een
   host"). Met `--stacks` draait het script als root: het leest de tokenbestanden
   (runner-UID, mode 0600) om ze onderling te vergelijken, zonder iets te printen; als
   niet-root geeft het een exit 66 over een onleesbaar tokenbestand.
9. Leg de credential voor de trustscan neer als
   `/opt/forgejo-runner/credentials/trust-scan.env`, mode `0600`, eigendom `root`,
   met exact één regel `FORGEJO_TOKEN=<waarde>`. De waarde is een Forgejo
   API-token van een account met admin-recht op iedere Actions-enabled
   repository: de scan leest `/repos/search`, `contents`, `collaborators`,
   `teams` en `branch_protections`, en die laatste vereist admin op de repo.
   Geef het token **alleen leesrechten**: `read:repository` en `read:admin`
   (gemeten 2026-09-30: voldoende voor een volledige scan van alle
   repositories; `teams` geeft op repo's van een gebruiker 405 en heeft dan
   geen scope nodig). Een token met schrijfrechten maakt van een compromis van
   de runnerhost een compromis van de forge (audit AUDIT-013).
   Het is een **ander** token dan `credentials/forgejo-token` (dat is de
   runnerregistratie) en komt nooit uit deze repo. Zet het neer zonder dat de
   waarde in je shellhistory of in argv komt, bijvoorbeeld:
   ```sh
   ssh -t max2 'read -rs -p "Token: " T; echo; printf "FORGEJO_TOKEN=%s\n" "$T" | sudo sh -c "umask 077; cat > /opt/forgejo-runner/credentials/trust-scan.env"; unset T'
   ```
   Controleer de invulling read-only vóór je de timer aanzet, door de scan-CLI
   los naar een wegwerpmap te draaien — niet de wrapper, want die invalideert
   bij falen het actieve verdict. Het token komt uit het bestand, niet uit de
   commandoregel:
   ```sh
   sudo sh -c 'cd /opt/forgejo-runner && set -a && . credentials/trust-scan.env && set +a && FORGEJO_URL=https://git.jp-visser.nl python3 -B scripts/trust_scope_cli.py --allowlist trusted-actions-scope.yml --labels labels.txt --out "$(mktemp -d)"'   # exit 0 = groen
   ```
10. `systemctl enable --now forgejo-runner-trust.timer`. Zonder deze timer
    verloopt het verdict na `trust.verdict_max_age_seconds` (24 uur) en stopt de
    controller met het starten van runners. De journal van
    `forgejo-runner-cycle.service` meldt dat één keer, bij de wissel naar rood
    (`trustgate ROOD: <reden>`), daarna niet opnieuw. Controleer met `systemctl list-timers forgejo-runner-trust.timer`
    dat er een `NEXT` staat, en met `systemctl start forgejo-runner-trust.service`
    dat een handmatige slag exit 0 geeft en `measured_at` in
    `trust-verdict.json` opschuift.

### Hostlokale units (niet in de bundel)

De units van de Forgejo-mirror (`scripts/forgejo-mirror/`) en van
docker-rollback-retention (`scripts/docker-rollback-retention/`) horen niet bij
de bundel: ze staan buiten `forgejo-runner/`, tellen niet mee in de bundelhash en
worden niet door `verify-stack.sh` gecontroleerd. Ze worden per host beheerd met
hun eigen installatiestappen.

## Meerdere stacks op een host (R17)

Een host kan meer dan één stack draaien (`max2`: stack `02` en `03`); `scrum4me-server`
houdt er één. Iedere stack is een eigen runnerrecord met eigen DinD, bridge, volume,
token en cyclecontroller. Ze delen alleen deze bundel (read-only), `allowed-job-images.txt`,
`labels.txt`, `trusted-actions-scope.yml` en het hostverdict. De bundel, het compose-sjabloon,
de labels en de caps zijn identiek voor iedere stack; een stack met andere caps of labels
is niet toegestaan. **Een compose-bestand wordt nooit gekopieerd om een stack te maken.**

| | stack `02` (bestaand) | stack `<id>` (nieuw) |
|---|---|---|
| runnernaam | `max2-forgejo-runner-02` | `max2-forgejo-runner-<id>` |
| compose-projectnaam | `forgejo-runner` | `forgejo-runner-<id>` |
| DinD-volume | `forgejo-runner-dind-data` | `forgejo-runner-<id>-dind-data` |
| bridge (max. 15 tekens) | `fr-dind0` | `fr-dind1` (`03`), `fr-dind2` (`04`) |
| tokenbestand | `/opt/forgejo-runner/credentials/forgejo-token` | `/opt/forgejo-runner-stacks/<id>/credentials/forgejo-token` |
| per-stack-map | `/opt/forgejo-runner/` (de bundelmap) | `/opt/forgejo-runner-stacks/<id>/` |
| controllerunit | `forgejo-runner-cycle.service` | `forgejo-runner-cycle@<id>.service` |

De per-stack-map staat bewust **buiten** de bundelmap en dus buiten de bundelhash. Ze bevat
`.env` (de vier verplichte `STACK_*`-waarden plus de gedeelde pins en caps; schrijf haar
uit de tabel hierboven, kopieer haar nooit uit `.env.example`, dat de waarden van stack
`02` draagt), `controller.toml` (met `project`, een eigen `marker_path` onder `state/` en
`env_file = "<per-stack-map>/.env"`), `runner-config.yml`, `state/` en `credentials/`.
Eigendom: de map, `.env`, `controller.toml`, `runner-config.yml` en `state/` zijn root en niet
groep- of wereldschrijfbaar (ze voeden root-`docker compose`); `credentials/` is root 0700 en
alleen `credentials/forgejo-token` is van de runner-UID, mode 0600 (het token wordt als enkel
bestand gemount). `verify-stack.sh --stacks` toetst dit (exit 64) en de uniciteit van
projectnaam, bridge, volume, tokenpad, tokeninhoud en `marker_path` plus gelijke pins en caps
over de stacks (exit 66).

Compose-aanroepen voor een stack geven altijd de projectnaam en het env-bestand mee, en
worden eerst met `ps` gecontroleerd; een vorm zonder `-p` raakt stack `02`:

```sh
docker compose -p forgejo-runner-03 -f /opt/forgejo-runner/compose.yaml \
  --env-file /opt/forgejo-runner-stacks/03/.env ps
```

**Uitrolvolgorde van een extra stack** (volledig uitgeschreven in het implementatieplan,
fase 3): per-stack-map en config klaarzetten; `verify-stack.sh --stacks "02 03" --pre-start`;
alleen de DinD van de nieuwe stack starten met de controller gestopt
(`up -d dind` met het per-stack-env); het runtime-deel van `verify-stack.sh --stacks "02 03"`,
de guardproef op de nieuwe bridge en de cross-stackproef; pas daarna
`systemctl enable --now forgejo-runner-cycle@<id>.service`. Zodra de controller `WAITING`
bereikt neemt hij gewone jobs aan: al het isolatiebewijs hoort dus vóór die stap.

**Terugdraaien van één stack**, zonder drain: (1) het runnerrecord van die stack in Forgejo
pauzeren; (2) de drie controles van "Een lopende job niet onderbreken", uitgeschreven voor
deze stack (`journalctl -u forgejo-runner-cycle@<id>` en `docker compose -p
forgejo-runner-<id> … --env-file <per-stack-env> exec -T dind …`; een vorm zonder `-p` of
`-u` raakt stack `02` en kan een vals "idle" geven); (3) `systemctl stop` en `disable` van
`forgejo-runner-cycle@<id>.service`; (4) `… ps` tonen en bevestigen, dan `… down` zonder
`-v` (het volume blijft); (5) het runnerrecord op disabled; (6) token en per-stack-map
blijven tot de rollbackperiode sluit. Stack `02`, de andere runners en de bundel blijven
ongemoeid.

## Terugdraaien

Stop en disable eerst `forgejo-runner-trust.timer`, anders publiceert die tijdens
het terugdraaien een vers verdict en laat hij de gate onbedoeld groen. Wacht
daarna tot er aantoonbaar geen job loopt (zie "Een lopende job niet
onderbreken") en leg het Forgejo-side nulbewijs voor assigned/running jobs vast.
Stop en disable daarna de unit en verwijder alleen de runner- en DinD-containers. Laat het volume
`forgejo-runner-dind-data` staan voor onderzoek. Herstart nooit de host-Dockerdaemon.

### Een lopende job niet onderbreken

`systemctl stop forgejo-runner-cycle.service` is **geen drain**. De controller
zet bij SIGTERM wel `DRAINING`, maar stuurt de runner direct SIGTERM door, en
die breekt een lopende job af. Gemeten op `max2` op 1 oktober 2026: task 10249
(`janpeter/Scrum4Me`, "DB Access Production Sentinel") liep 77 s toen de unit
stopte. De journal meldde `cyclus: runner exit rc=130` en Forgejo zette de job
op `failure`. De `child_stop_grace_seconds` (200 s) wordt dus niet benut voor een
nette afronding. Een niet-onderbrekende drain bestaat nog niet; ook het
maintenance-record is niet armbaar.

Tot die er is, stop je de unit alleen als alle drie de controles waar zijn:

1. de laatste journalregels van de unit zijn `single task poller received no
   task …` en er is na de laatste `runner gestart` geen `task <id> repo is …`
   gelogd: `journalctl -u forgejo-runner-cycle -n 20 --no-pager`;
2. binnen DinD draait geen job- of servicecontainer:
   `docker compose exec -T dind docker -H tcp://127.0.0.1:2375 ps -q` is leeg;
3. het Forgejo-side nulbewijs (§7.9) toont voor deze runner geen assigned of
   running job.

Stop dan direct. Er blijft een venster van één poll-interval (`fetch_interval`,
2 s) waarin de runner alsnog een job kan oppakken. Controleer na de stop in de
journal dat de laatste exit niet `rc=130` is na een `task … repo is …`-regel.
Gebeurde dat toch, herstart die job dan in Forgejo.

## Wat hier bewust niet gebeurt

- Geen deployment via Forgejo Actions: jobcontainers draaien in DinD zonder
  host-Docker-socket en zonder hostpadvolumes en kunnen deze stack niet wijzigen.
- Geen wijziging aan `/etc/docker/daemon.json`, geen herstart van de Docker-daemon,
  geen hostbrede `docker system prune`.
- Geen gedeeld DinD-volume of gedeelde DinD tussen de hosts.

## Verifiëren

Een geldige CLI-exit 0 of soft-only exit 10 publiceert groen. Zachte meldingen
blijven via stderr in het servicejournal zichtbaar en moeten binnen 24 uur worden
beoordeeld. Hard/onleesbaar, onverwachte exits en ongeldige of tegenstrijdige JSON
invalideren oud groen. De scanner onderzoekt de defaultbranch, niet de geselecteerde
featurecommit. Merge en hostuitrol vereisen afzonderlijk akkoord.

Het vaste ingangspunt voor de hele repo is `scripts/verify.sh` (vanaf de repo-root):
het draait alle bats-, Python- en shellcheck-suites, meldt overgeslagen tests met
naam en reden, en geeft exit ≠ 0 zodra één onderdeel faalt. Integratietests zijn
opt-in (`VERIFY_INTEGRATION=1` voor `test_compose_runner_exec.bats`).

```bash
bash scripts/verify.sh            # alles; --only bats|py|shellcheck beperkt dit
```

Los, vanuit deze map, hetzelfde als handwerk:

```bash
bats tests/*.bats
for f in tests/test_*.py; do python3 "$f"; done
shellcheck -x scripts/*.sh
```
