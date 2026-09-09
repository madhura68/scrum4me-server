# Implementatieplan — Forgejo 15.0.2 → 15.0.7 op `scrum4me-server`

> **Voor uitvoerders:** dit is een **operator-gedreven onderhoudsactie** op een productiehost, geen code-implementatie. Voer fase voor fase uit met de gate ná elke fase; bij een rode gate: **STOP** (stoppen, journal/uitvoer vastleggen, JP melden — niet forceren, niet de gate versoepelen). Elke fase heeft een terugweg (zie Rollback). Commando's zonder host-label draaien **op `scrum4me-server`** als `janpeter` (docker-groep, `sudo` waar aangegeven); `[max2]`-stappen draaien op `max2`; `[mac]`-stappen op de mac met persoonlijk `FORGEJO_TOKEN`; `[JP]`-stappen zijn JP-only (beheerinterface, besluiten).

**Doel:** de live forge `scrum4me-forgejo` van `codeberg.org/forgejo/forgejo:15.0.2` naar `:15.0.7` (LTS) brengen, in hetzelfde venster `[security] REVERSE_PROXY_TRUSTED_PROXIES` expliciet op het proxynetwerk zetten en de twee op 9 september 2026 gelekte secrets (`[oauth2] JWT_SECRET`, `[server] LFS_JWT_SECRET`) roteren — met een vóór de wijziging bewezen rollbackpunt en met de runnerpool netjes gedraind en hersteld.

**Architectuur:** één onderhoudsvenster (doel ≤ 30 min downtime), twee losse wijzigingsstappen met elk een eigen gate en terugweg: eerst de configuratie op 15.0.2 (herstart → gate), dan de image naar 15.0.7 (herstart → gate). Backup = `pg_dump` van database `forgejo` uit de gedeelde `scrum4me-postgres` + rsync-kopie van volume `forgejo_forgejo-data`, koud genomen. Runnerpool: legacy runner gepauzeerd, `max2`-controller netjes gestopt (runbook §7), na afloop trust-verdict handmatig vernieuwd en controller gestart (runbook §5), smoke (runbook §6).

**Tech stack:** Ubuntu 26.04, Docker Engine 29.7.2, Docker Compose 5.1.4 (compose-project `forgejo`), Forgejo rootful image, Postgres 17 (`scrum4me-postgres`, gedeeld met de scrum4me-app), Caddy 2, systemd-cyclecontroller op `max2` (bundel `forgejo-runner/`).

**Spec / grondslag:** [forgejo-upgrade-onderzoek-2026-09.md](forgejo-upgrade-onderzoek-2026-09.md) (§1 gemeten uitgangssituatie, §2 wat een upgrade hier betekent, §3 waarom 15.0.7 en niet 16, §6 secretlek); [Forgejo upgrade-guide](https://forgejo.org/docs/latest/admin/upgrade/); `migratieontwerp.md` §7.7/§7.9 (control-plane-onderhoud, drain, nulbewijs) en §9; `evidence/stap-d/bring-up-runbook.md` §5–§7 (controller starten, smoke, nette stop); `implementatieplan-stap-g.md` B3/C3 (het compose-project bevat de live forge); `CLAUDE.md` hardstops.

---

## Global Constraints (bindend, uit `CLAUDE.md`, het migratieontwerp en het stap-G-plan)

- **Geen secrets in Git.** Geen tokenwaarden, JWT-secrets, wachtwoorden, UUID's van runners of `app.ini`-kopieën in evidence of docs. De backupmap op de host is root-only (`0700`). `secret-scan.sh` moet exit 0 geven vóór elke commit.
- **Compose-project `forgejo` uitsluitend service-gebonden benaderen.** Nooit `docker compose down`, `up -d` zonder servicenaam, `--remove-orphans`, `prune` of `-v` in dit project: het bevat naast de forge ook de legacy runner en DinD (stap-G-plan B3/C3). Toegestaan: `docker compose -f "$CF" up -d --no-deps forgejo`, `docker stop/start/restart scrum4me-forgejo`.
- **Productiecontext (`CLAUDE.md`).** Host-Dockerdaemon niet herstarten, `/etc/docker/daemon.json` niet wijzigen, geen hostbrede prune. `scrum4me-postgres` wordt **niet** herstart of gewijzigd; het plan raakt die container alleen met `pg_dump`/`pg_restore` van database `forgejo`.
- **Backup vóór wijziging, bewezen restorepad.** Een major- of patchupgrade van Forgejo migreert de database automatisch en onomkeerbaar (upgrade-guide); Gate 2 (koud rollbackpunt) is voorwaarde voor elke daaropvolgende wijziging.
- **Eén variabele per gate.** Configuratie (trusted proxies + secrets) krijgt een eigen herstart en gate op 15.0.2 vóór de image wisselt, zodat een falende start eenduidig toe te schrijven is.
- **Control-plane-onderhoud = pool drainen.** Vóór de forge stopt: legacy runner gepauzeerd en `max2`-controller netjes gestopt met Forgejo-side nulbewijs (§7.9). De as-built controller kan géén maintenance-record laden (`cycle_runtime.py`/`cycle_adapters.py`/`controller.toml.example` kennen geen laadpad; `Controller.__init__` zet `self.maintenance = None`), dus een gestopte controller is hier de enige manier om een vals availability-incident te vermijden. Stap H loopt nog niet; er is geen stabiliteitsklok die reset.
- **Niet gelijktijdig met ander werk op de hosts** (stap F/G, reboots, bundelwijzigingen). Eén wijziging tegelijk; `git status --porcelain` van de uitvoerder toont alleen eigen evidence.
- **Meten, niet aannemen.** Elke waarde die hieronder "gemeten door JP op 9 september 2026" heet, wordt in Fase 0 opnieuw gemeten; wijkt zij af, dan is dat een STOP tot het plan is bijgewerkt.
- **Forge = Forgejo.** Evidence en docwijzigingen via een branch + PR op `git.jp-visser.nl` (API of `tea`), nooit via GitHub-tooling; uitrol nooit via Forgejo Actions.

Vaste paden in dit plan (op `scrum4me-server`):

```sh
CF=/srv/scrum4me/forgejo/docker-compose.yml                 # compose-project "forgejo" (mapnaam)
VOL=/var/lib/docker/volumes/forgejo_forgejo-data/_data      # forge-datavolume (/data in de container)
BK=/srv/backups/manual/forgejo-pre-15.0.7                   # koud rollbackpunt, root-only
```

---

## Fase 0 — read-only metingen (dagen vóór het venster, ~20 min, geen impact)

Leg alle uitvoer vast onder `evidence/forgejo-15.0.7/fase0/` (zie Fase 6 voor de redactieregels: geen secrets, geen UUID's).

- **0.1 Versie en compose-project.** `docker exec scrum4me-forgejo forgejo --version` → verwacht `15.0.2+gitea-1.22.0`. `docker compose -f "$CF" config --services` → bevat `forgejo`, `runner`, `dind`. `docker compose ls --filter name=forgejo` → project `forgejo` running.
- **0.2 Compose-regels (gemeten door JP 9 sep 2026: regel 22 image, 44–48 ports, 58 runner-image, 61 `depends_on: [forgejo, dind]`, 101 dind-image).** `grep -n -E 'image:|depends_on|ports:|container_name' "$CF"` → exact één regel `image: codeberg.org/forgejo/forgejo:15.0.2`; de forge-service heeft géén `depends_on`; poorten `127.0.0.1:3010:3000` en de SSH-regel op het Tailscale-IP. Kijk of de forge-service `FORGEJO__`-omgevingsvariabelen zet — **namen alleen**: `grep -n -o -E 'FORGEJO__[A-Za-z0-9_]+' "$CF" | sort -u`. Staat `FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES` erin, dan geldt in 2.5(a) de **compose-tak**; anders de **app.ini-tak**. Ownership van het bestand: `stat -c '%U:%G %a' "$CF"`.
- **0.3 Containergebruiker en configpad.** `docker exec scrum4me-forgejo id git` → bestaat (rootful image draait Forgejo als `git`, UID `USER_UID`). `docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini` → noteer eigenaar en mode; 2.5 draait als die eigenaar (`-u git` als `git` eigenaar is, anders `-u root`) en herstelt daarna eigenaar en mode met `chown`/`chmod` naar exact deze waarden, omdat `sed -i` het bestand opnieuw aanmaakt. `docker inspect scrum4me-forgejo --format '{{.HostConfig.RestartPolicy.Name}} {{.Config.Image}} {{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1` → restartbeleid, image, **env-namen** (waarden worden bewust niet getoond).
- **0.4 Doctor vooraf.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-pre.log" 2>&1; echo "exit=$?"` → exit 0; noteer waarschuwingen. Een `[E]`-regel is een STOP (eerst begrijpen, dan pas upgraden).
- **0.5 Omvang en ruimte.** `sudo du -sb "$VOL"`; `PGU=$(docker exec scrum4me-postgres sh -c 'printf %s "${POSTGRES_USER:-postgres}"')` (alleen de rolnaam); `docker exec scrum4me-postgres psql -U "$PGU" -d postgres -Atc "select pg_database_size('forgejo')"`; `sudo mkdir -p /srv/backups/manual && df -B1 --output=avail /srv/backups | tail -1`. Voorwaarde: vrij ≥ 2 × (volume + database).
- **0.6 Gereedschap.** `command -v rsync` (vereist voor Fase 1/2; ontbreekt het → JP beslist over `sudo apt-get install rsync` vóór Fase 1, of het plan wordt herzien — er is bewust geen tar-fallback, omdat die de volledige kopietijd in het venster legt). `docker exec scrum4me-postgres pg_restore --version`.
- **0.7 Timers en tijdzone.** `systemctl list-timers --all --no-pager | grep -i -E 'backup|restic|prune'` (nachtelijke backup: geen overlap met het venster). `[max2]` `systemctl list-timers forgejo-runner-trust.timer --no-pager` en `timedatectl | grep 'Time zone'` → het venster valt buiten 00:00–00:06, 06:00–06:06, 12:00–12:06 en 18:00–18:06 lokale tijd van `max2` (`OnCalendar` + `RandomizedDelaySec=300` in `forgejo-runner-trust.timer`).
- **0.8 Routerlog aanwezig?** `docker logs --since 30m scrum4me-forgejo 2>&1 | grep -c 'router: completed'` → > 0 betekent dat Gate 3 het client-IP via het routerlog kan bewijzen; 0 betekent dat Gate 3 terugvalt op de configregel + foutloze start (leg vast welke).
- **0.9 Runnerrecords vooraf.** `[mac]` `FORGEJO_TOKEN=… bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-15.0.7/voor` → verwacht twee records (`scrum4me-srv-runner` id 3 en `max2-forgejo-runner-02`), beide `idle`, versie `v12.10.1`. **Commit alleen de geredigeerde samenvatting** (Fase 6): `cut -f1,2,4,5,6,7,10 runners-summary.tsv` (zonder de `uuid`-kolom).
- **0.10 OAuth2-afhankelijkheid.** `[JP]` Site Administration → Applications: zijn er OAuth2-applicaties die Forgejo als provider gebruiken? Noteer ja/nee en welke; hun tokens vervallen bij de secretrotatie (2.5b).
- **0.11 Caddy-netwerk.** `docker inspect scrum4me-forgejo --format '{{range $n,$v := .NetworkSettings.Networks}}{{$n}}={{$v.IPAddress}} {{end}}'` en hetzelfde voor `scrum4me-caddy` → het gedeelde netwerk (compose-commentaar: `compose_default`). `docker network inspect NETWERK --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'` met `NETWERK` = de gedeelde netwerknaam uit de vorige regel → `SUBNET` (bv. `172.18.0.0/16`). Dit is de waarde voor 2.5(a).

**Gate 0:** versie 15.0.2 bevestigd; alle regelnummers en de DB-configuratie komen overeen met §1 van het onderzoek; doctor zonder `[E]`; ruimte ≥ 2×; rsync + pg_restore aanwezig; venster gekozen buiten de timerslagen; tak voor 2.5(a) bekend; routerlog-uitkomst bekend; beide runnerrecords `idle`; `SUBNET` bekend. Anders STOP.

---

## Fase 1 — voorbereiden zonder downtime (uren tot een dag vóór het venster)

- **1.1 Backupmap.** `sudo mkdir -p "$BK" && sudo chmod 0700 "$BK" && sudo chown root:root "$BK"`.
- **1.2 Warme kopie van het volume** (Forgejo draait; de kopie is nog niet consistent, maar draagt het gros van de bytes zodat de koude delta in 2.7 kort is): `time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"` → exit 0; noteer duur en `sudo du -sb "$BK/data"`.
- **1.3 Image vooraf ophalen** (geen herstart): `docker pull codeberg.org/forgejo/forgejo:15.0.7 && docker image inspect codeberg.org/forgejo/forgejo:15.0.7 --format '{{index .RepoDigests 0}}'` → digest vastleggen.
- **1.4 Venster vastleggen.** `[JP]` datum/tijd (UTC én lokaal), verwachte duur ≤ 30 min, buiten 0.7-slagen en de nachtelijke backup; aankondiging aan wie de forge gebruikt. Geen andere hostwijzigingen in dat venster.
- **1.5 Rollbacktijd schatten.** Uit 0.5 en 1.2: koude delta (2.7) hoort in minuten te passen; de restore (Rollback R4: `pg_restore` + rsync terug) hoort binnen het resterende venster te passen. Past het niet, dan verlengt JP het venster vóóraf; het wordt niet tijdens het venster opgerekt.

**Gate 1:** `$BK/data` gevuld en rsync exit 0; image 15.0.7 lokaal met vastgelegde digest; venster gepland en aangekondigd; rollbacktijd geschat en passend.

---

## Fase 2 — venster openen: drainen, rollbackpunt (T+0 … ~T+10)

Noteer `T0=$(date -u +%FT%TZ)` bij de eerste handeling.

- **2.1 [JP] Legacy runner pauzeren.** Site Administration → Actions → Runners → `scrum4me-srv-runner` (id 3) → Pause (zelfde handeling als in stap E, runbook §6). Hij mag geen nieuwe job meer aannemen; een lopende job laten eindigen.
- **2.2 [mac] Nulbewijs.** Twee metingen ≥ 10 s uiteen (`assignment_nulbewijs`-semantiek, §7.9): `bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-15.0.7/nul1; sleep 15; bash … --out /tmp/fj-15.0.7/nul2` → in beide is `max2-forgejo-runner-02` `idle` en is `scrum4me-srv-runner` niet `active`. Is een van beide `active`: wachten en herhalen (max `T_requeue` = 10 min), niet stoppen.
- **2.3 [max2] Controller netjes stoppen (runbook §7).** `sudo systemctl stop forgejo-runner-cycle.service; sudo systemctl show forgejo-runner-cycle.service -p ExecMainStatus -p Result` → `ExecMainStatus=0`, `Result=success`; `cd /opt/forgejo-runner && docker compose ps --profile cycle runner` → leeg; `ls /opt/forgejo-runner/state/cycle-op.marker` → bestaat niet. DinD blijft draaien. `[mac]` derde capture → `max2-forgejo-runner-02` `offline`.
- **2.4 Configuratie-rollbackpunt.** `sudo cp -a "$VOL/gitea/conf/app.ini" "$BK/app.ini.pre" && sudo cp -a "$CF" "$BK/docker-compose.yml.pre" && sudo sha256sum "$BK/app.ini.pre" "$BK/docker-compose.yml.pre"` → hashes in evidence (alleen hashes). Vingerafdruk van de te roteren regels, zonder waarden: `PRE_SECRETS=$(docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1)`.
- **2.5 Configuratiewijzigingen op de draaiende 15.0.2** (effectief bij de eerstvolgende herstart; het rollbackpunt van 2.4 is de terugweg). Hier en niet ná de stop, omdat `forgejo generate secret` het binary in de draaiende container gebruikt en de waarde zo de container nooit verlaat.
  - **(a) Trusted proxies.** *app.ini-tak:* `docker exec -u git scrum4me-forgejo sh -c 'sed -i "s|^REVERSE_PROXY_TRUSTED_PROXIES *=.*|REVERSE_PROXY_TRUSTED_PROXIES = 127.0.0.0/8,::1/128,SUBNET|" /data/gitea/conf/app.ini'` met `SUBNET` uit 0.11 ingevuld; verificatie `docker exec scrum4me-forgejo grep -n -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini` → precies één regel, nieuwe waarde. *Compose-tak:* dezelfde waarde in de `FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES`-regel van `$CF` (`sudo sed -i`), verificatie met `grep -n` op die regel; de entrypoint schrijft env naar `app.ini` bij elke start, dus alleen de compose-regel is dan leidend.
  - **(b) Secretrotatie (besluit JP, onderzoek §6).** Waarden verlaten de container niet en komen niet in argv van de host:
    ```sh
    docker exec -u git scrum4me-forgejo sh -c 'v=$(forgejo generate secret JWT_SECRET) && sed -i "s|^JWT_SECRET *=.*|JWT_SECRET = $v|" /data/gitea/conf/app.ini'
    docker exec -u git scrum4me-forgejo sh -c 'v=$(forgejo generate secret LFS_JWT_SECRET) && sed -i "s|^LFS_JWT_SECRET *=.*|LFS_JWT_SECRET = $v|" /data/gitea/conf/app.ini'
    POST_SECRETS=$(docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1)
    [ "$PRE_SECRETS" != "$POST_SECRETS" ] && docker exec scrum4me-forgejo sh -c 'grep -c -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini'   # verwacht: 2
    ```
    `^JWT_SECRET` matcht alleen de `[oauth2]`-sleutel (de `[server]`-sleutel begint met `LFS_`); JP's grep van 9 september toonde precies die twee sleutels. Base64url bevat geen `|`, `&` of `/`, dus de sed-vervanging is veilig. Slaat JP de rotatie over: leg dat besluit vast in `venster.md` en sla (b) over; de rest van het plan verandert niet.
- **2.6 Doctor + queues, dan stoppen.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-pre-venster.log" 2>&1`; `docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m` → exit 0. Dan `docker stop -t 90 scrum4me-forgejo` en `docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'` → `Exited (…)`. `TSTOP=$(date -u +%FT%TZ)`. Legacy runner- en DinD-containers blijven ongemoeid: `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → beide `running`; bewaar de ID's als `RID`/`DID` voor Gate 4.
- **2.7 Koud rollbackpunt.**
  ```sh
  docker exec scrum4me-postgres sh -c 'pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -f /tmp/forgejo-pre-15.0.7.dump forgejo' && \
  docker exec scrum4me-postgres pg_restore --list /tmp/forgejo-pre-15.0.7.dump | wc -l && \
  docker cp scrum4me-postgres:/tmp/forgejo-pre-15.0.7.dump /tmp/forgejo-pre-15.0.7.dump && \
  sudo mv /tmp/forgejo-pre-15.0.7.dump "$BK/" && sudo chmod 0600 "$BK/forgejo-pre-15.0.7.dump" && \
  docker exec scrum4me-postgres rm /tmp/forgejo-pre-15.0.7.dump && \
  sudo sha256sum "$BK/forgejo-pre-15.0.7.dump" && sudo stat -c '%s' "$BK/forgejo-pre-15.0.7.dump"
  time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"    # koude delta; exit 0
  ```
  De `pg_restore --list`-telling moet > 0 zijn; lokale socketverbindingen in het officiële Postgres-image zijn `trust`, daarom volstaat de rolnaam.

**Gate 2 (rollbackpunt bewezen):** dump aanwezig, `--list` > 0, sha256 en grootte vastgelegd; koude rsync exit 0; `app.ini.pre` en `docker-compose.yml.pre` met hashes; forge gestopt, legacy containers `running` met ongewijzigde ID's; controller op `max2` `Result=success`. Anders STOP en Rollback R2 (forge gewoon weer starten op 15.0.2 met `app.ini.pre` teruggezet).

---

## Fase 3 — configuratie-gate op 15.0.2 (~T+10 … T+15)

- **3.1 Starten op de oude image.** `docker start scrum4me-forgejo`; wacht tot `curl -s http://127.0.0.1:3010/api/v1/version` `"15.0.2+gitea-1.22.0"` geeft (poort uit 0.2). `docker logs --since 3m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'` → leeg.
- **3.2 Via Caddy.** `[mac]` `curl -s https://git.jp-visser.nl/api/v1/version` → `15.0.2+gitea-1.22.0`. `[JP]` inloggen op de webinterface, één repository openen (websessies overleven de rotatie: die hangen aan `SECRET_KEY`, niet aan `JWT_SECRET`).
- **3.3 Trusted proxies effectief.** *Routerlog aanwezig (0.8):* direct na 3.2 `docker logs --since 2m scrum4me-forgejo 2>&1 | grep 'api/v1/version' | tail -3` → het gelogde client-IP is het IP waarmee de mac bij Caddy binnenkomt (`[mac]` `curl -s https://ifconfig.me`, of het Tailscale-IP als die route via de tailnet loopt), **niet** het container-IP van Caddy uit 0.11. *Routerlog afwezig:* `docker exec scrum4me-forgejo grep -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini` toont de nieuwe waarde en de start was foutloos (3.1); leg vast dat het IP-bewijs niet beschikbaar was.
- **3.4 Secrets.** `docker logs --since 3m scrum4me-forgejo 2>&1 | grep -i -E 'jwt|secret'` → leeg (geen decodeerfout). Vingerafdruk gelijk aan `POST_SECRETS` uit 2.5(b).

**Gate 3:** 15.0.2 antwoordt op 3010 én via Caddy; login werkt; trusted-proxies-bewijs volgens de 0.8-tak; geen `[E]`/jwt-fouten. Anders **Rollback R3** (configuratie terug) — het venster gaat dan zonder image-upgrade dicht via Fase 5, en JP krijgt de bevinding.

---

## Fase 4 — image naar 15.0.7 (~T+15 … T+22)

- **4.1 Stoppen.** `docker stop -t 90 scrum4me-forgejo`.
- **4.2 Tag wisselen (alleen regel 22).** `sudo sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.2$|image: codeberg.org/forgejo/forgejo:15.0.7|' "$CF" && grep -n 'forgejo/forgejo:' "$CF"` → precies één regel, met `15.0.7`, geen `15.0.2` meer. `sudo diff "$BK/docker-compose.yml.pre" "$CF"` → alleen deze ene regel (plus in de compose-tak de regel uit 2.5a).
- **4.3 Service-gebonden opbrengen.** `docker compose -f "$CF" up -d --no-deps forgejo` → de container wordt hercreëerd met dezelfde naam, hetzelfde volume en dezelfde netwerken. Direct daarna: `docker inspect scrum4me-forgejo --format '{{.Config.Image}}'` → `codeberg.org/forgejo/forgejo:15.0.7`; `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → ID's gelijk aan `RID`/`DID`, beide `running` (bewijs dat `--no-deps` de legacy stack niet raakte).
- **4.4 Migraties volgen.** `docker logs -f scrum4me-forgejo` tot de HTTP-listener meldt dat hij luistert; `curl -s http://127.0.0.1:3010/api/v1/version` → `15.0.7+gitea-1.22.0`. `docker logs --since 5m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'` → leeg. Caddy lost `forgejo` via Docker-DNS per verzoek op; blijft `[mac]` `curl -s https://git.jp-visser.nl/api/v1/version` na 60 s 502 geven, dan is dat een STOP-bevinding (géén eigenmachtige Caddy-herstart; JP beslist).
- **4.5 Doctor achteraf.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-post.log" 2>&1; echo "exit=$?"` → exit 0; `diff <(grep -v -E '^\[I\]' "$HOME/doctor-pre-venster.log") <(grep -v -E '^\[I\]' "$HOME/doctor-post.log")` → geen nieuwe waarschuwingen of fouten.
- **4.6 [JP] Functioneel.** Inloggen, een repository, een pull request en de Actions-pagina van `janpeter/scrum4me-shared` openen; `forgejo --version` in de container: `docker exec scrum4me-forgejo forgejo --version` → `15.0.7+gitea-1.22.0 (release name 15.0.7)`.

**Gate 4:** versie 15.0.7 via 3010, via Caddy en via `forgejo --version`; doctor zonder nieuwe bevindingen; geen `[E]`; legacy container-ID's ongewijzigd; JP-functioneel groen. Anders **Rollback R4**. Beslisregel: is Gate 4 op **T+20** niet groen, dan begint R4 meteen, zodat het venster inclusief herstel binnen 30 min blijft.

---

## Fase 5 — pool herstellen, venster sluiten (~T+22 … T+30)

- **5.1 [JP] Legacy runner hervatten.** Runners → `scrum4me-srv-runner` → Resume. `[mac]` capture → id 3 `idle`, versie `v12.10.1`.
- **5.2 [max2] Trust-verdict vernieuwen, dan controller starten (runbook §5).** `sudo systemctl start forgejo-runner-trust.service && sudo systemctl show forgejo-runner-trust.service -p Result` → `Result=success`; `python3 -c 'import json;d=json.load(open("/opt/forgejo-runner/trust-verdict.json"));print(d["ok"],d["measured_at"])'` → `True` en een epoch ná `T0` (bewijs dat de trust-API-endpoints op 15.0.7 werken). Daarna `sudo systemctl start forgejo-runner-cycle.service; sudo journalctl -u forgejo-runner-cycle.service --since "$T0" --no-pager` → `SOURCE_WAIT` → tweemaal `READY` → `cyclus: scrub ok=True` → `cyclus: runner gestart`. `[mac]` capture → `max2-forgejo-runner-02` `idle`.
- **5.3 Smoke (runbook §6).** Tijdelijke `smoke-green.yml` (`on: [workflow_dispatch]`, `runs-on: ubuntu-latest`, `run: echo "smoke groen"; exit 0`) op `janpeter/scrum4me-shared` (staat in de trust-allowlist), dispatchen, terminale status **success**; noteer runnummer en welke runner hem draaide (Forgejo-UI of `docker ps` op de host die hem kreeg). Workflow daarna weer verwijderen. Eén groene run volstaat: het doel is het Forgejo↔runner-protocol op 15.0.7; de online/idle-status van het andere record uit 5.1/5.2 is het protocolbewijs voor die runner.
- **5.4 Venster sluiten.** `TEND=$(date -u +%FT%TZ)`; downtime = `TSTOP` (2.6) tot de 15.0.7-listener (4.4); totale duur `T0`→`TEND` ≤ 30 min. Leg beide vast in `venster.md`.

**Gate 5:** beide records `idle` op 15.0.7; trust-verdict `ok:true` met `measured_at` ná `T0`; controller in `WAITING`; smoke `success`; tijden vastgelegd.

---

## Fase 6 — nazorg zonder downtime (dezelfde dag)

- **6.1 Evidence** onder `docs/forgejo-runner-pool/evidence/forgejo-15.0.7/`: `fase0/` (metingen, `doctor-pre.log`), `backup-manifest.md` (paden, groottes, sha256's, tijden — géén inhoud), `doctor-pre-venster.log`, `doctor-post.log`, `versies.txt` (`forgejo --version` voor/na, image-digest), `runners-voor.tsv`/`runners-na.tsv` (**zonder uuid-kolom**, zie 0.9), `smoke.md`, `venster.md` (T0/TSTOP/TEND, besluit over 2.5b, gekozen takken 2.5a/3.3), `controller-journal-max2.txt` (uittreksel sinds `T0`). Redactie vóór commit: `grep -r -n -i -E 'token|secret|passw|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' docs/forgejo-runner-pool/evidence/forgejo-15.0.7/` → geen waarden; `bash forgejo-runner/scripts/secret-scan.sh docs/forgejo-runner-pool/evidence/forgejo-15.0.7/*` → exit 0.
- **6.2 Docs.** `CLAUDE.md` en `AGENTS.md` regel 3: "Forgejo 15.0.2" → "Forgejo 15.0.7"; in de Oriëntatie-tabel van `CLAUDE.md` een rij voor `forgejo-upgrade-onderzoek-2026-09.md` en één voor dit plan. `evidence/stap-a/t-requeue.md` blijft historisch (gemeten op 15.0.2); noteer in `versies.txt` dat `app.ini` `[actions]` na de upgrade nog steeds geen timeout-override heeft (`T_requeue` = 600 s blijft geldig: `docker exec scrum4me-forgejo sh -c 'sed -n "/^\[actions\]/,/^\[/p" /data/gitea/conf/app.ini'`).
- **6.3 Commit + PR.** Branch `ops/forgejo-15.0.7`, commit `ops(forgejo): 15.0.2 → 15.0.7, trusted proxies expliciet, secrets geroteerd — evidence`, PR op Forgejo via de API (`Authorization: token $FORGEJO_TOKEN` via `curl --config`), JP merget.
- **6.4 Retentie rollbackpunt.** `$BK` blijft **zeven dagen** na Gate 5 staan (zelfde termijn als de stabiliteitsdefinitie §9); vernietigingsdatum in `backup-manifest.md`; verwijdering (`sudo rm -rf "$BK"`) is een [JP]-handeling. Bij een R4-rollback blijft ook de hernoemde database staan tot JP hem laat vallen.
- **6.5 Scrum4Me.** Per taak `update_task_status`; `log_implementation` met de evidence-paden; geen productdoc nodig naast dit plan en het onderzoek (JP beslist of het onderzoek als runbook in de DB moet).

**Gate 6:** PR gemerged; `secret-scan.sh` exit 0; `CLAUDE.md`/`AGENTS.md` noemen 15.0.7; vernietigingsdatum vastgelegd.

---

## Rollback

Elke terugweg herstelt naar de toestand van het laatst groene gate; er is geen "point of no return" vóór 4.3, en na 4.3 is de terugweg het koude rollbackpunt van Gate 2.

- **R2 (Gate 2 rood, forge gestopt, niets veranderd behalve `app.ini`):** `sudo cp -a "$BK/app.ini.pre" "$VOL/gitea/conf/app.ini"` (compose-tak: ook `sudo cp -a "$BK/docker-compose.yml.pre" "$CF"`), `docker start scrum4me-forgejo`, Gate 3-controles 3.1/3.2 op 15.0.2, dan Fase 5.
- **R3 (Gate 3 rood):** `docker stop -t 90 scrum4me-forgejo`, zelfde herstel als R2, `docker start`, 3.1/3.2, dan Fase 5. Het venster sluit zonder image-upgrade; bevinding naar JP.
- **R4 (Gate 4 rood of T+20 zonder groen):**
  1. `docker stop -t 90 scrum4me-forgejo`.
  2. Database terug (de gemigreerde database wordt **hernoemd**, niet gedropt, voor forensisch onderzoek):
     ```sh
     docker cp "$BK/forgejo-pre-15.0.7.dump" scrum4me-postgres:/tmp/forgejo-pre-15.0.7.dump
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE forgejo RENAME TO forgejo_failed_15_0_7"'
     docker exec scrum4me-postgres sh -c 'pg_restore -U "${POSTGRES_USER:-postgres}" -d postgres --create --exit-on-error /tmp/forgejo-pre-15.0.7.dump'
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -Atc "select datname from pg_database"'   # verwacht: forgejo én forgejo_failed_15_0_7
     docker exec scrum4me-postgres rm /tmp/forgejo-pre-15.0.7.dump
     ```
     `ALTER DATABASE … RENAME` vereist dat niemand op `forgejo` verbonden is (de forge is gestopt). `pg_restore --create` maakt de database met de in het archief vastgelegde eigenschappen opnieuw aan; `-d postgres` is alleen de onderhoudsverbinding.
  3. Volume terug: `sudo rsync -aHAX --numeric-ids --delete "$BK/data/" "$VOL/"` (bevat de `app.ini` van ná 2.5, consistent met Gate 3; wil JP ook de configuratie terug, dan daarna `app.ini.pre` kopiëren zoals in R2).
  4. Tag terug: `sudo sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.7$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF" && grep -n 'forgejo/forgejo:' "$CF"`; `docker compose -f "$CF" up -d --no-deps forgejo`.
  5. Controles 3.1/3.2 op 15.0.2 + `doctor check --all` → dan Fase 5 (pool herstellen). Bevinding, logs en de naam `forgejo_failed_15_0_7` naar JP; het onderzoek bepaalt of en wanneer een tweede poging volgt.
- **Fase 5 faalt (runner komt niet online, trust rood, smoke rood):** dit is een poolbevinding, geen reden om de forge terug te zetten. Legacy runner en controller volgen runbook §9 ("als iets misgaat"); JP beslist.

---

## Bevindingen buiten scope (voor JP)

- **Maintenance-record niet armbaar.** `MaintenanceRecord` bestaat in `forgejo_runner_cycle.py` en is getest (`tests/test_cycle_maintenance.py`), maar `cycle_runtime.py`, `cycle_adapters.py`, `forgejo-runner-cycle.service` en `controller.toml.example` bieden geen manier om er een te laden. Daarmee zijn stap F punt 12 (`migratieontwerp.md` §8) en de Global Constraint "control-plane-impact vereist een gearmd maintenance-record" uit het stap-G-plan op dit moment niet door een mechanisme af te dwingen. Dit plan omzeilt dat met een geplande stop; stap F heeft een echte oplossing nodig (laadpad in `controller.toml` of een bestandspad dat de runtime pollt).
- **Forgejo 16 en Runner 13** blijven buiten dit plan; zie onderzoek §3–§5.

---

## Zelf-review (grondslag-dekking)

- **Upgrade-guide:** backup (2.4/2.7, Gate 2), `doctor check --all` vooraf (0.4, 2.6) en achteraf (4.5), `flush-queues` (2.6), verificatie via webinterface (4.6), loglevel-troubleshooting alleen bij een STOP.
- **Onderzoek §2:** service-gebonden compose (Global Constraints, 4.3), control-plane-drain (2.1–2.3), trust-timer (0.7, 5.2), geen versiepin in de probe (5.2 bewijst herstel).
- **Onderzoek §3/§6:** trusted proxies (0.11, 2.5a, 3.3), secretrotatie (2.4 vingerafdruk, 2.5b, 3.4, 0.10 impact), `T_requeue` blijft geldig (6.2).
- **Geen placeholders:** elk commando is concreet; enige in te vullen waarden zijn `SUBNET` (0.11) en de tijdstempels. **Geen secrets:** waarden blijven in de container of in de root-only `$BK`.
- **Consistentie:** `RID`/`DID` (2.6 → 4.3), `PRE_SECRETS`/`POST_SECRETS` (2.4 → 2.5b → 3.4), `T0`/`TSTOP`/`TEND` (2 → 5.4), takkeuze 2.5a en 3.3 vastgelegd in 0.2/0.8 en `venster.md`.

## Uitvoerhandoff

Volgorde: (1) **plan-review** (review-loop, twee cross-model reviewers: `scrum4me-server:claude` ops-routed — Docker/Postgres/compose op de host zelf — en `mac:codex`) tot dubbel GO; (2) **JP-gate**; (3) **Scrum4Me-ceremonie** op product `cmsx8zbdh0002hk7rcgxxr00k` (sprint → PBI → story → taken per fase, met de commando's en gates uit dit plan gekopieerd) → hardstop; (4) uitvoering uitsluitend na een afzonderlijke opdracht van JP, in een door JP gepland venster, niet gelijktijdig met stap F/G.

## Review record

Plan-fase van de review-loop (twee onafhankelijke cross-model reviewers, JP-armd; zij zien elkaars output niet). Persistente loop-staat.

### Ronde 1 — nog te verzenden
- **Reviewers:** `scrum4me-server:claude` (ops-routed: kan `$CF`, `app.ini`-sleutels en de containers op de host zelf verifiëren) + `mac:codex`.
- **Onder review:** dit plan + `forgejo-upgrade-onderzoek-2026-09.md`, tegen de Forgejo upgrade-guide, `migratieontwerp.md` §7.7/§7.9/§9, `evidence/stap-d/bring-up-runbook.md` §5–§7, `implementatieplan-stap-g.md` B3/C3 en de as-built bundel `forgejo-runner/`.
- **Scope-noot voor reviewers:** de keuze 15.0.7 in plaats van 16.0.3 en het uitstel van Runner 13 zijn onderbouwd in het onderzoek (§3–§5) en liggen bij JP; wél in scope: of het plan de drain, het rollbackpunt, de twee gates en de terugwegen correct en volledig uitvoert, en of elke boomclaim klopt.
