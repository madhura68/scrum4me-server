# Vensterproef 15.0.2 → 15.0.9 in een wegwerpomgeving (30 september 2026)

Bewijs bij [implementatieplan-forgejo-15.0.9.md](../../implementatieplan-forgejo-15.0.9.md), "Vensterproef en D10".
De stappen 2.4 t/m 4.5, R3, R4 en 6.2 zijn **letterlijk uit het plan** uitgevoerd: de shellblokken zijn
uit het planbestand geëxtraheerd (`bNN.sh`, in volgorde van voorkomen) en met `source` gedraaid; de
commando's die in de lopende tekst staan, zijn overgenomen in het script hieronder. Er is geen host en
geen productiedata geraakt.

## 1. Omgeving en afwijkingen van productie

- **"Host":** een `docker:dind`-container op de mac (Docker 29.8.1, bash 5.3.9, GNU sed 4.9, Docker Compose
  5.5.1), met een gebruiker `janpeter` in de docker-groep en `sudo` zonder wachtwoord — zoals het plan de
  uitvoerder veronderstelt.
- **Zelfde namen en paden als productie:** containers `scrum4me-postgres` (image `postgres:17`, superuser
  `scrum4me`, database `forgejo` van rol `forgejo`), `scrum4me-forgejo`, `scrum4me-forgejo-runner`,
  `scrum4me-forgejo-dind`; compose-project `forgejo` in `/srv/scrum4me/forgejo`; volume
  `forgejo_forgejo-data` op `/var/lib/docker/volumes/forgejo_forgejo-data/_data`; compose-map onder git via
  `scripts/compose-git-init` (`GIT_CF=ja`).
- **Afwijkingen:** de legacy runner en DinD zijn stubs (`busybox sleep`), alleen om te bewijzen dat
  `--no-deps` hun container-ID's niet raakt; de instance bevat één repository, één generic package en geen
  echte gebruikers; er is geen Caddy (3.2/3.3 zijn niet beproefd), geen `max2` en geen runnerpool (2.1–2.3,
  Fase 5 zijn niet beproefd); architectuur arm64. `app.ini` is bij de eerste start door de entrypoint
  gevuld vanuit env-variabelen en bevat daarna, zoals productie, `JWT_SECRET`, `LFS_JWT_SECRET` en een
  expliciete `REVERSE_PROXY_TRUSTED_PROXIES = *`; de compose-service zelf zet geen `FORGEJO__`-variabelen
  (app.ini-tak).
- De omgeving diende eerst voor de proef van het 17.0-plan en is daarna door het opzetscript teruggezet.

## 2. Opzet van de broninstance (geen plantekst)

```sh
#!/usr/bin/env bash
# als janpeter: proefomgeving resetten en een 15.0.2-broninstance opzetten zoals productie (compose-project forgejo, app.ini-tak)
set -e
cd /srv/scrum4me/forgejo && docker compose -f docker-compose.yml down >/dev/null 2>&1 || true      # alleen in de wegwerpomgeving
sudo rm -rf /srv/scrum4me/forgejo/.git /srv/scrum4me/forgejo/.gitignore /srv/backups/manual/* ; docker volume rm forgejo_forgejo-data >/dev/null
docker exec scrum4me-postgres psql -q -U scrum4me -d postgres -c 'drop database if exists forgejo' -c 'drop database if exists forgejo_failed_17_0' -c 'create database forgejo owner forgejo'
docker volume create forgejo_forgejo-data >/dev/null
docker run -d --name scrum4me-forgejo --network compose_default -v forgejo_forgejo-data:/data -e USER_UID=1000 -e USER_GID=1000 \
  -e FORGEJO__database__DB_TYPE=postgres -e FORGEJO__database__HOST=scrum4me-postgres:5432 -e FORGEJO__database__NAME=forgejo \
  -e FORGEJO__database__USER=forgejo -e FORGEJO__database__PASSWD=fjproef12 \
  -e FORGEJO__security__INSTALL_LOCK=true -e 'FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES=*' \
  -e FORGEJO__server__ROOT_URL=https://git.example.test/ -e FORGEJO__server__LFS_START_SERVER=true -e FORGEJO__actions__ENABLED=true \
  codeberg.org/forgejo/forgejo:15.0.2 >/dev/null
timeout 300 sh -c 'until docker exec scrum4me-forgejo curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; do sleep 3; done'
docker exec -u git scrum4me-forgejo forgejo admin user create --admin --username janpeter --password 'Proef-Wachtw-1' --email jp@example.test --must-change-password=false | tail -1
docker rm -f scrum4me-forgejo >/dev/null
sed -i 's|forgejo/forgejo:15.0.9|forgejo/forgejo:15.0.2|; s|forgejo/forgejo:17.0.0|forgejo/forgejo:15.0.2|' docker-compose.yml
docker compose -f docker-compose.yml up -d 2>&1 | tail -1
timeout 300 sh -c 'until curl -sf http://127.0.0.1:3010/api/v1/version >/dev/null; do sleep 3; done'
echo "bron: $(curl -s http://127.0.0.1:3010/api/v1/version)"
TOK=$(docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token --username janpeter --token-name setup --scopes all --raw)
api() { curl -sS --fail-with-body -H "Authorization: token $TOK" -H 'Content-Type: application/json' "$@"; }
api -X POST -d '{"name":"scrum4me-shared","auto_init":true,"private":true}' http://127.0.0.1:3010/api/v1/user/repos >/dev/null
echo "pakketinhoud" > /tmp/p.txt; curl -sS --fail-with-body -H "Authorization: token $TOK" -T /tmp/p.txt http://127.0.0.1:3010/api/packages/janpeter/generic/proef/1.0.0/p.txt; echo " pakket-upload exit=$?"
python3 /trial/scripts/compose-git-init /srv/scrum4me/forgejo docker-compose.yml runner-config.yaml | head -1
echo "app.ini-sleutels (alleen namen): $(docker exec scrum4me-forgejo sh -c 'grep -o -E "^(LFS_JWT_SECRET|JWT_SECRET|REVERSE_PROXY_TRUSTED_PROXIES|SECRET_KEY|INTERNAL_TOKEN)" /data/gitea/conf/app.ini' | sort | tr '\n' ' ')"
docker exec scrum4me-forgejo grep -n -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini
```

Het compose-bestand in `/srv/scrum4me/forgejo` (de imageregel staat bij de start van deze proef op `15.0.2`):

```yaml
services:
  forgejo:
    image: codeberg.org/forgejo/forgejo:15.0.2
    container_name: scrum4me-forgejo
    restart: unless-stopped
    environment:
      - USER_UID=1000
      - USER_GID=1000
    volumes:
      - forgejo-data:/data
    networks:
      - compose_default
    ports:
      - "127.0.0.1:3010:3000"
  runner:
    image: busybox:1.36
    container_name: scrum4me-forgejo-runner
    command: ["sleep", "infinity"]
    depends_on: [forgejo, dind]
  dind:
    image: busybox:1.36
    container_name: scrum4me-forgejo-dind
    command: ["sleep", "infinity"]
volumes:
  forgejo-data:
    name: forgejo_forgejo-data
    external: true
networks:
  compose_default:
    external: true
```

## 3. Het venster, R3, R4 en een tweede imagewissel

Script (`b159/bNN.sh` = het N-de shellblok van het plan: b01 vaste paden, b03 secretrotatie 2.5b, b04 koud
rollbackpunt 2.7, b05 vers rollbackpunt 4.1, b06 tagwissel 4.2, b08 en b09 de R4-blokken):

```sh
#!/usr/bin/env bash
# als janpeter: 15.0.9-plan — 2.4 t/m 4.5, R3, R4 en een tweede upgrade; commando's letterlijk uit het plan (blokken b159/bNN.sh + prose)
source /trial/b159/b01.sh
BL=/trial/b159
step() { echo; echo "===== $*"; }
ver() { curl -s http://127.0.0.1:3010/api/v1/version; echo; }
wacht() { timeout 600 sh -c 'until curl -sf http://127.0.0.1:3010/api/v1/version >/dev/null; do sleep 2; done'; }
data() { TK=$(docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token --username janpeter --token-name "v$1" --scopes all --raw)
  echo "data: repo $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $TK" http://127.0.0.1:3010/api/v1/repos/janpeter/scrum4me-shared), pakket '$(curl -s -H "Authorization: token $TK" http://127.0.0.1:3010/api/packages/janpeter/generic/proef/1.0.0/p.txt)'"; }
fp() { docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1; }
config_fase() {
  step "2.4 configuratie-rollbackpunt"
  sudo cp -a "$VOL/gitea/conf/app.ini" "$BK/app.ini.pre" && sudo sha256sum "$BK/app.ini.pre" | cut -c1-16
  PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); echo "PRE_CF=${PRE_CF:0:16}…"; git -C "$CD" status --porcelain; echo "(einde git status)"
  PRE_SECRETS=$(docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1)
  step "2.5a trusted proxies (SUBNET=$SUBNET)"
  docker exec -u git scrum4me-forgejo sh -c 'sed -i "s|^REVERSE_PROXY_TRUSTED_PROXIES *=.*|REVERSE_PROXY_TRUSTED_PROXIES = 127.0.0.0/8,::1/128,'"$SUBNET"'|" /data/gitea/conf/app.ini'
  docker exec scrum4me-forgejo grep -n -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini
  docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini
  step "2.5b secretrotatie"; source $BL/b03.sh; echo "exit=$?"
  step "2.6 doctor + flush + stop"
  docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-pre-venster.log" 2>&1; echo "doctor-exit=$?"
  docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m; echo "flush-exit=$?"
  docker stop -t 90 scrum4me-forgejo >/dev/null; docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'
  RD=$(docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind)
  step "2.7 koud rollbackpunt"; source $BL/b04.sh 2>&1 | grep -v -E '^$|^(real|user|sys)'
  step "3.1 opbrengen op 15.0.2"; docker start scrum4me-forgejo >/dev/null; wacht; ver
  docker logs --since 3m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'; echo "(einde loggrep 3.1)"
  step "3.4 secrets"; docker logs --since 3m scrum4me-forgejo 2>&1 | grep -i -E 'jwt|secret'; echo "(einde loggrep 3.4)"; [ "$(fp)" = "$POST_SECRETS" ] && echo "vingerafdruk = POST_SECRETS" || echo "VINGERAFDRUK WIJKT AF"
}
image_fase() {
  step "4.1 stoppen + vers rollbackpunt"; docker stop -t 90 scrum4me-forgejo >/dev/null; source $BL/b05.sh 2>&1 | grep -v -E '^$|^(real|user|sys)'
  step "4.2 tagwissel"; source $BL/b06.sh; echo "exit=$?"
  step "4.3 opbrengen"; docker compose -f "$CF" up -d --no-deps forgejo 2>&1 | tail -1
  docker inspect scrum4me-forgejo --format '{{.Config.Image}}'
  [ "$(docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind)" = "$RD" ] && echo "legacy ID's ongewijzigd, beide running" || echo "LEGACY GEWIJZIGD"
  step "4.4 migraties"; wacht; ver; docker logs --since 5m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'; echo "(einde loggrep 4.4)"
  step "4.5 doctor achteraf"; docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-post.log" 2>&1; echo "exit=$?"
  echo "oude toets (plan-tekst GO 9 sep): $(diff <(grep -v -E '^\[I\]' "$HOME/doctor-pre-venster.log") <(grep -v -E '^\[I\]' "$HOME/doctor-post.log") | grep -c '^[<>]') verschilregels"
  docker exec scrum4me-forgejo forgejo --version | cut -c1-62
  VNOW=$(docker exec scrum4me-forgejo forgejo --version | grep -oE '1[0-9]+\.[0-9]+\.[0-9]+' | head -1); echo "VNOW=$VNOW"
}
step "0.2/0.3/0.11/0.13"
grep -c 'forgejo/forgejo:' "$CF"; grep -n -o -E 'FORGEJO__[A-Za-z0-9_]+' "$CF" | sort -u; echo "(einde FORGEJO__-namen)"
docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini
SUBNET=$(docker network inspect compose_default --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | tr -d ' '); echo "SUBNET=$SUBNET"
if [ -d "$CD/.git" ]; then echo GIT_CF=ja; git -C "$CD" status --porcelain; else echo GIT_CF=nee; fi
step "1.1–1.3"; sudo mkdir -p "$BK" && sudo chmod 0700 "$BK" && sudo chown root:root "$BK"
echo pad-test | sudo tee "$BK/.cptest" >/dev/null && sudo docker cp "$BK/.cptest" scrum4me-postgres:/tmp/.cptest && docker exec scrum4me-postgres rm /tmp/.cptest && sudo rm "$BK/.cptest"; echo "kopiepad exit=$?"
sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"; echo "warme kopie exit=$?"
docker pull -q codeberg.org/forgejo/forgejo:15.0.9 >/dev/null; docker image inspect codeberg.org/forgejo/forgejo:15.0.9 --format '{{index .RepoDigests 0}}' | cut -c1-70
data a
echo; echo "################ CONFIGURATIEFASE, dan R3 (Gate 3 rood gespeeld) ################"; config_fase
step "R3"; docker stop -t 90 scrum4me-forgejo >/dev/null; sudo cp -a "$BK/app.ini.pre" "$VOL/gitea/conf/app.ini"; docker start scrum4me-forgejo >/dev/null; wacht; ver
[ "$(fp)" = "$PRE_SECRETS" ] && echo "vingerafdruk terug op PRE_SECRETS"; docker exec scrum4me-forgejo grep -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini; docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini; data b
echo; echo "################ CONFIGURATIEFASE opnieuw, dan IMAGE ################"; config_fase; data c; image_fase; data d
echo; echo "################ R4 ################"
docker stop -t 90 scrum4me-forgejo >/dev/null
step "R4.2"; source $BL/b08.sh; echo "exit=$?"
step "R4.3"; source $BL/b09.sh 2>&1 | tr '\n' ' '; echo
step "R4.4"; sudo rsync -aHAX --numeric-ids --delete "$BK/data/" "$VOL/"; echo "exit=$?"
step "R4.5"; sudo sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.9$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF"; [ "$(sha256sum "$CF" | cut -d' ' -f1)" = "$PRE_CF" ] && echo "COMPOSE TERUG OP PRE_CF" || { echo "COMPOSE WIJKT AF VAN PRE_CF — STOP, JP"; false; }
docker compose -f "$CF" up -d --no-deps forgejo 2>&1 | tail -1
step "R4.6"; wacht; ver; docker exec -u git scrum4me-forgejo forgejo doctor check --all >/dev/null 2>&1; echo "doctor-exit=$?"; [ "$(fp)" = "$POST_SECRETS" ] && echo "vingerafdruk = POST_SECRETS (rotatie behouden)"; data e; git -C "$CD" status --porcelain; echo "(einde git status)"
echo; echo "################ IMAGE opnieuw, dan 6.2 ################"; image_fase; data f
step "6.2 hostregel-commit"; docker compose -f "$CF" config -q; echo "config-exit=$?"; git -C "$CD" add docker-compose.yml; git -C "$CD" diff --cached | grep '^[+-] '
git -C "$CD" commit -q -m "forgejo 15.0.2 -> 15.0.9 (onderhoudsvenster proef)"; echo "commit-exit=$?"; git -C "$CD" status --porcelain; echo "(einde git status)"
step "databases"; docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -Atc "select datname from pg_database"' | tr '\n' ' '; echo
```

Uitvoer:

```text

===== 0.2/0.3/0.11/0.13
1
(einde FORGEJO__-namen)
git:git 600
SUBNET=172.19.0.0/16
GIT_CF=ja

===== 1.1–1.3
kopiepad exit=0
warme kopie exit=0
codeberg.org/forgejo/forgejo@sha256:91a5310c86934339e16bd06b6078aada83
data: repo 200, pakket 'pakketinhoud'

################ CONFIGURATIEFASE, dan R3 (Gate 3 rood gespeeld) ################

===== 2.4 configuratie-rollbackpunt
4633c06acc767b42
PRE_CF=00c65400d0d7857e…
(einde git status)

===== 2.5a trusted proxies (SUBNET=172.19.0.0/16)
57:REVERSE_PROXY_TRUSTED_PROXIES = 127.0.0.0/8,::1/128,172.19.0.0/16
git:git 600

===== 2.5b secretrotatie
ROTATIE OK
exit=0

===== 2.6 doctor + flush + stop
doctor-exit=0
Flushed
flush-exit=0
Exited (0) Less than a second ago

===== 2.7 koud rollbackpunt
4bfa852b6286abe92e7996da847287b265c4c374354621597632e2fb67932bc6  /srv/backups/manual/forgejo-pre-15.0.9/forgejo-pre-15.0.9.dump
402400
KOUD ROLLBACKPUNT OK

===== 3.1 opbrengen op 15.0.2
{"version":"15.0.2+gitea-1.22.0"}

(einde loggrep 3.1)

===== 3.4 secrets
(einde loggrep 3.4)
vingerafdruk = POST_SECRETS

===== R3
{"version":"15.0.2+gitea-1.22.0"}

vingerafdruk terug op PRE_SECRETS
REVERSE_PROXY_TRUSTED_PROXIES = *
git:git 600
data: repo 200, pakket 'pakketinhoud'

################ CONFIGURATIEFASE opnieuw, dan IMAGE ################

===== 2.4 configuratie-rollbackpunt
4633c06acc767b42
PRE_CF=00c65400d0d7857e…
(einde git status)

===== 2.5a trusted proxies (SUBNET=172.19.0.0/16)
57:REVERSE_PROXY_TRUSTED_PROXIES = 127.0.0.0/8,::1/128,172.19.0.0/16
git:git 600

===== 2.5b secretrotatie
ROTATIE OK
exit=0

===== 2.6 doctor + flush + stop
doctor-exit=0
Flushed
flush-exit=0
Exited (0) Less than a second ago

===== 2.7 koud rollbackpunt
4ac8f721587a30a7479e5bb1253282dd17c4a5da450ce53ea5895fb5e62c2cf0  /srv/backups/manual/forgejo-pre-15.0.9/forgejo-pre-15.0.9.dump
402540
KOUD ROLLBACKPUNT OK

===== 3.1 opbrengen op 15.0.2
{"version":"15.0.2+gitea-1.22.0"}

(einde loggrep 3.1)

===== 3.4 secrets
(einde loggrep 3.4)
vingerafdruk = POST_SECRETS
data: repo 200, pakket 'pakketinhoud'

===== 4.1 stoppen + vers rollbackpunt
9a3471bc817fae2eee2e0a174fccac3666b6c0448cf3a8394a8c08d9e38cb741  /srv/backups/manual/forgejo-pre-15.0.9/forgejo-pre-image.dump
VERS ROLLBACKPUNT OK

===== 4.2 tagwissel
TAGWISSEL OK (alleen de forge-imageregel gewijzigd)
exit=0

===== 4.3 opbrengen
 Container scrum4me-forgejo Started 
codeberg.org/forgejo/forgejo:15.0.9
legacy ID's ongewijzigd, beide running

===== 4.4 migraties
{"version":"15.0.9+gitea-1.22.0"}

(einde loggrep 4.4)

===== 4.5 doctor achteraf
exit=0
oude toets (plan-tekst GO 9 sep): 387 verschilregels
forgejo version 15.0.9+gitea-1.22.0 (release name 15.0.9) buil
VNOW=15.0.9
data: repo 200, pakket 'pakketinhoud'

################ R4 ################

===== R4.2
exit=0

===== R4.3
ALTER DATABASE postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo 

===== R4.4
exit=0

===== R4.5
COMPOSE TERUG OP PRE_CF
 Container scrum4me-forgejo Started 

===== R4.6
{"version":"15.0.2+gitea-1.22.0"}

doctor-exit=0
vingerafdruk = POST_SECRETS (rotatie behouden)
data: repo 200, pakket 'pakketinhoud'
(einde git status)

################ IMAGE opnieuw, dan 6.2 ################

===== 4.1 stoppen + vers rollbackpunt
7635279bb81b0cf037d2b2ef09124e666964775358d956d506aa5bc4e2b2b467  /srv/backups/manual/forgejo-pre-15.0.9/forgejo-pre-image.dump
VERS ROLLBACKPUNT OK

===== 4.2 tagwissel
TAGWISSEL OK (alleen de forge-imageregel gewijzigd)
exit=0

===== 4.3 opbrengen
 Container scrum4me-forgejo Started 
codeberg.org/forgejo/forgejo:15.0.9
legacy ID's ongewijzigd, beide running

===== 4.4 migraties
{"version":"15.0.9+gitea-1.22.0"}

(einde loggrep 4.4)

===== 4.5 doctor achteraf
exit=0
oude toets (plan-tekst GO 9 sep): 388 verschilregels
forgejo version 15.0.9+gitea-1.22.0 (release name 15.0.9) buil
VNOW=15.0.9
data: repo 200, pakket 'pakketinhoud'

===== 6.2 hostregel-commit
config-exit=0
-    image: codeberg.org/forgejo/forgejo:15.0.2
+    image: codeberg.org/forgejo/forgejo:15.0.9
commit-exit=0
(einde git status)

===== databases
postgres scrum4me template1 template0 forgejo_failed_15_0_9 forgejo 
```

Lezing:

- **Configuratiefase:** 2.5a zet precies één regel, eigenaar en mode van `app.ini` blijven `git:git 600`;
  2.5b geeft `ROTATIE OK`; 15.0.2 start met de nieuwe secrets zonder `[E]`/`[F]`/panic en zonder jwt- of
  secretmelding in het log; de vingerafdruk is `POST_SECRETS`.
- **R3:** na het terugzetten van `app.ini.pre` draait 15.0.2 weer, de vingerafdruk is terug op
  `PRE_SECRETS`, de trusted-proxiesregel is weer `*`, eigenaar en mode zijn behouden, de data is er.
- **Imagewissel:** `VERS ROLLBACKPUNT OK`, `TAGWISSEL OK`, de forge draait `15.0.9+gitea-1.22.0`, de
  legacy-stubs houden hun container-ID en blijven `running`.
- **R4:** de gemigreerde database wordt `forgejo_failed_15_0_9`, de verse dump wordt hersteld, het volume
  gaat terug, `$CF` is weer byte-gelijk aan `PRE_CF`, 15.0.2 draait met de data en met de geroteerde
  secrets (het verse paar is van ná 2.5), en de werkboom van de compose-map is schoon.
- **6.2:** na de tweede imagewissel slaagt `docker compose config -q`, bevat de gestagede diff alleen de
  imageregel, slaagt de commit door de hook en is de werkboom schoon.
- **Defect:** de regel "oude toets" laat zien dat de doctor-vergelijking uit de plantekst van 9 september
  387–388 verschilregels geeft tussen twee gezonde logs. Zie §4.

## 4. De doctor-vergelijking (D10)

De functies zijn uit het planbestand geëxtraheerd (byte-gelijk aan het blok "Hulpfuncties") en gedraaid in
`ubuntu:24.04` (GNU sed 4.9, mawk, bash 5.2) op de echte doctor-logs uit deze proef en uit de proef van het
17.0-plan.

```sh
doctorsamenvatting() {   # per check: naam<TAB>OK|ERROR, plus elke [W]/[E]-regel van die check — zonder logregels, kleurcodes en volgnummers
  grep -v -E '^[0-9]{4}/[0-9]{2}/[0-9]{2} ' "$1" | sed -E 's/\x1b\[[0-9;]*m//g' \
    | awk '/^\[[0-9]+\] /{sub(/^\[[0-9]+\] /,""); n=$0; next} /^ - \[(W|E)\]/{print n "\t" $0; next} /^(OK|ERROR)$/{print n "\t" $0}'
}
doctornieuw() {          # bevindingen die in $2 staan en niet in $1: een check die ERROR werd, of een nieuwe [W]/[E]-regel
  comm -13 <(doctorsamenvatting "$1" | LC_ALL=C sort) <(doctorsamenvatting "$2" | LC_ALL=C sort) | grep -v 'OK$'
}
doctortoets() {          # $1 = log vóór, $2 = log na; exit 0 alleen als $2 echte checks bevat en geen nieuwe bevindingen heeft
  local n nieuw
  n=$(doctorsamenvatting "$2" | grep -c -E '(OK|ERROR)$')
  nieuw=$(doctornieuw "$1" "$2")
  if [ "$n" -gt 0 ] && [ -z "$nieuw" ]; then echo "DOCTOR OK ($n checks, geen nieuwe bevindingen)"; return 0; fi
  printf '%s\n' "$nieuw"; echo "DOCTOR ROOD ($n checks gelezen; nieuwe bevindingen staan hierboven, of het log is leeg of onleesbaar) — beoordelen, onverklaard = STOP"; return 1
}

# --- proefscript ---
#!/usr/bin/env bash
# Proef van doctorsamenvatting/doctornieuw/doctortoets met echte doctor-logs uit de wegwerpomgeving
source /d/functies.sh
echo "awk: $(readlink -f "$(command -v awk)") | $(sed --version | head -1) | bash $BASH_VERSION"
geval() { echo; echo "=== $1"; shift; doctortoets "$@" 2>&1 | cut -c1-160; echo "exit=${PIPESTATUS[0]}"; }
echo; echo "ruwe diff uit de oude plantekst, 15.0.2 → 15.0.9: $(diff <(grep -v -E '^\[I\]' /d/pre-15.0.2.log) <(grep -v -E '^\[I\]' /d/post-15.0.9.log) | grep -c '^[<>]') verschilregels; 15.0.9 → 17.0-test: $(diff <(grep -v -E '^\[I\]' /d/pre-15.0.9.log) <(grep -v -E '^\[I\]' /d/post-17.0-test.log) | grep -c '^[<>]')"
echo "baseline 15.0.2 (niet-OK): $(doctorsamenvatting /d/pre-15.0.2.log | grep -v 'OK$' | wc -l) regels; baseline 15.0.9 (niet-OK): $(doctorsamenvatting /d/pre-15.0.9.log | grep -v 'OK$' | tr '\t' ' ')"
echo "verdwenen 15.0.9 → 17.0-test: $(comm -23 <(doctorsamenvatting /d/pre-15.0.9.log | LC_ALL=C sort) <(doctorsamenvatting /d/post-17.0-test.log | LC_ALL=C sort) | tr '\t' ' ')"
geval "1. echt: 15.0.2 → 15.0.9"            /d/pre-15.0.2.log /d/post-15.0.9.log
geval "2. echt: 15.0.9 → 17.0-test"         /d/pre-15.0.9.log /d/post-17.0-test.log
awk 'BEGIN{c=0} /^\[3\] /{print; print " - [E] kapot"; c=1; next} c==1 && /^OK$/{print "ERROR"; c=0; next} {print}' /d/post-15.0.9.log > /tmp/bad-a.log
geval "3. injectie: OK-check wordt ERROR"    /d/pre-15.0.2.log /tmp/bad-a.log
awk '/^\[4\] /{print; print " - [W] nieuw"; next} {print}' /d/post-15.0.9.log > /tmp/bad-b.log
geval "4. injectie: alleen een nieuwe [W]"   /d/pre-15.0.2.log /tmp/bad-b.log
: > /tmp/leeg.log
geval "5. post-log leeg"                     /d/pre-15.0.2.log /tmp/leeg.log
geval "6. post-log ontbreekt"                /d/pre-15.0.2.log /tmp/bestaat-niet.log
geval "7. bestaande ERROR blijft ERROR (baseline)" /d/pre-15.0.9.log /d/pre-15.0.9.log
```

Uitvoer:

```text
awk: /usr/bin/mawk | sed (GNU sed) 4.9 | bash 5.2.21(1)-release

ruwe diff uit de oude plantekst, 15.0.2 → 15.0.9: 388 verschilregels; 15.0.9 → 17.0-test: 385
baseline 15.0.2 (niet-OK): 4 regels; baseline 15.0.9 (niet-OK): Garbage collect LFS ERROR
verdwenen 15.0.9 → 17.0-test: Check if hook files are up-to-date and executable OK

=== 1. echt: 15.0.2 → 15.0.9
DOCTOR OK (28 checks, geen nieuwe bevindingen)
exit=0

=== 2. echt: 15.0.9 → 17.0-test
DOCTOR OK (27 checks, geen nieuwe bevindingen)
exit=0

=== 3. injectie: OK-check wordt ERROR
Check if there are orphaned archives in storage	 - [E] kapot
Check if there are orphaned archives in storage	ERROR
DOCTOR ROOD (28 checks gelezen; nieuwe bevindingen staan hierboven, of het log is leeg of onleesbaar) — beoordelen, onverklaard = STOP
exit=1

=== 4. injectie: alleen een nieuwe [W]
Check if there are orphaned attachments in storage	 - [W] nieuw
DOCTOR ROOD (28 checks gelezen; nieuwe bevindingen staan hierboven, of het log is leeg of onleesbaar) — beoordelen, onverklaard = STOP
exit=1

=== 5. post-log leeg

DOCTOR ROOD (0 checks gelezen; nieuwe bevindingen staan hierboven, of het log is leeg of onleesbaar) — beoordelen, onverklaard = STOP
exit=1

=== 6. post-log ontbreekt
grep: /tmp/bestaat-niet.log: No such file or directory
grep: /tmp/bestaat-niet.log: No such file or directory

DOCTOR ROOD (0 checks gelezen; nieuwe bevindingen staan hierboven, of het log is leeg of onleesbaar) — beoordelen, onverklaard = STOP
exit=1

=== 7. bestaande ERROR blijft ERROR (baseline)
DOCTOR OK (28 checks, geen nieuwe bevindingen)
exit=0
```

Lezing: de twee echte paren geven `DOCTOR OK`; een check die `ERROR` wordt en een losse nieuwe `[W]`-regel
geven `DOCTOR ROOD` met de betreffende regels; een leeg en een ontbrekend log geven `DOCTOR ROOD` (0 checks
gelezen); een `ERROR` die al in de baseline stond, telt niet als nieuw. De "baseline 15.0.9: Garbage collect
LFS ERROR" komt uit de proefinstance van het 17.0-plan, waar LFS niet was aangezet; het toont dat doctor
exit 0 geeft terwijl een check `ERROR` meldt, en dat zo'n regel in 0.4 als baseline beoordeeld moet worden.
