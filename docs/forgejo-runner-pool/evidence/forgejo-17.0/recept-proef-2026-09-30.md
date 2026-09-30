# Receptproef Forgejo 15.0.9 → 17.0 in een wegwerpomgeving (30 september 2026)

Bewijs bij [implementatieplan-forgejo-17.0.md](../../implementatieplan-forgejo-17.0.md). Fase R, het venster
(2.4–4.5), de terugweg R4 en de hostregel-commit uit 6.2 zijn **letterlijk uit het plan** uitgevoerd: de
shellblokken zijn uit het planbestand geëxtraheerd (`b17/bNN.sh`, het N-de blok) en met `source` gedraaid;
commando's uit de lopende tekst staan in het script hieronder. Er is geen host en geen productiedata geraakt.

## 1. Omgeving en afwijkingen van productie

- **"Host":** een `docker:dind`-container op de mac (Docker 29.8.1, bash 5.3.9, GNU sed 4.9, Docker Compose
  5.5.1), gebruiker `janpeter` in de docker-groep met `sudo` zonder wachtwoord.
- **Zelfde namen en paden als productie:** `scrum4me-postgres` (`postgres:17`, superuser `scrum4me`, database
  `forgejo` van rol `forgejo`), `scrum4me-forgejo`, `scrum4me-forgejo-runner`, `scrum4me-forgejo-dind`,
  compose-project `forgejo` in `/srv/scrum4me/forgejo` (onder git, `GIT_CF=ja`), volume
  `forgejo_forgejo-data` op `/var/lib/docker/volumes/forgejo_forgejo-data/_data`.
- **Beginstand van de eindproef:** de instance ná de vensterproef van het 15.0.9-plan — 15.0.9, trusted
  proxies expliciet, secrets geroteerd, compose-tag `15.0.9` gecommit, en de database
  `forgejo_failed_15_0_9` uit de R4-proef nog aanwezig. Dat is de stand waar dit plan op de host van uitgaat
  (zie [vensterproef 15.0.9](../forgejo-15.0.9/vensterproef-2026-09-30.md) voor de opzet en het compose-bestand).
- **Doelimage:** `codeberg.org/forgejo-experimental/forgejo:17.0-test` (meldt zich als
  `17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0`); 17.0 is nog niet uitgebracht. Voor het venster is dat image
  lokaal hertagd als `codeberg.org/forgejo/forgejo:17.0.0`, zodat 4.2/4.3 met `V17=17.0.0` letterlijk lopen.
- **Afwijkingen:** één repository, één generic package, twee runnerrecords zonder echte runner; legacy
  runner en DinD zijn stubs (`busybox sleep`); geen Caddy, geen `max2`, geen echte pool (2.1–2.3, 4.6,
  Fase 5 zijn niet beproefd); geen push-mirrors (de isolatie is wel gemeten, zie §4); architectuur arm64;
  de trust-allowlist is die van productie en past niet bij één proefrepo, dus de trustgate bewijst hier
  alleen dat de CLI tegen 17 zijn meting afrondt (exit 10), niet dat het productieverdict gelijk blijft;
  de migratieduur (5–6 s, 2 s in het venster) zegt niets over de echte data.

## 2. Wat de proef opleverde

Gemeten:

- **Runner v12.10.1** (de gepinde image, draait in de container als uid 1000) meldt zich met
  `server.connections` aan bij Forgejo 17.0-test, haalt via `one-job --wait` één taak op en de run eindigt
  `success` (R.5).
- De migratie 15.0.9 → 17.0-test slaagt op een kopie en op de "live" instance; het startlog bevat geen
  `[E]`, `[F]`, panic of *creating new key*; de geroteerde JWT-secrets laden dus.
- `doctor check --all`: 28 checks op 15.0.9, 27 op 17.0-test (de check "Check if hook files are
  up-to-date and executable" bestaat op 17 niet meer); beide runs sluiten af met `All done (checks: N).`
  en `doctortoets` geeft `DOCTOR OK`.
- `/api/v1/admin/actions/runners` geeft op 17.0-test een vorm die `capture-forgejo-records.sh` accepteert
  en twee records; `/runners/jobs` geeft `null` of een lijst (`CONTRACT OK`).
- De proefinstance heeft geen verbinding naar buiten (op naam: exit 6; op IP: exit 7) en niet naar de
  productieforge (exit 7), en geen gepubliceerde poorten; de host heeft op het geïsoleerde proefnetwerk geen
  adres (§5.2).
- R4 zet de instance terug op 15.0.9 met de data intact, `$CF` byte-gelijk aan `PRE_CF`, de werkboom van
  de compose-map schoon, `DOCTOR OK` ten opzichte van het log van vóór het venster, en de gemigreerde
  database bewaard als `forgejo_failed_17_0`.

Fouten die de proef in een eerdere versie van het recept vond en die vóór de review zijn hersteld:

1. **R.5:** de map `$RH/runner` was `0700 root`; de runner (uid 1000) kon de gemounte
   `config.yml` niet openen (`permission denied`, `runner-exit=1`, run bleef `waiting`). Het plan zet de
   map nu op `0755` en de twee bestanden op `0644`; `$RH` zelf blijft `0700`.
2. **Doctor-vergelijking:** `diff` na `grep -v '^\[I\]'` gaf 385 verschilregels tussen twee gezonde logs,
   en doctor geeft exit 0 bij een check met `ERROR`. Vervangen door de `doctor…`-functies, die in de
   delta-review van het 15.0.9-plan zijn aangescherpt; hun proef (24 gevallen, ook met de logs van deze
   proef) staat in [vensterproef 15.0.9](../forgejo-15.0.9/vensterproef-2026-09-30.md) §4.
3. **R4-databasenaam:** een tweede R4 faalt op de hernoeming als `forgejo_failed_17_0` al bestaat; 0.5
   toetst nu dat de naam vrij is (zelfde bewijs, §5).
4. **Anoniem volume (plan-review ronde 1, beide reviewers):** de wegwerp-Postgres liet na `docker rm -f` een
   anoniem volume met de herstelde database achter, en R.7 keek alleen naar containers en netwerken. In deze
   wegwerpomgeving viel dat niet op omdat de hele "host" wordt weggegooid; §5 laat het zien en toont dat
   een benoemd volume met `docker rm -f -v` en `docker volume rm` niets achterlaat.
5. **"Cron uit" klopte niet (ronde 1):** `FORGEJO__cron__ENABLED=false` zet de afzonderlijke crontaken niet
   uit; de regel is geschrapt en het plan zegt nu wat wél geldt (`[mirror]` en `[mailer]` uit, netwerk intern).
6. **Proeftoken kon stil leeg zijn (ronde 2, host-reviewer):** de account-opzoeking met het productietoken
   werkt niet (het token mist `read:user`), en de pipe naar `tee` schreef bij een lege gebruikersnaam een leeg
   tokenbestand. De opzoeking is geschrapt (`TRUSTUSER` komt uit de token-inventaris en wordt op site-admin
   getoetst) en het tokenblok in R.3 is fail-closed (§5).
7. **Migratietoets las een fout als "geen migratie" (ronde 2, codex):** een HTTP 404 gaf met het eerste
   filter `[]`. `migratiecheck` valideert nu status en vorm van het antwoord (§5).
8. **Host bereikbaar vanaf een intern netwerk (ronde 2, suggestie host-reviewer):** gemeten dat een
   container op een `--internal`-netwerk hostdiensten op het gateway-adres bereikt; met
   `gateway_mode_ipv4=isolated` niet meer, terwijl de proefcontainers elkaar op naam blijven vinden (§5).
9. Klein: de runnerconfig van de proef zet nu `cache.enabled: false` (zoals de productiepolicy); zonder dat
   logt de runner op een netwerk zonder uitgaand verkeer een foutregel over de cacheserver. En R.3 laat
   `IMG` vooraf zetten toe, zodat de optionele vroege proef met `17.0-test` hetzelfde blok gebruikt.

## 3. Eerste run van R.5 (de fout) en de herkansing met de fix

```text
===== R.5 setup + runner
PROEF-SETUP OK voor janpeter
Error: invalid configuration: cannot open config file "/etc/forgejo-runner/config.yml": "open /etc/forgejo-runner/config.yml: permission denied"
runner-exit=1

===== R.5 runstatus
runs: ['waiting']
exit=1

--- herkansing na: sudo chmod 0755 "$RH/runner" && sudo chmod 0644 "$RH/runner/token" "$RH/runner/config.yml"
root:root 700 /srv/backups/manual/forgejo-proef-17.0
root:root 755 /srv/backups/manual/forgejo-proef-17.0/runner
root:root 644 /srv/backups/manual/forgejo-proef-17.0/runner/config.yml
time="2026-09-30T10:45:24Z" level=info msg="Starting job"
time="2026-09-30T10:45:24Z" level=error msg="Could not start the cache server, cache will be disabled: unable to determine outbound IP address"
time="2026-09-30T10:45:24Z" level=info msg="runner: proef-runner, with version: v12.10.1, with labels: [proef], ephemeral: false, declared successfully"
time="2026-09-30T10:45:24Z" level=info msg="single task poller launched"
time="2026-09-30T10:45:24Z" level=info msg="single task poller successfully fetched one task from http://fj17-rh:3000/"
time="2026-09-30T10:45:24Z" level=info msg="task 1 repo is janpeter/proef-smoke https://data.forgejo.org http://fj17-rh:3000/"
time="2026-09-30T10:45:24Z" level=info msg="single task poller is shutting down"
runner-exit=0
runs: ['success']
status-exit=0
forgejo-runner version v12.10.1
```

(De regel "Could not start the cache server" in de herkansing is de aanleiding voor punt 4 hierboven.)

## 4. Eindproef: het plan zoals het nu luidt

De blokken `b17/bNN.sh` komen uit het planbestand in dezelfde commit als dit bewijs (b01 vaste namen en
de `doctor…`-functies, b02 `migratiecheck`, b04–b13 Fase R, b15 koud rollbackpunt, b16 tagwissel, b18 en
b19 de R4-blokken).

Script:

```sh
#!/usr/bin/env bash
# als janpeter: eindproef van het 17.0-plan op de toestand ná het 15.0.9-venster — blokken letterlijk (b17/bNN.sh), prose-commando's overgenomen
source /trial/b17/b01.sh; S=15.0.9; V17=17.0.0; UID0=1000; GID0=1000
BL=/trial/b17
q() { grep -v -E "^[0-9a-f]{12}: |Pulling|Digest:|Status:|Unable to find|Download|Already exists|Pull complete|Verifying|Waiting|^$|^(real|user|sys)"; }
step() { echo; echo "===== $*"; }
ver() { curl -s http://127.0.0.1:3010/api/v1/version; echo; }
wacht() { timeout 600 sh -c 'until curl -sf http://127.0.0.1:3010/api/v1/version >/dev/null; do sleep 2; done'; }
data() { TK=$(docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token --username janpeter --token-name "w$1-$(date +%s)" --scopes all --raw)
  echo "data: repo $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $TK" http://127.0.0.1:3010/api/v1/repos/janpeter/scrum4me-shared), pakket '$(curl -s -H "Authorization: token $TK" http://127.0.0.1:3010/api/packages/janpeter/generic/proef/1.0.0/p.txt)'"; }
step "0.1/0.2/0.3/0.4/0.13/0.17"
docker exec scrum4me-forgejo forgejo --version | cut -c1-62; docker compose -f "$CF" config --services | tr '\n' ' '; echo
grep -c 'forgejo/forgejo:' "$CF"; grep -n 'image: codeberg.org/forgejo/forgejo' "$CF"
docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini; docker exec scrum4me-forgejo sh -c 'command -v curl'
doctorlog scrum4me-forgejo "$HOME/doctor-pre.log" && doctorbaseline "$HOME/doctor-pre.log"; echo "0.4-exit=$?"
PGU=$(docker exec scrum4me-postgres sh -c 'printf %s "${POSTGRES_USER:-postgres}"'); echo "0.5 R4-databasenaam bezet: $(docker exec scrum4me-postgres psql -U "$PGU" -d postgres -Atc "select count(*) from pg_database where datname = 'forgejo_failed_17_0'")"
if [ -d "$CD/.git" ]; then echo GIT_CF=ja; git -C "$CD" status --porcelain; else echo GIT_CF=nee; fi
docker run --rm --entrypoint /bin/sh "$RUNNER_IMAGE" -c 'echo sh-ok; id'
sudo mkdir -p /tmp/fj17-bundle && sudo cp /trial/bundle/* /tmp/fj17-bundle/
echo; echo "################ FASE R (IMG=17.0-test) ################"
IMG=codeberg.org/forgejo-experimental/forgejo:17.0-test
step "R.0 schone lei"; docker ps -a --filter name=fj17 --format '{{.Names}}'; docker network ls --filter name=fj17 --format '{{.Name}}'; docker volume ls -q --filter name=fj17; sudo test -e "$RH" && echo "RH BESTAAT" || echo "(alle vier leeg / RH bestaat niet)"
step "R.0"; source $BL/b04.sh; echo "exit=$?"
step "R.1"; source $BL/b05.sh 2>&1 | q
step "R.2"; source $BL/b06.sh 2>&1 | q
step "R.3"; source $BL/b07.sh > /tmp/r3.out 2>&1; echo "blok-exit=$?"; q < /tmp/r3.out
TRUSTUSER=janpeter   # op de host: uit 0.18
source $BL/b08.sh; echo "blok-exit=$?"
step "R.4 doctor"; doctorlog fj17-rh "$HOME/proef-doctor.log" && doctortoets "$HOME/doctor-pre.log" "$HOME/proef-doctor.log"; echo "keten-exit=$?"
echo "checks vóór/na: $(doctorsamenvatting "$HOME/doctor-pre.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}') / $(doctorsamenvatting "$HOME/proef-doctor.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}')"
step "R.4 trustgate"; source $BL/b09.sh 2>&1 | tail -3
step "R.4 contract";  source $BL/b10.sh 2>&1 | tail -3
step "R.5 setup + runner"; source $BL/b11.sh 2>&1 | q | cut -c1-190
step "R.5 runstatus"; source $BL/b12.sh; echo "exit=$?"
step "R.6"; docker logs fj17-rh 2>&1 | grep -E '\[F\]|panic|creating new key'; echo "(einde [F]/panic/creating new key)"; echo "[E]-regels: $(docker logs fj17-rh 2>&1 | grep -c '\[E\]')"
step "R.7"; source $BL/b13.sh 2>&1; echo "(einde R.7-blok)"; sudo test -e "$RH" && echo "RH bestaat nog" || echo "RH weg"; echo "volumes met fj17 in de naam: $(docker volume ls -q --filter name=fj17 | wc -l)"
echo; echo "################ VENSTER (V17=17.0.0 = lokale hertag van 17.0-test) ################"
upgrade() {
  step "2.4"; PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); echo "PRE_CF=${PRE_CF:0:16}…"; git -C "$CD" status --porcelain; echo "(einde git status)"
  step "2.6"; doctorlog scrum4me-forgejo "$HOME/doctor-pre-venster.log" && doctorvolledig "$HOME/doctor-pre-venster.log" && echo "VOORLOG VOLLEDIG"; echo "keten-exit=$?"
  docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m; echo "flush-exit=$?"
  docker stop -t 90 scrum4me-forgejo >/dev/null; docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'
  RD=$(docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind)
  step "2.7"; source $BL/b15.sh 2>&1 | q
  step "4.2"; source $BL/b16.sh; echo "exit=$?"
  step "4.3"; T43=$(date +%s); docker compose -f "$CF" up -d --no-deps forgejo 2>&1 | tail -1
  [ "$(docker inspect scrum4me-forgejo --format '{{.Config.Image}} {{.Image}}')" = "codeberg.org/forgejo/forgejo:$V17 $IMGID17" ] && echo "tag V17 en image-ID = IMGID17" || echo "IMAGE WIJKT AF"
  [ "$(docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind)" = "$RD" ] && echo "legacy ID's ongewijzigd, beide running" || echo "LEGACY GEWIJZIGD"
  step "4.4"; wacht; echo "listener na $(( $(date +%s) - T43 ))s"; ver
  docker logs --since "$(date -u -d @"$T43" +%FT%TZ)" scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic|creating new key'; echo "(einde loggrep)"
  step "4.5"; doctorlog scrum4me-forgejo "$HOME/doctor-post.log" && doctortoets "$HOME/doctor-pre-venster.log" "$HOME/doctor-post.log"; echo "keten-exit=$?"
  VNOW=$(docker exec scrum4me-forgejo forgejo --version | grep -oE '1[0-9]+\.[0-9]+\.[0-9]+' | head -1); echo "VNOW=$VNOW"
}
step "1.1–1.3"; sudo mkdir -p "$BK" && sudo chmod 0700 "$BK" && sudo chown root:root "$BK"
echo pad-test | sudo tee "$BK/.cptest" >/dev/null && sudo docker cp "$BK/.cptest" scrum4me-postgres:/tmp/.cptest && docker exec scrum4me-postgres rm /tmp/.cptest && sudo rm "$BK/.cptest"; echo "kopiepad exit=$?"
sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"; echo "warme kopie exit=$?"
IMGID17=$(docker image inspect codeberg.org/forgejo/forgejo:$V17 --format '{{.Id}}'); echo "IMGID17=${IMGID17:0:19}…"
data a; upgrade; data b
echo; echo "################ R4 ################"
docker stop -t 90 scrum4me-forgejo >/dev/null
step "R4.2"; source $BL/b18.sh; echo "exit=$?"
step "R4.3"; source $BL/b19.sh 2>&1 | tr '\n' ' '; echo
step "R4.4"; sudo rsync -aHAX --numeric-ids --delete "$BK/data/" "$VOL/"; echo "exit=$?"
step "R4.5"; sudo sed -i "s|image: codeberg.org/forgejo/forgejo:$V17\$|image: codeberg.org/forgejo/forgejo:$S|" "$CF"; [ "$(sha256sum "$CF" | cut -d' ' -f1)" = "$PRE_CF" ] && echo "COMPOSE TERUG OP PRE_CF" || { echo "COMPOSE WIJKT AF VAN PRE_CF — STOP, JP"; false; }
docker compose -f "$CF" up -d --no-deps forgejo 2>&1 | tail -1
step "R4.6"; wacht; ver; doctorlog scrum4me-forgejo "$HOME/doctor-r4.log" && doctortoets "$HOME/doctor-pre-venster.log" "$HOME/doctor-r4.log"; echo "keten-exit=$?"; data c; git -C "$CD" status --porcelain; echo "(einde git status)"
echo; echo "################ TWEEDE UPGRADE + 6.2 ################"; upgrade; data d
step "6.2"; docker compose -f "$CF" config -q; echo "config-exit=$?"; git -C "$CD" add docker-compose.yml; git -C "$CD" diff --cached | grep '^[+-] '
git -C "$CD" commit -q -m "forgejo $S -> $V17 (onderhoudsvenster proef)"; echo "commit-exit=$?"; git -C "$CD" status --porcelain; echo "(einde git status)"
step "databases"; docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -Atc "select datname from pg_database"' | tr '\n' ' '; echo
```

Uitvoer:

```text

===== 0.1/0.2/0.3/0.4/0.13/0.17
forgejo version 15.0.9+gitea-1.22.0 (release name 15.0.9) buil
dind forgejo runner 
1
3:    image: codeberg.org/forgejo/forgejo:15.0.9
git:git 600
/usr/bin/curl
doctor exit 0 → /home/janpeter/doctor-pre.log
checks: 28
0.4-exit=0
0.5 R4-databasenaam bezet: 0
GIT_CF=ja
sh-ok
uid=1000 gid=1000 groups=1000

################ FASE R (IMG=17.0-test) ################

===== R.0 schone lei
(alle vier leeg / RH bestaat niet)

===== R.0
ec37c61fd283dac47f0227a0be6cb1d74b0f998af0859890f11c8d4f8e9eb54a
true isolated
exit=0

===== R.1
PROEFKOPIE OK

===== R.2
02de6afda0aea8f5bcb8e29c5ef65ca8883a7348dc52740beefb18dac38e30b2
PROEF-DB OK

===== R.3
blok-exit=0
codeberg.org/forgejo-experimental/forgejo:17.0-test
7a850e8c471fc838d3621cd986725b5587b8bcda61430229454ce2685fe68650
migratie + start: 5s
{"version":"17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0"}
curl-dns-exit=6
curl-ip-exit=7
curl-prod-exit=7
[mirror] ENABLED = false
[mailer] ENABLED = false
PROEFTOKEN OK
blok-exit=0

===== R.4 doctor
doctor exit 0 → /home/janpeter/proef-doctor.log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
keten-exit=0
checks vóór/na: 28 / 27

===== R.4 trustgate
ZACHT: janpeter/scrum4me-shared: Actions staat aan maar er is geen workflowmap gevonden
trust-exit=10

===== R.4 contract
CONTRACT OK: 2 runners, 0 jobs

===== R.5 setup + runner
PROEF-SETUP OK voor janpeter
time="2026-09-30T12:21:32Z" level=info msg="Starting job"
time="2026-09-30T12:21:32Z" level=info msg="runner: proef-runner, with version: v12.10.1, with labels: [proef], ephemeral: false, declared successfully"
time="2026-09-30T12:21:32Z" level=info msg="single task poller launched"
time="2026-09-30T12:21:32Z" level=info msg="single task poller received no task from http://fj17-rh:3000/, trying again"
time="2026-09-30T12:21:34Z" level=info msg="single task poller successfully fetched one task from http://fj17-rh:3000/"
time="2026-09-30T12:21:34Z" level=info msg="task 1 repo is janpeter/proef-smoke https://data.forgejo.org http://fj17-rh:3000/"
time="2026-09-30T12:21:34Z" level=info msg="single task poller is shutting down"
runner-exit=0

===== R.5 runstatus
runs: ['success']
exit=0

===== R.6
(einde [F]/panic/creating new key)
[E]-regels: 0

===== R.7
fj17-rh
fj17-rh-db
fj17-rh-pgdata
fj17-rh-net
GEEN NIEUW DANGLING VOLUME
(einde R.7-blok)
RH weg
volumes met fj17 in de naam: 0

################ VENSTER (V17=17.0.0 = lokale hertag van 17.0-test) ################

===== 1.1–1.3
kopiepad exit=0
warme kopie exit=0
IMGID17=sha256:ec8a9e4a0db8…
data: repo 200, pakket 'pakketinhoud'

===== 2.4
PRE_CF=5312bad9e30703c9…
(einde git status)

===== 2.6
doctor exit 0 → /home/janpeter/doctor-pre-venster.log
VOORLOG VOLLEDIG
keten-exit=0
Flushed
flush-exit=0
Exited (0) Less than a second ago

===== 2.7
1c6c7909b1d173c2b515ade11bbf2ec6e541cba5ac03122e81f73d40aab23bc3  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
403316
KOUD ROLLBACKPUNT OK

===== 4.2
TAGWISSEL OK (alleen de forge-imageregel gewijzigd)
exit=0

===== 4.3
 Container scrum4me-forgejo Started 
tag V17 en image-ID = IMGID17
legacy ID's ongewijzigd, beide running

===== 4.4
listener na 2s
{"version":"17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0"}

(einde loggrep)

===== 4.5
doctor exit 0 → /home/janpeter/doctor-post.log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
keten-exit=0
VNOW=17.0.0
data: repo 200, pakket 'pakketinhoud'

################ R4 ################

===== R4.2
exit=0

===== R4.3
ALTER DATABASE postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo forgejo_failed_17_0 

===== R4.4
exit=0

===== R4.5
COMPOSE TERUG OP PRE_CF
 Container scrum4me-forgejo Started 

===== R4.6
{"version":"15.0.9+gitea-1.22.0"}

doctor exit 0 → /home/janpeter/doctor-r4.log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
keten-exit=0
data: repo 200, pakket 'pakketinhoud'
(einde git status)

################ TWEEDE UPGRADE + 6.2 ################

===== 2.4
PRE_CF=5312bad9e30703c9…
(einde git status)

===== 2.6
doctor exit 0 → /home/janpeter/doctor-pre-venster.log
VOORLOG VOLLEDIG
keten-exit=0
Flushed
flush-exit=0
Exited (0) Less than a second ago

===== 2.7
c4b278dd197d922607776de5a5ed754f60d1dece82033497d3ebb89c73e14b55  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
403417
KOUD ROLLBACKPUNT OK

===== 4.2
TAGWISSEL OK (alleen de forge-imageregel gewijzigd)
exit=0

===== 4.3
 Container scrum4me-forgejo Started 
tag V17 en image-ID = IMGID17
legacy ID's ongewijzigd, beide running

===== 4.4
listener na 2s
{"version":"17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0"}

(einde loggrep)

===== 4.5
doctor exit 0 → /home/janpeter/doctor-post.log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
keten-exit=0
VNOW=17.0.0
data: repo 200, pakket 'pakketinhoud'

===== 6.2
config-exit=0
-    image: codeberg.org/forgejo/forgejo:15.0.9
+    image: codeberg.org/forgejo/forgejo:17.0.0
commit-exit=0
(einde git status)

===== databases
postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo forgejo_failed_17_0 
```

Lezing: 0.4 geeft `doctor exit 0` en 28 checks zonder niet-OK-regels; de R4-databasenaam is vrij. Fase R
begint met een schone lei en loopt van R.0 t/m R.7 zonder rood: het netwerk is `true isolated`,
`PROEFKOPIE OK`, `PROEF-DB OK`, de versie van het 17-image, drie probes (6, 7, 7: buiten op naam, buiten
op IP, de productieforge), geen poorten, `[mirror]` en `[mailer]` op `ENABLED = false`, `PROEFTOKEN OK`,
`DOCTOR OK`, `trust-exit=10`, `CONTRACT OK`, `runner-exit=0`, run `success`, schone logs; na R.7 geen
container, netwerk of volume met `fj17` in de naam en `GEEN NIEUW DANGLING VOLUME`. Het venster geeft
`VOORLOG VOLLEDIG`, `KOUD ROLLBACKPUNT OK`, `TAGWISSEL OK`, de juiste image, ongewijzigde
legacy-containers en `DOCTOR OK`. R4 herstelt 15.0.9 met `DOCTOR OK` ten opzichte van het log van vóór het
venster. De tweede upgrade en de commit volgens de hostregel slagen.

## 5. Proeven bij de bevindingen uit de plan-review

### 5.1 Volumes (ronde 1)

In de wegwerp-"host"; de vijf dangling volumes bij de start zijn de restanten van de eerdere proefrondes
met het oude recept — precies het defect.

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": laat de proef anonieme volumes achter, en helpt een benoemd volume + rm -v?
echo "volumes nu: totaal $(docker volume ls -q | wc -l), dangling $(docker volume ls -qf dangling=true | wc -l), met naam fj17*: $(docker volume ls -q --filter name=fj17 | wc -l)"
docker image inspect postgres:17 --format 'postgres:17 VOLUME: {{json .Config.Volumes}}'
docker image inspect code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533 --format 'runner VOLUME: {{json .Config.Volumes}}'
docker image inspect codeberg.org/forgejo-experimental/forgejo:17.0-test --format 'forgejo 17.0-test VOLUME: {{json .Config.Volumes}}'
DV0=$(docker volume ls -qf dangling=true | sort)
echo "--- oud recept: docker run zonder volume, docker rm -f zonder -v"
docker network create --internal fj17-rh-net >/dev/null
docker run -d --name fj17-rh-db --network fj17-rh-net -e POSTGRES_PASSWORD=proefpw123 postgres:17 >/dev/null; sleep 3
docker rm -f fj17-rh-db >/dev/null; echo "dangling erbij: $(comm -13 <(echo "$DV0") <(docker volume ls -qf dangling=true | sort) | wc -l)"
docker volume rm $(comm -13 <(echo "$DV0") <(docker volume ls -qf dangling=true | sort)) >/dev/null
echo "--- nieuw recept: benoemd volume, rm -f -v, volume rm"
docker run -d --name fj17-rh-db --network fj17-rh-net -v fj17-rh-pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=proefpw123 postgres:17 >/dev/null; sleep 3
docker volume ls -q --filter name=fj17
docker rm -f -v fj17-rh-db >/dev/null; echo "na rm -f -v: benoemd volume bestaat nog: $(docker volume ls -q --filter name=fj17 | wc -l) (rm -v verwijdert alleen anonieme volumes)"
docker volume rm fj17-rh-pgdata; docker volume ls -q --filter name=fj17 | wc -l
[ "$(docker volume ls -qf dangling=true | sort)" = "$DV0" ] && echo "dangling volumes gelijk aan vóór de proef" || echo "DANGLING VERSCHILT"
echo "--- runner met timeout: blijft er een container met anoniem volume?"
docker run -d --name fj17-rh-runner --network fj17-rh-net --entrypoint /bin/sh code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533 -c 'sleep 300' >/dev/null
docker rm -f fj17-rh-runner >/dev/null; echo "zonder -v, dangling erbij: $(comm -13 <(echo "$DV0") <(docker volume ls -qf dangling=true | sort) | wc -l)"
docker volume rm $(comm -13 <(echo "$DV0") <(docker volume ls -qf dangling=true | sort)) >/dev/null 2>&1
docker run -d --name fj17-rh-runner --network fj17-rh-net --entrypoint /bin/sh code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533 -c 'sleep 300' >/dev/null
docker rm -f -v fj17-rh-runner >/dev/null; echo "met -v, dangling erbij: $(comm -13 <(echo "$DV0") <(docker volume ls -qf dangling=true | sort) | wc -l)"
echo "--- isolatie op IP-niveau vanuit een container op het interne netwerk"
docker run --rm --network fj17-rh-net --entrypoint /bin/sh codeberg.org/forgejo-experimental/forgejo:17.0-test -c 'curl -s -m 5 -o /dev/null https://1.1.1.1; echo "curl-ip-exit=$?"; curl -s -m 5 -o /dev/null https://codeberg.org; echo "curl-dns-exit=$?"'
docker network rm fj17-rh-net >/dev/null
```

```text
volumes nu: totaal 7, dangling 5, met naam fj17*: 0
postgres:17 VOLUME: {"/var/lib/postgresql/data":{}}
runner VOLUME: {"/data":{}}
forgejo 17.0-test VOLUME: {"/data":{}}
--- oud recept: docker run zonder volume, docker rm -f zonder -v
dangling erbij: 1
--- nieuw recept: benoemd volume, rm -f -v, volume rm
fj17-rh-pgdata
na rm -f -v: benoemd volume bestaat nog: 1 (rm -v verwijdert alleen anonieme volumes)
fj17-rh-pgdata
0
dangling volumes gelijk aan vóór de proef
--- runner met timeout: blijft er een container met anoniem volume?
zonder -v, dangling erbij: 1
met -v, dangling erbij: 0
--- isolatie op IP-niveau vanuit een container op het interne netwerk
curl-ip-exit=7
curl-dns-exit=6
```

### 5.2 Host-gateway en `gateway_mode_ipv4=isolated` (ronde 2)

Een luisteraar op de "host" (poort 8099), benaderd vanuit een container op het proefnetwerk via het
eerste adres van het subnet; en de naamresolutie tussen twee containers op dat netwerk.

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": kan een container op een --internal-netwerk de host bereiken via het gateway-adres,
# en sluit gateway_mode_ipv4=isolated dat af zonder de naamresolutie tussen proefcontainers te breken?
IMG=codeberg.org/forgejo-experimental/forgejo:17.0-test
python3 -m http.server 8099 --bind 0.0.0.0 >/dev/null 2>&1 & HP=$!; sleep 1
proef() { # $1 = netwerknaam
  GW=$(docker network inspect "$1" --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'); echo "gateway volgens docker: ${GW:-geen}"
  docker run -d --name gw-a --network "$1" --entrypoint /bin/sh "$IMG" -c 'sleep 120' >/dev/null
  SUB=$(docker network inspect "$1" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'); G1=$(echo "$SUB" | sed -E 's|\.[0-9]+/[0-9]+$|.1|')
  docker run --rm --network "$1" --entrypoint /bin/sh "$IMG" -c "curl -s -m 4 -o /dev/null http://$G1:8099/; echo \"host via $G1:8099 → curl-exit=\$?\"; curl -s -m 4 -o /dev/null http://gw-a:1/; echo \"naam gw-a resolven+verbinden → curl-exit=\$? (7 = naam gevonden, poort dicht; 6 = naam niet gevonden)\"; curl -s -m 4 -o /dev/null https://1.1.1.1; echo \"buiten op IP → curl-exit=\$?\""
  docker rm -f gw-a >/dev/null
}
echo "=== A. --internal (zoals het plan nu)"; docker network create --internal gw-net-a >/dev/null; proef gw-net-a; docker network rm gw-net-a >/dev/null
echo "=== B. --internal + gateway_mode_ipv4=isolated"; docker network create --internal -o com.docker.network.bridge.gateway_mode_ipv4=isolated gw-net-b >/dev/null; echo "create-exit=$?"; proef gw-net-b; docker network inspect gw-net-b --format 'Internal={{.Internal}} opties={{json .Options}}'; docker network rm gw-net-b >/dev/null
kill $HP 2>/dev/null; docker version --format 'docker {{.Server.Version}}'
```

```text
=== A. --internal (zoals het plan nu)
gateway volgens docker: 172.21.0.1
host via 172.21.0.1:8099 → curl-exit=0
naam gw-a resolven+verbinden → curl-exit=7 (7 = naam gevonden, poort dicht; 6 = naam niet gevonden)
buiten op IP → curl-exit=7
=== B. --internal + gateway_mode_ipv4=isolated
create-exit=0
gateway volgens docker: invalid IP
host via 172.21.0.1:8099 → curl-exit=7
naam gw-a resolven+verbinden → curl-exit=7 (7 = naam gevonden, poort dicht; 6 = naam niet gevonden)
buiten op IP → curl-exit=7
Internal=true opties={"com.docker.network.bridge.gateway_mode_ipv4":"isolated"}
docker 29.8.1
```

Lezing: met alleen `--internal` is de host bereikbaar (exit 0); met `gateway_mode_ipv4=isolated` niet
(exit 7), terwijl de naam van de andere container nog wordt gevonden (exit 7 = gevonden, poort dicht; 6
zou "niet gevonden" zijn) en buiten onbereikbaar blijft.

De directe meting: heeft de host een adres op de bridge van het proefnetwerk?

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": heeft de host een adres op de bridge van het proefnetwerk? (de directe meting van "de host is onbereikbaar")
hostadres() { local br; br=br-$(docker network inspect "$1" --format '{{.Id}}' | cut -c1-12); echo "bridge $br: $(ip -4 -o addr show dev "$br" | awk '{print $4}' | tr '\n' ' ')(einde adressen)"; }
echo "=== A. --internal zonder isolated"; docker network create --internal br-a-net >/dev/null; hostadres br-a-net; docker network rm br-a-net >/dev/null
echo "=== B. --internal + isolated";      docker network create --internal -o com.docker.network.bridge.gateway_mode_ipv4=isolated br-b-net >/dev/null; hostadres br-b-net
docker network inspect br-b-net --format '{{.Internal}} {{index .Options "com.docker.network.bridge.gateway_mode_ipv4"}}'; docker network rm br-b-net >/dev/null
```

```text
=== A. --internal zonder isolated
bridge br-f766bed15011: 172.21.0.1/16 (einde adressen)
=== B. --internal + isolated
bridge br-2c43ecabae6c: (einde adressen)
true isolated
```

En waarom een probe naar "het eerste adres van het subnet" in de geïsoleerde modus niets over de host
zegt (plan-review ronde 3): zonder gateway krijgt een container dat adres. De eerste twee regels per
netwerk laten ook zien welke probevorm een bereikbaar hostproces herkent (`nc -z` en `curl http` wel,
`curl telnet://` niet: die geeft 28, ook als de verbinding er is).

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": welke probevorm onderscheidt "hostproces bereikbaar" van "niet bereikbaar"?
# Een hostproces (python-luisteraar op 0.0.0.0:8022, zoals sshd op 22 op de echte host) wordt benaderd via het eerste adres van het subnet.
IMG=codeberg.org/forgejo-experimental/forgejo:17.0-test
python3 -m http.server 8022 --bind 0.0.0.0 >/dev/null 2>&1 & HP=$!; sleep 1
proef() {
  G1=$(docker network inspect "$1" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' | sed -E 's|\.[0-9]+/[0-9]+$|.1|')
  docker run --rm --network "$1" --entrypoint /bin/sh "$IMG" -c "
    nc -z -w 5 $G1 8022; echo \"nc -z exit=\$?\"
    curl -s -m 5 -o /dev/null telnet://$G1:8022 </dev/null; echo \"curl telnet exit=\$?\"
    curl -s -m 5 -o /dev/null http://$G1:8022/; echo \"curl http exit=\$?\"
    nc -z -w 5 $G1 8023; echo \"nc -z naar een poort waar niets luistert exit=\$?\""
}
echo "=== A. --internal zonder isolated (host bereikbaar)"; docker network create --internal pr-a >/dev/null; proef pr-a; docker network rm pr-a >/dev/null
echo "=== B. --internal + isolated"; docker network create --internal -o com.docker.network.bridge.gateway_mode_ipv4=isolated pr-b >/dev/null; proef pr-b
echo "--- krijgt een container in isolated-modus het .1-adres?"; for i in 1 2 3; do docker run -d --name pr-c$i --network pr-b --entrypoint /bin/sh "$IMG" -c 'sleep 60' >/dev/null; done
docker network inspect pr-b --format '{{range .Containers}}{{.Name}}={{.IPv4Address}} {{end}}'; docker rm -f pr-c1 pr-c2 pr-c3 >/dev/null; docker network rm pr-b >/dev/null
kill $HP 2>/dev/null
```

```text
=== A. --internal zonder isolated (host bereikbaar)
nc -z exit=0
curl telnet exit=28
curl http exit=0
nc -z naar een poort waar niets luistert exit=1
=== B. --internal + isolated
nc -z exit=1
curl telnet exit=7
curl http exit=7
nc -z naar een poort waar niets luistert exit=1
--- krijgt een container in isolated-modus het .1-adres?
pr-c2=172.21.0.2/16 pr-c3=172.21.0.3/16 pr-c1=172.21.0.1/16 
```

### 5.3 Proeftoken fail-closed en de dangling-diagnostiek (ronde 2)

Het tokenblok uit R.3 en de vergelijking uit R.0/R.7, in dezelfde vorm als in het plan (de draaiende
proef-forge doet hier dienst als `fj17-rh`).

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": het R.3-tokenblok (fail-closed) en de dangling-vergelijking uit R.0/R.7, met afwijkingsgevallen
RH=/srv/backups/manual/forgejo-proef-17.0
tokenblok() {
  ( set -e -o pipefail
    [ -n "$TRUSTUSER" ]
    docker exec -u git fj17-rh forgejo admin user generate-access-token --username "$TRUSTUSER" --token-name "proef-$1" --scopes all --raw | sudo tee "$RH/proef.token" >/dev/null
    sudo chmod 0600 "$RH/proef.token"
    sudo test -s "$RH/proef.token"
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "PROEFTOKEN OK" || { echo "PROEFTOKEN MISLUKT (exit $rc) — STOP"; false; }
}
sudo install -d -m 0700 -o root -g root "$RH"
docker rm -f fj17-rh >/dev/null 2>&1; docker tag scrum4me-forgejo-stub:latest x 2>/dev/null
# de draaiende proef-forge (15.0.9 of 17) doet hier dienst als "fj17-rh": alleen het token-CLI-gedrag wordt beproefd
docker rename scrum4me-forgejo fj17-rh
echo "--- a. geldige gebruiker";      TRUSTUSER=janpeter;      tokenblok a; echo "exit=$? bytes=$(sudo cat "$RH/proef.token" | wc -c)"
echo "--- b. lege TRUSTUSER";         TRUSTUSER=;              sudo rm -f "$RH/proef.token"; tokenblok b; echo "exit=$?"; sudo test -e "$RH/proef.token" && echo "bestand: $(sudo cat "$RH/proef.token" | wc -c) bytes" || echo "geen bestand"
echo "--- c. onbekende gebruiker";    TRUSTUSER=bestaat-niet;  sudo rm -f "$RH/proef.token"; tokenblok c 2>&1 | tail -2; echo "exit=${PIPESTATUS[0]}"; echo "bestand: $(sudo cat "$RH/proef.token" 2>/dev/null | wc -c) bytes"
docker rename fj17-rh scrum4me-forgejo
echo "--- 0.18: is TRUSTUSER site-admin? (leesbaar op de productieforge, geen token nodig)"
docker exec -u git scrum4me-forgejo forgejo admin user list --admin | awk 'NR==1 || $2=="janpeter"' | cut -c1-90
echo "--- dangling-vergelijking"
B="$HOME/fj17-dangling-voor.txt"
toets() { if [ -r "$B" ]; then NIEUW=$(LC_ALL=C comm -13 "$B" <(docker volume ls -qf dangling=true | LC_ALL=C sort)); else NIEUW="(baseline ontbreekt)"; fi
  [ -z "$NIEUW" ] && echo "GEEN NIEUW DANGLING VOLUME" || { echo "NIEUW DANGLING VOLUME of geen baseline: $NIEUW — beoordelen"; false; }; }
docker volume ls -qf dangling=true | LC_ALL=C sort > "$B"; echo "baseline: $(wc -l < "$B") volumes"
echo "d. niets veranderd:";            toets; echo "exit=$?"
V=$(docker volume create); echo "e. één nieuw dangling volume:"; toets | cut -c1-60; echo "exit=${PIPESTATUS[0]}"
docker volume rm "$V" >/dev/null
OUD=$(head -1 "$B"); [ -n "$OUD" ] && docker volume rm "$OUD" >/dev/null && echo "f. een bestaand dangling volume verdween (andere sessie):" && toets; echo "exit=$?"
rm -f "$B"; echo "g. baseline ontbreekt:"; toets; echo "exit=$?"
sudo rm -rf "$RH"
```

```text
--- a. geldige gebruiker
PROEFTOKEN OK
exit=0 bytes=41
--- b. lege TRUSTUSER
PROEFTOKEN MISLUKT (exit 1) — STOP
exit=1
geen bestand
--- c. onbekende gebruiker
Command error: user does not exist [uid: 0, name: bestaat-niet]
PROEFTOKEN MISLUKT (exit 1) — STOP
exit=1
bestand: 0 bytes
--- 0.18: is TRUSTUSER site-admin? (leesbaar op de productieforge, geen token nodig)
ID   Username Email           IsActive
1    janpeter jp@example.test true
--- dangling-vergelijking
baseline: 5 volumes
d. niets veranderd:
GEEN NIEUW DANGLING VOLUME
exit=0
e. één nieuw dangling volume:
NIEUW DANGLING VOLUME of geen baseline: 31a2f36d17f79eba3826
exit=1
f. een bestaand dangling volume verdween (andere sessie):
GEEN NIEUW DANGLING VOLUME
exit=0
g. baseline ontbreekt:
NIEUW DANGLING VOLUME of geen baseline: (baseline ontbreekt) — beoordelen
exit=1
```

Lezing: een geldige gebruiker geeft `PROEFTOKEN OK` en een bestand van 41 bytes; een lege en een onbekende
gebruikersnaam geven `PROEFTOKEN MISLUKT` met exit 1 (bij de lege naam wordt het bestand niet eens
aangemaakt). De dangling-diagnostiek meldt alleen volumes die erbij zijn gekomen; een verdwenen volume
telt niet, en een ontbrekende baseline wordt gemeld in plaats van als "niets nieuws" gelezen. De
account-opzoeking met het productietoken uit de vorige planversie is vervallen en wordt hier niet meer
beproefd.

### 5.4 `migratiecheck` (ronde 1 en 2)

De functie is byte-gelijk aan het blok in stap 0.0 van het plan; gedraaid op de mac tegen de Codeberg-API
en met gestubde antwoorden.

```sh
migratiecheck() {   # $1 = oudere tag, $2 = nieuwere tag (bv. v17.0.1 v17.0.2): exit 0 alleen bij een geldig antwoord zonder migratiebestanden
  local f rc; f=$(mktemp)
  curl -sS --fail-with-body --max-time 180 -o "$f" "https://codeberg.org/api/v1/repos/forgejo/forgejo/compare/$1...$2"; rc=$?
  if [ "$rc" -ne 0 ]; then echo "MIGRATIECHECK ROOD: ophalen mislukte (curl exit $rc) — geen vrijgave"; rm -f "$f"; return 1; fi
  python3 - "$f" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("MIGRATIECHECK ROOD: geen geldige JSON —", e); sys.exit(1)
files, commits = (d.get("files"), d.get("total_commits")) if isinstance(d, dict) else (None, None)
if not (isinstance(files, list) and files and isinstance(commits, int) and commits > 0
        and all(isinstance(x, dict) and isinstance(x.get("filename"), str) for x in files)):
    print("MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave"); sys.exit(1)
hits = sorted({x["filename"] for x in files if x["filename"].startswith(("models/forgejo_migrations", "models/gitea_migrations"))})
if hits:
    print("MIGRATIECHECK ROOD: migratiebestanden gewijzigd —", hits); sys.exit(1)
print(f"GEEN MIGRATIE IN DE BRON ({len(files)} bestanden, {commits} commits)")
PY
  rc=$?; rm -f "$f"; return "$rc"
}

# --- proefscript ---
#!/usr/bin/env bash
# Proef van migratiecheck (stap 0.0): echte Codeberg-antwoorden en foutgevallen
source "$(dirname "$0")/functie.sh"
geval() { echo; echo "=== $1"; shift; "$@"; echo "exit=$?"; }
geval "1. echt, geen migratie: v16.0.4 → v16.0.5"          migratiecheck v16.0.4 v16.0.5
geval "2. echt, wél een migratie: v16.0.0 → v16.0.5"       migratiecheck v16.0.0 v16.0.5
geval "3. echt, niet-bestaande tag (HTTP 404)"             migratiecheck v16.0.5 v16.0.99
geval "4. echt, twee keer dezelfde tag (0 commits)"        migratiecheck v16.0.5 v16.0.5
geval "5. echt, tags omgedraaid (nieuw...oud)"             migratiecheck v16.0.5 v16.0.4
stub() { FIX="$1"; curl() { local o; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && o="$2"; shift; done; printf '%s' "$FIX" > "$o"; return 0; }; }
stub '{}';                                                   geval "6. stub: leeg object bij HTTP-succes"          migratiecheck a b
stub '{"message":"reference does not exist","errors":[]}';   geval "7. stub: foutobject bij HTTP-succes"           migratiecheck a b
stub '{"total_commits":3,"files":[]}';                       geval "8. stub: commits maar lege files-lijst"        migratiecheck a b
stub 'geen json';                                            geval "9. stub: geen JSON"                            migratiecheck a b
stub '{"total_commits":2,"files":[{"filename":"README.md"},{"filename":"models/forgejo_migrations_legacy/v99.go"}]}'; geval "10. stub: legacy-migratiemap" migratiecheck a b
stub '{"total_commits":2,"files":[{"filename":"README.md"}]}'; geval "11. stub: geldig, geen migratie"             migratiecheck a b
```

```text

=== 1. echt, geen migratie: v16.0.4 → v16.0.5
GEEN MIGRATIE IN DE BRON (32 bestanden, 10 commits)
exit=0

=== 2. echt, wél een migratie: v16.0.0 → v16.0.5
MIGRATIECHECK ROOD: migratiebestanden gewijzigd — ['models/forgejo_migrations/v17a_add-action-run-workflow-source-commit.go']
exit=1

=== 3. echt, niet-bestaande tag (HTTP 404)
curl: (22) The requested URL returned error: 404
MIGRATIECHECK ROOD: ophalen mislukte (curl exit 22) — geen vrijgave
exit=1

=== 4. echt, twee keer dezelfde tag (0 commits)
MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave
exit=1

=== 5. echt, tags omgedraaid (nieuw...oud)
MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave
exit=1

=== 6. stub: leeg object bij HTTP-succes
MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave
exit=1

=== 7. stub: foutobject bij HTTP-succes
MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave
exit=1

=== 8. stub: commits maar lege files-lijst
MIGRATIECHECK ROOD: onverwacht antwoord (geen niet-lege files-lijst of geen commits) — geen vrijgave
exit=1

=== 9. stub: geen JSON
MIGRATIECHECK ROOD: geen geldige JSON — Expecting value: line 1 column 1 (char 0)
exit=1

=== 10. stub: legacy-migratiemap
MIGRATIECHECK ROOD: migratiebestanden gewijzigd — ['models/forgejo_migrations_legacy/v99.go']
exit=1

=== 11. stub: geldig, geen migratie
GEEN MIGRATIE IN DE BRON (1 bestanden, 2 commits)
exit=0
```

Lezing: alleen een geldig antwoord zonder migratiebestanden geeft exit 0 (1, 11). Een migratiebestand in
een patchlijn wordt gevonden (2: tussen 16.0.0 en 16.0.5), ook in de legacy-map (10). Een niet-bestaande
tag (HTTP 404), gelijke of verwisselde tags, een leeg object, een foutobject, een lege bestandslijst en
niet-JSON geven alle `MIGRATIECHECK ROOD` (3–9).
