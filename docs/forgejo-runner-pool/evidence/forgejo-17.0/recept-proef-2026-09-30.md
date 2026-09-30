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
4. Klein: de runnerconfig van de proef zet nu `cache.enabled: false` (zoals de productiepolicy); zonder dat
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
docker exec fj17-rh sh -c 'curl -s -m 5 -o /dev/null https://codeberg.org; echo "curl-exit=$?"'; docker port fj17-rh; echo "(einde docker port)"
docker exec -u git fj17-rh forgejo admin user generate-access-token --username janpeter --token-name proef --scopes all --raw | sudo tee "$RH/proef.token" >/dev/null && sudo chmod 0600 "$RH/proef.token"; echo "token-exit=$?"
step "R.4 doctor"; doctorlog fj17-rh "$HOME/proef-doctor.log" && doctortoets "$HOME/doctor-pre.log" "$HOME/proef-doctor.log"; echo "keten-exit=$?"
echo "checks vóór/na: $(doctorsamenvatting "$HOME/doctor-pre.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}') / $(doctorsamenvatting "$HOME/proef-doctor.log" | awk -F'\t' '$1=="V"{c++} END{print c+0}')"
step "R.4 trustgate"; source $BL/b07.sh 2>&1 | tail -3
step "R.4 contract";  source $BL/b08.sh 2>&1 | tail -3
step "R.5 setup + runner"; source $BL/b09.sh 2>&1 | q | cut -c1-190
step "R.5 runstatus"; source $BL/b10.sh; echo "exit=$?"
step "R.6"; docker logs fj17-rh 2>&1 | grep -E '\[F\]|panic|creating new key'; echo "(einde [F]/panic/creating new key)"; echo "[E]-regels: $(docker logs fj17-rh 2>&1 | grep -c '\[E\]')"
step "R.7"; source $BL/b11.sh 2>&1; echo "(einde R.7-controles)"; sudo test -e "$RH" && echo "RH bestaat nog" || echo "RH weg"
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
34513572a4bde74cc58df44b9a0d716e640767901cf72fbdce3bc49f202e4850
true
exit=0

===== R.1
PROEFKOPIE OK

===== R.2
d80e56f129bb76f22ffd421f4d0e70c63f89861d577be95392eecd4732670a9c
PROEF-DB OK

===== R.3
blok-exit=0
codeberg.org/forgejo-experimental/forgejo:17.0-test
f6b492e021f3b39993dfc01397bc5e734c4f8c6f52feccd5f4796ad6645f4246
migratie + start: 5s
{"version":"17.0.0-dev-577-c4d05ee1a9+gitea-1.22.0"}
curl-exit=6
(einde docker port)
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
time="2026-09-30T11:30:06Z" level=info msg="Starting job"
time="2026-09-30T11:30:06Z" level=info msg="runner: proef-runner, with version: v12.10.1, with labels: [proef], ephemeral: false, declared successfully"
time="2026-09-30T11:30:06Z" level=info msg="single task poller launched"
time="2026-09-30T11:30:06Z" level=info msg="single task poller received no task from http://fj17-rh:3000/, trying again"
time="2026-09-30T11:30:08Z" level=info msg="single task poller successfully fetched one task from http://fj17-rh:3000/"
time="2026-09-30T11:30:08Z" level=info msg="task 1 repo is janpeter/proef-smoke https://data.forgejo.org http://fj17-rh:3000/"
time="2026-09-30T11:30:08Z" level=info msg="single task poller is shutting down"
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
fj17-rh-net
(einde R.7-controles)
RH weg

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
bb8c46468bdf48bd7a5fca9efc820430eda9f043d9f5c5367747e81fcd67f9c7  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
402701
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
1580c8acc3a060403dc526007629eab82c83925c5f86cbd298df91879a8646f0  /srv/backups/manual/forgejo-pre-17.0/forgejo-pre-17.dump
402803
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
loopt van R.0 t/m R.7 zonder rood (`PROEFKOPIE OK`, `PROEF-DB OK`, versie van het 17-image, geen uitgaand
verkeer, `DOCTOR OK`, `trust-exit=10`, `CONTRACT OK`, `runner-exit=0`, run `success`, schone logs, alles
opgeruimd). Het venster geeft `VOORLOG VOLLEDIG`, `KOUD ROLLBACKPUNT OK`, `TAGWISSEL OK`, de juiste image,
ongewijzigde legacy-containers en `DOCTOR OK`. R4 herstelt 15.0.9 met `DOCTOR OK` ten opzichte van het log
van vóór het venster. De tweede upgrade en de commit volgens de hostregel slagen.
