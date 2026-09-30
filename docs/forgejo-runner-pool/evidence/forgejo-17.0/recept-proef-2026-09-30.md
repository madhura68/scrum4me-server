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
- De proefinstance heeft geen uitgaand verkeer (`curl` naar buiten: exit 6) en geen gepubliceerde poorten.
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
6. Klein: de runnerconfig van de proef zet nu `cache.enabled: false` (zoals de productiepolicy); zonder dat
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
de `doctor…`-functies, b03–b11 Fase R, b13 koud rollbackpunt, b14 tagwissel, b16 en b17 de R4-blokken).

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
step "R.0"; source $BL/b03.sh; echo "exit=$?"
step "R.1"; source $BL/b04.sh 2>&1 | q
step "R.2"; source $BL/b05.sh 2>&1 | q
step "R.3"; source $BL/b06.sh > /tmp/r3.out 2>&1; echo "blok-exit=$?"; q < /tmp/r3.out
docker exec fj17-rh sh -c 'curl -s -m 5 -o /dev/null https://codeberg.org; echo "curl-dns-exit=$?"; curl -s -m 5 -o /dev/null https://1.1.1.1; echo "curl-ip-exit=$?"'; docker port fj17-rh; echo "(einde docker port)"
docker exec fj17-rh awk '/^\[/{s=$0} (s=="[mirror]"||s=="[mailer]") && /^ENABLED/{print s, $0}' /data/gitea/conf/app.ini
TRUSTUSER=janpeter   # op de host: uit 0.18
docker exec -u git fj17-rh forgejo admin user generate-access-token --username "$TRUSTUSER" --token-name proef --scopes all --raw | sudo tee "$RH/proef.token" >/dev/null && sudo chmod 0600 "$RH/proef.token"; echo "token-exit=$?"
step "R.4 doctor"; doctorlog fj17-rh "$HOME/proef-doctor.log" && doctortoets "$HOME/doctor-pre.log" "$HOME/proef-doctor.log"; echo "keten-exit=$?"
echo "checks vóór/na: $(doctorsamenvatting "$HOME/doctor-pre.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}') / $(doctorsamenvatting "$HOME/proef-doctor.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}')"
step "R.4 trustgate"; source $BL/b07.sh 2>&1 | tail -3
step "R.4 contract";  source $BL/b08.sh 2>&1 | tail -3
step "R.5 setup + runner"; source $BL/b09.sh 2>&1 | q | cut -c1-190
step "R.5 runstatus"; source $BL/b10.sh; echo "exit=$?"
step "R.6"; docker logs fj17-rh 2>&1 | grep -E '\[F\]|panic|creating new key'; echo "(einde [F]/panic/creating new key)"; echo "[E]-regels: $(docker logs fj17-rh 2>&1 | grep -c '\[E\]')"
step "R.7"; source $BL/b11.sh 2>&1; echo "(einde R.7-blok)"; sudo test -e "$RH" && echo "RH bestaat nog" || echo "RH weg"; echo "volumes met fj17 in de naam: $(docker volume ls -q --filter name=fj17 | wc -l)"
echo; echo "################ VENSTER (V17=17.0.0 = lokale hertag van 17.0-test) ################"
upgrade() {
  step "2.4"; PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); echo "PRE_CF=${PRE_CF:0:16}…"; git -C "$CD" status --porcelain; echo "(einde git status)"
  step "2.6"; doctorlog scrum4me-forgejo "$HOME/doctor-pre-venster.log" && doctorvolledig "$HOME/doctor-pre-venster.log" && echo "VOORLOG VOLLEDIG"; echo "keten-exit=$?"
  docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m; echo "flush-exit=$?"
  docker stop -t 90 scrum4me-forgejo >/dev/null; docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'
  RD=$(docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind)
  step "2.7"; source $BL/b13.sh 2>&1 | q
  step "4.2"; source $BL/b14.sh; echo "exit=$?"
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
step "R4.2"; source $BL/b16.sh; echo "exit=$?"
step "R4.3"; source $BL/b17.sh 2>&1 | tr '\n' ' '; echo
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

===== R.0
4619a0747201c210b3f8d132a4339677f1f926793b85f1c4da43ad707842b035
true
exit=0

===== R.1
PROEFKOPIE OK

===== R.2
40c0ec64fe943aa2d65fc59ad04971ee5e294fd6730caa7bb5eea36c1f04f5c1
PROEF-DB OK

===== R.3
blok-exit=0
codeberg.org/forgejo-experimental/forgejo:17.0-test
dab4270c8e80c4a98bc7c1f4e0f0b52946f33e81acd1e1218dc75368b47ccd98
migratie + start: 5s
{"version":"17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0"}
curl-dns-exit=6
curl-ip-exit=7
(einde docker port)
[mirror] ENABLED = false
[mailer] ENABLED = false
token-exit=0

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
time="2026-09-30T11:53:41Z" level=info msg="Starting job"
time="2026-09-30T11:53:41Z" level=info msg="runner: proef-runner, with version: v12.10.1, with labels: [proef], ephemeral: false, declared successfully"
time="2026-09-30T11:53:41Z" level=info msg="single task poller launched"
time="2026-09-30T11:53:41Z" level=info msg="single task poller received no task from http://fj17-rh:3000/, trying again"
time="2026-09-30T11:53:43Z" level=info msg="single task poller successfully fetched one task from http://fj17-rh:3000/"
time="2026-09-30T11:53:43Z" level=info msg="task 1 repo is janpeter/proef-smoke https://data.forgejo.org http://fj17-rh:3000/"
time="2026-09-30T11:53:43Z" level=info msg="single task poller is shutting down"
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
31eab09ccdad932e2b381fe30f5a0bed0f26aa7689d5a01f5d4518e827ed6e7a  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
402908
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
ALTER DATABASE postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo_failed_17_0 forgejo 

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
cfefec05d68106f0c98f9545fa7daf30de9346761e6e155501ef4a6a6fe97df2  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
403009
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
postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo_failed_17_0 forgejo 
```

Lezing: 0.4 geeft `doctor exit 0` en 28 checks zonder niet-OK-regels; de R4-databasenaam is vrij. Fase R
loopt van R.0 t/m R.7 zonder rood: `PROEFKOPIE OK`, `PROEF-DB OK`, de versie van het 17-image, geen
verkeer naar buiten op naam (exit 6) en op IP (exit 7), geen poorten, `[mirror]` en `[mailer]` op
`ENABLED = false`, `DOCTOR OK`, `trust-exit=10`, `CONTRACT OK`, `runner-exit=0`, run `success`, schone
logs; na R.7 geen container, netwerk of volume met `fj17` in de naam en `GEEN NIEUW DANGLING VOLUME`.
Het venster geeft `VOORLOG VOLLEDIG`, `KOUD ROLLBACKPUNT OK`, `TAGWISSEL OK`, de juiste image,
ongewijzigde legacy-containers en `DOCTOR OK`. R4 herstelt 15.0.9 met `DOCTOR OK` ten opzichte van het log
van vóór het venster. De tweede upgrade en de commit volgens de hostregel slagen.

## 5. Proeven bij de bevindingen van plan-review ronde 1

**Volumes en isolatie op IP-niveau** (in de wegwerp-"host"; de vijf dangling volumes bij de start zijn de
restanten van de eerdere proefrondes met het oude recept — precies het defect):

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

**Het account van de productiescan (0.18)** — het commando uit het plan, met de URL van de proef-forge en
een proeftoken in een root-only env-bestand van dezelfde vorm als `trust-scan.env`:

```sh
#!/usr/bin/env bash
# als janpeter in de wegwerp-"host": het 0.18-commando voor TRUSTUSER, tegen de proef-forge (URL aangepast; env-bestand met een proeftoken, root 0600)
TK=$(docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token --username janpeter --token-name "tu-$(date +%s)" --scopes all --raw)
sudo mkdir -p /opt/forgejo-runner/credentials && printf 'FORGEJO_TOKEN=%s\n' "$TK" | sudo tee /opt/forgejo-runner/credentials/trust-scan.env >/dev/null && sudo chmod 0600 /opt/forgejo-runner/credentials/trust-scan.env
sudo bash -c 'set -a; . /opt/forgejo-runner/credentials/trust-scan.env; set +a; curl --config <(printf "header = \"Authorization: token %s\"\n" "$FORGEJO_TOKEN") -sS --fail-with-body --max-time 30 http://127.0.0.1:3010/api/v1/user' | python3 -c 'import json,sys; print(json.load(sys.stdin)["login"])'
echo "exit=${PIPESTATUS[0]}/${PIPESTATUS[1]}"; sudo rm -rf /opt/forgejo-runner
```

```text
janpeter
exit=0/0
```

**Migraties tussen twee tags (0.0)** — het filter uit het plan tegen de Codeberg-API, 30 september 2026.
De patchlijn 16.0.x bevat een migratiebestand dat tussen 16.0.0 en 16.0.5 is gewijzigd: releasenotes
alleen zijn dus geen betrouwbare bron, de brontoets wel.

```text
v16.0.4...v16.0.5 → []
v16.0.0...v16.0.1 → []
v16.0.0...v16.0.5 → 425 bestanden, 93 commits; treffer: models/forgejo_migrations/v17a_add-action-run-workflow-source-commit.go
v16.0.5...v17.0/forgejo → 3522 bestanden, 581 commits; treffers o.a. models/forgejo_migrations/v17a_add_package_cleanup_based_on_last_download.go,
                          models/forgejo_migrations/v17a_add_action_task_step_summary.go, models/forgejo_migrations_legacy/v32_test.go
```
