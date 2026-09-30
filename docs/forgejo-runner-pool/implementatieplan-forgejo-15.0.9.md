# Implementatieplan — Forgejo 15.0.2 → 15.0.9 op `scrum4me-server`

> **Status (30 september 2026): omgezet van 15.0.7 naar 15.0.9; delta-review loopt.** De plan-review gaf op 9 september dubbel GO voor doel 15.0.7 (commit `21d103e`, PR #26); dat plan is niet uitgevoerd. JP-besluit 30 september: eerst 15.0.9 (LTS), eind oktober 17.0 via een eigen plan. Wat er sinds de GO is gewijzigd en waarom staat onder "Delta 30 september 2026" in het Review record.

> **Voor uitvoerders:** dit is een **operator-gedreven onderhoudsactie** op een productiehost, geen code-implementatie. Voer fase voor fase uit met de gate ná elke fase; bij een rode gate: **STOP** (stoppen, journal/uitvoer vastleggen, JP melden — niet forceren, niet de gate versoepelen). Elke fase heeft een terugweg (zie Rollback). Commando's zonder host-label draaien **op `scrum4me-server`** als `janpeter` (docker-groep, `sudo` waar aangegeven); `[max2]`-stappen draaien op `max2`; `[mac]`-stappen op de mac met persoonlijk `FORGEJO_TOKEN`; `[JP]`-stappen zijn JP-only (beheerinterface, besluiten).

**Doel:** de live forge `scrum4me-forgejo` van `codeberg.org/forgejo/forgejo:15.0.2` naar `:15.0.9` (LTS) brengen, in hetzelfde venster `[security] REVERSE_PROXY_TRUSTED_PROXIES` expliciet op het proxynetwerk zetten en de twee op 9 september 2026 gelekte secrets (`[oauth2] JWT_SECRET`, `[server] LFS_JWT_SECRET`) roteren — met een vóór de wijziging bewezen rollbackpunt en met de runnerpool netjes gedraind en hersteld.

**Architectuur:** één onderhoudsvenster (doel ≤ 30 min downtime), twee losse wijzigingsstappen met elk een eigen gate en terugweg: eerst de configuratie op 15.0.2 (herstart → gate), dan de image naar 15.0.9 (herstart → gate). Backup = `pg_dump` van database `forgejo` uit de gedeelde `scrum4me-postgres` + rsync-kopie van volume `forgejo_forgejo-data`, koud genomen. Runnerpool: legacy runner gepauzeerd, `max2`-controller netjes gestopt (runbook §7), na afloop trust-verdict handmatig vernieuwd en controller gestart (runbook §5), smoke (runbook §6).

**Tech stack:** Ubuntu 26.04, Docker Engine 29.7.2, Docker Compose 5.1.4 (compose-project `forgejo`), Forgejo rootful image, Postgres 17 (`scrum4me-postgres`, gedeeld met de scrum4me-app), Caddy 2, systemd-cyclecontroller op `max2` (bundel `forgejo-runner/`).

**Spec / grondslag:** [forgejo-upgrade-onderzoek-2026-09.md](forgejo-upgrade-onderzoek-2026-09.md) (§1 gemeten uitgangssituatie, §2 wat een upgrade hier betekent, §3 de LTS-lijn 15.0 tegenover 16, §6 secretlek); de releasenotes 15.0.3–15.0.9 (`release-notes-published/` in `forgejo/forgejo`: 15.0.8 en 15.0.9 bevatten elk een als *Critical* gepubliceerde RCE-fix, PR #14302 en #14371 — de reden dat het doel de nieuwste LTS-patch is); [Forgejo upgrade-guide](https://forgejo.org/docs/latest/admin/upgrade/); `migratieontwerp.md` §7.7/§7.9 (control-plane-onderhoud, drain, nulbewijs) en §9; `evidence/stap-d/bring-up-runbook.md` §5–§7 (controller starten, smoke, nette stop); `implementatieplan-stap-g.md` B3/C3 (het compose-project bevat de live forge); `CLAUDE.md` hardstops.

---

## Global Constraints (bindend, uit `CLAUDE.md`, het migratieontwerp en het stap-G-plan)

- **Geen secrets in Git.** Geen tokenwaarden, JWT-secrets, wachtwoorden, UUID's van runners of `app.ini`-kopieën in evidence of docs. De backupmap op de host is root-only (`0700`). `secret-scan.sh` moet exit 0 geven vóór elke commit — maar let op: die scanner sluit UUID's **bewust** uit (`sha256:`/`token_url`/UUID-vorm vallen buiten zijn filter). De **UUID-regel** wordt daarom gehandhaafd door de aparte recursieve grep in 6.1, niet door `secret-scan.sh`. De bestaande stap-A-evidence draagt nog een rauwe `uuid`-kolom (o.a. `evidence/stap-a/forgejo/runners-summary.tsv`) — bewuste erfenis of op te schonen; JP beslist, buiten scope van dit plan.
- **Compose-project `forgejo` uitsluitend service-gebonden benaderen.** Nooit `docker compose down`, `up -d` zonder servicenaam, `--remove-orphans`, `prune` of `-v` in dit project: het bevat naast de forge ook de legacy runner en DinD (stap-G-plan B3/C3). Toegestaan: `docker compose -f "$CF" up -d --no-deps forgejo`, `docker stop/start/restart scrum4me-forgejo`.
- **Hostregel "Compose-bestanden wijzigen"** (`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md` §4 B2, goedgekeurd 28 sep). Er komt geen losse kopie van een compose-bestand, ook niet in de backupmap: de terugweg voor `$CF` is de omkeerbare tagwissel met een sha256-bewijs (2.4, 4.2, R4). Staat `/srv/scrum4me/forgejo` onder git (0.13), dan begint het werk aan `$CF` met een schone `git status` en eindigt het met een commit volgens die regel (6.2).
- **Productiecontext (`CLAUDE.md`).** Host-Dockerdaemon niet herstarten, `/etc/docker/daemon.json` niet wijzigen, geen hostbrede prune. `scrum4me-postgres` wordt **niet** herstart of gewijzigd; het plan raakt die container alleen met `pg_dump`/`pg_restore` van database `forgejo`.
- **Backup vóór wijziging, bewezen restorepad.** Een major- of patchupgrade van Forgejo migreert de database automatisch en onomkeerbaar (upgrade-guide); Gate 2 (koud rollbackpunt) is voorwaarde voor elke daaropvolgende wijziging.
- **Eén variabele per gate.** Configuratie (trusted proxies + secrets) krijgt een eigen herstart en gate op 15.0.2 vóór de image wisselt, zodat een falende start eenduidig toe te schrijven is.
- **Control-plane-onderhoud = pool drainen.** Vóór de forge stopt: legacy runner gepauzeerd en `max2`-controller netjes gestopt met Forgejo-side nulbewijs (§7.9). De as-built controller kan géén maintenance-record laden (`cycle_runtime.py`/`cycle_adapters.py`/`controller.toml.example` kennen geen laadpad; `Controller.__init__` zet `self.maintenance = None`), dus een gestopte controller is hier de enige manier om een vals availability-incident te vermijden. Stap H loopt nog niet; er is geen stabiliteitsklok die reset.
- **Niet gelijktijdig met ander werk op de hosts** (stap F/G, reboots, bundelwijzigingen, en de compose-opruiming van ISS-5 in `/srv/scrum4me/forgejo`). Eén wijziging tegelijk; `git status --porcelain` van de uitvoerder toont alleen eigen evidence.
- **Meten, niet aannemen.** Elke waarde die hieronder "gemeten door JP op 9 september 2026" heet, wordt in Fase 0 opnieuw gemeten; wijkt zij af, dan is dat een STOP tot het plan is bijgewerkt.
- **Forge = Forgejo.** Evidence en docwijzigingen via een branch + PR op `git.jp-visser.nl` (API of `tea`), nooit via GitHub-tooling; uitrol nooit via Forgejo Actions.

Vaste paden in dit plan (op `scrum4me-server`):

```sh
CD=/srv/scrum4me/forgejo                                    # compose-map van project "forgejo" (mapnaam)
CF=$CD/docker-compose.yml
VOL=/var/lib/docker/volumes/forgejo_forgejo-data/_data      # forge-datavolume (/data in de container)
BK=/srv/backups/manual/forgejo-pre-15.0.9                   # koud rollbackpunt, root-only
```

---

## Fase 0 — read-only metingen (dagen vóór het venster, ~20 min, geen impact)

Leg alle uitvoer vast onder `evidence/forgejo-15.0.9/fase0/` (zie Fase 6 voor de redactieregels: geen secrets, geen UUID's).

- **0.1 Versie en compose-project.** `docker exec scrum4me-forgejo forgejo --version` → verwacht `15.0.2+gitea-1.22.0`. `docker compose -f "$CF" config --services` → bevat `forgejo`, `runner`, `dind`. `docker compose ls --filter name=forgejo` → project `forgejo` running.
- **0.2 Compose-regels (op inhoud, niet op regelnummer).** De regelnummers van 9 september gelden niet meer als toets: op 28 september verscheen in dezelfde map een kopie `docker-compose.yml.bak-throttle-…` van een andere sessie (`docs/runbooks/evidence/2026-09-28-compose-git-init.md:45`), wat op een lopende wijziging aan dit bestand wijst. `grep -n -E 'image:|depends_on|ports:|container_name' "$CF"` → exact één regel `image: codeberg.org/forgejo/forgejo:15.0.2` (`grep -c 'forgejo/forgejo:' "$CF"` → `1`); de forge-service heeft géén `depends_on`; poorten `127.0.0.1:3010:3000` en de SSH-regel op het Tailscale-IP. Env-namen van de forge-service, **namen alleen**: `grep -n -o -E 'FORGEJO__[A-Za-z0-9_]+' "$CF" | sort -u`. Staat `FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES` erin, dan is dat een **STOP**: dit plan dekt alleen de app.ini-tak (op 9 sep op de host gemeten door `scrum4me-server:claude`, Review record ronde 1); die waarde in `$CF` wijzigen vraagt een terugweg die de hostregel niet als losse kopie toestaat, en dus eerst een herzien plan. Ownership van het bestand: `stat -c '%U:%G %a' "$CF"`.
- **0.3 Containergebruiker en configpad.** `docker exec scrum4me-forgejo id git` → bestaat (rootful image draait Forgejo als `git`, UID `USER_UID`). `docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini` → noteer eigenaar en mode; 2.5 draait als die eigenaar (`-u git` als `git` eigenaar is, anders `-u root`) en herstelt daarna eigenaar en mode met `chown`/`chmod` naar exact deze waarden, omdat `sed -i` het bestand opnieuw aanmaakt. `docker inspect scrum4me-forgejo --format '{{.HostConfig.RestartPolicy.Name}} {{.Config.Image}} {{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1` → restartbeleid, image, **env-namen** (waarden worden bewust niet getoond).
- **0.4 Doctor vooraf.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-pre.log" 2>&1; echo "exit=$?"` → exit 0; noteer waarschuwingen. Een `[E]`-regel is een STOP (eerst begrijpen, dan pas upgraden).
- **0.5 Omvang en ruimte.** `sudo du -sb "$VOL"`; `PGU=$(docker exec scrum4me-postgres sh -c 'printf %s "${POSTGRES_USER:-postgres}"')` (alleen de rolnaam); `docker exec scrum4me-postgres psql -U "$PGU" -d postgres -Atc "select pg_database_size('forgejo')"`; `sudo mkdir -p /srv/backups/manual && df -B1 --output=avail /srv/backups | tail -1`. Voorwaarde: vrij ≥ 2 × (volume + database).
- **0.6 Gereedschap.** `command -v rsync` (vereist voor Fase 1/2; ontbreekt het → JP beslist over `sudo apt-get install rsync` vóór Fase 1, of het plan wordt herzien — er is bewust geen tar-fallback, omdat die de volledige kopietijd in het venster legt). `docker exec scrum4me-postgres pg_restore --version`.
- **0.7 Timers en tijdzone.** `systemctl list-timers --all --no-pager | grep -i -E 'backup|restic|prune|mirror'` (nachtelijke backup: geen overlap met het venster; de nachtelijke `forgejo-mirror-sync.timer`, 02:30 UTC ± 5 min volgens `scripts/forgejo-mirror/README.md`, schrijft via de Forgejo-API: ook daar geen overlap). `[max2]` `systemctl list-timers forgejo-runner-trust.timer --no-pager` en `timedatectl | grep 'Time zone'` → het venster valt buiten 00:00–00:06, 06:00–06:06, 12:00–12:06 en 18:00–18:06 lokale tijd van `max2` (`OnCalendar` + `RandomizedDelaySec=300` in `forgejo-runner-trust.timer`).
- **0.8 Routerlog aanwezig?** `docker logs --since 30m scrum4me-forgejo 2>&1 | grep -c 'router: completed'` → > 0 betekent dat Gate 3 het client-IP via het routerlog kan bewijzen; 0 betekent dat Gate 3 terugvalt op de configregel + foutloze start (leg vast welke).
- **0.9 Runnerrecords vooraf.** `[mac]` `FORGEJO_TOKEN=… bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-15.0.9/voor` → verwacht twee records (`scrum4me-srv-runner` id 3 en `max2-forgejo-runner-02`), beide `idle`, versie `v12.10.1`. **Commit alleen de geredigeerde samenvatting** (Fase 6): `cut -f1,2,4,5,6,7,10 runners-summary.tsv` (zonder de `uuid`-kolom).
- **0.10 OAuth2-afhankelijkheid.** `[JP]` Site Administration → Applications: zijn er OAuth2-applicaties die Forgejo als provider gebruiken? Noteer ja/nee en welke; hun tokens vervallen bij de secretrotatie (2.5b).
- **0.11 Caddy-netwerk.** `docker inspect scrum4me-forgejo --format '{{range $n,$v := .NetworkSettings.Networks}}{{$n}}={{$v.IPAddress}} {{end}}'` en hetzelfde voor `scrum4me-caddy` → het gedeelde netwerk (compose-commentaar: `compose_default`). `docker network inspect NETWERK --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'` met `NETWERK` = de gedeelde netwerknaam uit de vorige regel → `SUBNET` (bv. `172.18.0.0/16`). Dit is de waarde voor 2.5(a).
- **0.12 Jobstatus-endpoint bereikbaar (bron voor het nulbewijs 2.3).** `[mac]` `curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") -s -o /dev/null -w '%{http_code}\n' https://git.jp-visser.nl/api/v1/admin/actions/runners/jobs` → `200`. Het token moet admin-recht hebben (zelfde account als de trustscan, README §9). Een `403` betekent onvoldoende recht → STOP tot een geschikt token beschikbaar is.
- **0.13 Compose-map onder git?** `if [ -d "$CD/.git" ]; then echo GIT_CF=ja; git -C "$CD" status --porcelain; else echo GIT_CF=nee; fi` → noteer `GIT_CF`. Bij `ja` moet de statusuitvoer leeg zijn; een vuile werkboom is volgens de hostregel een STOP (wijziging van een andere sessie: `git status` en `git diff --stat` tonen, JP vragen, niet committen). Losse kopieën in de map zijn niet van dit plan en blijven onaangeroerd.
- **0.14 Automatische schrijvers (invulling van de write-fence).** Naast de runnerpool schrijven naar Forgejo: de nachtelijke mirror-sync (0.7) en de applicaties `scrum4me-mcp` (PR's, reviews, issue-mirror), `Scrum4Me` (review-dispatch, issue-sync), `scrum4me-docker` (docs-audit-PR's, releasetags) en de review-bot `s4m-codex-reviewer` (inventaris over alle repositories, 28 sep). `[JP]` besluit per schrijver: pauzeren voor het venster, of accepteren onder het restrisico van Gate 4; vastleggen in `venster.md`.

**Gate 0:** versie 15.0.2 bevestigd; de compose-inhoud (0.2) en de DB-configuratie komen overeen met §1 van het onderzoek; doctor zonder `[E]`; ruimte ≥ 2×; rsync + pg_restore aanwezig; venster gekozen buiten de timerslagen en de mirror-sync; app.ini-tak bevestigd (0.2); `GIT_CF` bekend en de werkboom schoon (0.13); schrijversbesluit vastgelegd (0.14); routerlog-uitkomst bekend; beide runnerrecords `idle`; jobstatus-endpoint `200`; `SUBNET` bekend. Anders STOP.

---

## Fase 1 — voorbereiden zonder downtime (uren tot een dag vóór het venster)

- **1.1 Backupmap.** `sudo mkdir -p "$BK" && sudo chmod 0700 "$BK" && sudo chown root:root "$BK"`. Toets meteen dat het R4-kopiepad uit deze root-only map werkt (de uitvoerder is `janpeter`; `docker cp` uit een `0700 root:root`-map vereist `sudo`): `echo pad-test | sudo tee "$BK/.cptest" >/dev/null && sudo docker cp "$BK/.cptest" scrum4me-postgres:/tmp/.cptest && docker exec scrum4me-postgres rm /tmp/.cptest && sudo rm "$BK/.cptest"` → exit 0 (geen productieherstel; bewijst alleen het kopiepad).
- **1.2 Warme kopie van het volume** (Forgejo draait; de kopie is nog niet consistent, maar draagt het gros van de bytes zodat de koude delta in 2.7 kort is): `time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"` → exit 0; noteer duur en `sudo du -sb "$BK/data"`.
- **1.3 Image vooraf ophalen** (geen herstart): `docker pull codeberg.org/forgejo/forgejo:15.0.9 && docker image inspect codeberg.org/forgejo/forgejo:15.0.9 --format '{{index .RepoDigests 0}}'` → digest vastleggen.
- **1.4 Venster vastleggen + write-fence.** `[JP]` datum/tijd (UTC én lokaal), verwachte duur ≤ 30 min, buiten 0.7-slagen en de nachtelijke backup; aankondiging aan wie de forge gebruikt. Geen andere hostwijzigingen in dat venster. De aankondiging stelt expliciet dat de forge het hele venster (`T0`→Gate 5) **in onderhoud** is en **geen schrijfacties** aanneemt (geen pushes, geen web/API-writes); ook in Fase 3, wanneer de forge weer bereikbaar is, verifiëren uitsluitend de operator/JP de gates. Geautomatiseerde schrijvers bestaan wél (0.14): de runnerpool is gedraind (2.1–2.3), het venster ligt buiten de mirror-sync (0.7), en voor de overige schrijvers geldt JP's 0.14-besluit (pauzeren, of accepteren onder het restrisico van Gate 4); agents zijn geïnformeerd. Deze write-fence is de voorwaarde waarop R4 rekent — zie de restrisiconoot bij Gate 4.
- **1.5 Rollbacktijd schatten.** Uit 0.5 en 1.2: koude delta (2.7) hoort in minuten te passen; de restore (Rollback R4: `pg_restore` + rsync terug) hoort binnen het resterende venster te passen. Past het niet, dan verlengt JP het venster vóóraf; het wordt niet tijdens het venster opgerekt.

**Gate 1:** `$BK/data` gevuld en rsync exit 0; image 15.0.9 lokaal met vastgelegde digest; venster gepland en aangekondigd (incl. write-fence 1.4); R4-kopiepad (`sudo docker cp` uit `$BK`) getoetst exit 0; rollbacktijd geschat en passend.

---

## Fase 2 — venster openen: drainen, rollbackpunt (T+0 … ~T+10)

Noteer `T0=$(date -u +%FT%TZ)` bij de eerste handeling.

- **2.1 [JP] Legacy runner pauzeren.** Site Administration → Actions → Runners → `scrum4me-srv-runner` (id 3) → Pause (zelfde handeling als in stap E, runbook §6). Hij mag geen nieuwe job meer aannemen; een lopende job laten eindigen.
- **2.2 [max2] Controller netjes stoppen (runbook §7), daarna offline-bewijs.** `sudo systemctl stop forgejo-runner-cycle.service; sudo systemctl show forgejo-runner-cycle.service -p ExecMainStatus -p Result` → `ExecMainStatus=0`, `Result=success`; `cd /opt/forgejo-runner && docker compose ps --profile cycle runner` → leeg; `ls /opt/forgejo-runner/state/cycle-op.marker` → bestaat niet (een aanwezige marker na een schone stop is een diagnostisch signaal, runbook §7). DinD blijft draaien. Wacht daarna **minimaal `fetch_timeout` + 10 s** (`fetch_timeout: 5s` in `runner-config.policy.yml`, dus ≥ 15 s), zodat een net vóór de stop opgehaalde `FetchTask` is afgerekend (§7.9). `[mac]` capture → `bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-15.0.9/na-stop` → `max2-forgejo-runner-02` `offline` en `scrum4me-srv-runner` (id 3) niet `active`. Dit is een status-, geen jobcontrole — het nulbewijs zelf staat in 2.3.
- **2.3 [mac] Assignment-nulbewijs (§7.9 — ná de stop, jobkant).** Runnerstatus (2.2) is géén nulbewijs: `capture-forgejo-records.sh` haalt alleen `/api/v1/admin/actions/runners` op en kent geen jobstatus. §7.9 eist daarna twee snapshots ≥ 10 s uiteen **zonder assigned/running job** voor de gedrainde runners. Vraag de jobbron los op — de admin-endpoint `/api/v1/admin/actions/runners/jobs` (Forgejo 15+, `RunJobList`; de gedeprecte `/admin/runners/jobs` verwijst hiernaar), token via `curl --config` zodat hij niet in argv staat:
```sh
mkdir -p /tmp/fj-15.0.9
cat > /tmp/fj-15.0.9/nulbewijs.py <<'PY'
import json, sys
TERM = {"success", "failure", "cancelled", "canceled", "skipped"}
d = json.load(open(sys.argv[1]))
if d is None:                     # lege RunJobList = Go nil-slice → nul jobs
    d = []
if not isinstance(d, list):       # elk ander toplevel (bv. een JSON-errorobject) is GEEN geldig antwoord
    print("onverwacht antwoordtype:", type(d).__name__); sys.exit(2)
actief = []
for job in d:
    s = job.get("status") if isinstance(job, dict) else None
    if not (isinstance(s, str) and s.lower() in TERM):   # ontbrekend/niet-string/niet-terminaal telt mee
        actief.append(s)
print(len(actief), actief)
sys.exit(1 if actief else 0)
PY
Q() { curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
        -sS --fail-with-body --max-time 30 \
        https://git.jp-visser.nl/api/v1/admin/actions/runners/jobs; }
# LET OP: de subshell staat op een eigen regel en wordt NIET gevolgd door && of ||,
# en niet in een `if (...)`. In een AND-OR-lijst of if-conditie negeert bash de
# `set -e` binnen de subshell (gemeten, bash 5.3.9); alleen een losstaande subshell
# gevolgd door `rc=$?` handhaaft hem. Vandaar dit patroon overal in dit plan.
( set -e
  Q > /tmp/fj-15.0.9/jobs1.json        # niet-2xx → curl --fail-with-body exit != 0 → set -e stopt hier
  sleep 15
  Q > /tmp/fj-15.0.9/jobs2.json
  python3 /tmp/fj-15.0.9/nulbewijs.py /tmp/fj-15.0.9/jobs1.json
  python3 /tmp/fj-15.0.9/nulbewijs.py /tmp/fj-15.0.9/jobs2.json
)
rc=$?
[ "$rc" -eq 0 ] && echo "NULBEWIJS SCHOON (beide snapshots leeg)" \
  || { echo "NULBEWIJS ROOD of jobfetch faalde (exit $rc) — STOP, pas §7.9-remedie toe"; false; }
```
Fail-closed op drie niveaus: een niet-2xx-fetch stopt via `set -e` in de **losstaande** subshell (`curl --fail-with-body` geeft dan exit ≠ 0, en `rc` vangt het); een niet-lijst-toplevel — zoals een JSON-errorobject bij 401/403 — geeft exit 2; en elke job met een ontbrekende, niet-string of niet-terminale `status` telt als actief. Alleen wanneer bij **beide** snapshots de lijst leeg is (of `null`), verschijnt `NULBEWIJS SCHOON` en is het nulbewijs geleverd. `ActionRunJob` heeft een plat string-`status`-veld (geverifieerd tegen de swagger van deze instance; geen geneste objecten), dus het volstaat de toplijst te itereren; de endpoint geeft bij geen resultaten `null`. De pool kent alleen id 3 en `max2-forgejo-runner-02`, dus elke `waiting`/`running` job valt binnen scope. Bij `NULBEWIJS ROOD` geldt §7.9: blijf gepauzeerd, wacht `min(T_requeue + 30 s, 10 min)` (`T_requeue` = 600 s, `evidence/stap-a/t-requeue.md`); is de job na de grens niet aantoonbaar gerequeued/terminaal, dan annuleert de operator (`[JP]`/beheerinterface) de run en dispatcht dezelfde workflow vanaf dezelfde commit opnieuw. Pas ná een schoon nulbewijs mag 2.6 de forge stoppen. Dit reproduceert handmatig de `DRAINING`-nulbewijsstap die de as-built controller niet kan armen (zie "Bevindingen buiten scope").
- **2.4 Configuratie-rollbackpunt.** `sudo cp -a "$VOL/gitea/conf/app.ini" "$BK/app.ini.pre" && sudo sha256sum "$BK/app.ini.pre"` → hash in evidence. Van `$CF` komt géén kopie (hostregel): `PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); echo "$PRE_CF"` → hash in evidence; bij `GIT_CF=ja` eerst `git -C "$CD" status --porcelain` → leeg, anders STOP. Vingerafdruk van de te roteren regels, zonder waarden: `PRE_SECRETS=$(docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1)`.
- **2.5 Configuratiewijzigingen op de draaiende 15.0.2** (effectief bij de eerstvolgende herstart; het rollbackpunt van 2.4 is de terugweg). Hier en niet ná de stop, omdat `forgejo generate secret` het binary in de draaiende container gebruikt en de waarde zo de container nooit verlaat.
  - **(a) Trusted proxies** (app.ini-tak; de compose-tak is een STOP in 0.2). `docker exec -u git scrum4me-forgejo sh -c 'sed -i "s|^REVERSE_PROXY_TRUSTED_PROXIES *=.*|REVERSE_PROXY_TRUSTED_PROXIES = 127.0.0.0/8,::1/128,SUBNET|" /data/gitea/conf/app.ini'` met `SUBNET` uit 0.11 ingevuld; verificatie `docker exec scrum4me-forgejo grep -n -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini` → precies één regel, nieuwe waarde.
  - **(b) Secretrotatie (besluit JP, onderzoek §6).** Waarden verlaten de container niet en komen niet in argv van de host:
    ```sh
    docker exec -u git scrum4me-forgejo sh -c 'v=$(forgejo generate secret JWT_SECRET) && sed -i "s|^JWT_SECRET *=.*|JWT_SECRET = $v|" /data/gitea/conf/app.ini'
    docker exec -u git scrum4me-forgejo sh -c 'v=$(forgejo generate secret LFS_JWT_SECRET) && sed -i "s|^LFS_JWT_SECRET *=.*|LFS_JWT_SECRET = $v|" /data/gitea/conf/app.ini'
    POST_SECRETS=$(docker exec scrum4me-forgejo sh -c 'grep -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini' | sha256sum | cut -d' ' -f1)
    ( set -e
      [ "$PRE_SECRETS" != "$POST_SECRETS" ]                                                                              # vingerafdruk moet zijn veranderd
      [ "$(docker exec scrum4me-forgejo sh -c 'grep -c -E "^(LFS_)?JWT_SECRET" /data/gitea/conf/app.ini')" = 2 ]          # precies twee secretregels
    )
    rc=$?
    [ "$rc" -eq 0 ] && echo "ROTATIE OK" || { echo "ROTATIE NIET/ONVOLLEDIG DOORGEVOERD (exit $rc) — STOP"; false; }
    ```
    De controle is **luid én afbrekend**: de twee tests staan in een **losstaande** `set -e`-subshell waarvan de exit in `rc` wordt gevangen — bij een gelijke vingerafdruk of een onverwacht aantal regels is `rc` ≠ 0 en eindigt het blok met een melding en exit ≠ 0. Dit móét een losstaande subshell zijn: `( … ) && … || …` zou de `set -e` binnen de subshell onderdrukken, zodat alléén de laatste test telt. `^JWT_SECRET` matcht alleen de `[oauth2]`-sleutel (de `[server]`-sleutel begint met `LFS_`); JP's grep van 9 september toonde precies die twee sleutels. `forgejo generate secret LFS_JWT_SECRET` is in de CLI een **alias** van `JWT_SECRET` (dezelfde generator); de tweede aanroep dient alleen om de doelsleutel te benoemen. Base64url bevat geen `|`, `&` of `/`, dus de sed-vervanging is veilig. Slaat JP de rotatie over: leg dat besluit vast in `venster.md` en sla (b) over; de rest van het plan verandert niet.
- **2.6 Doctor + queues, dan stoppen.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-pre-venster.log" 2>&1`; `docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m` → exit 0. Dan `docker stop -t 90 scrum4me-forgejo` en `docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'` → `Exited (…)`. `TSTOP=$(date -u +%FT%TZ)`. Legacy runner- en DinD-containers blijven ongemoeid: `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → beide `running`; bewaar de ID's als `RID`/`DID` voor Gate 4.
- **2.7 Koud rollbackpunt.** De hele reeks draait in een subshell met `set -e`, zodat elk falend commando — inclusief de `pg_restore --list`-verificatie — de reeks hard afbreekt (een losse `| wc -l` in een `&&`-keten zou dat níét doen: de pijplijn-exit is die van `wc`, en het plan zet nergens `pipefail`):
  ```sh
  ( set -e
    docker exec scrum4me-postgres sh -c 'pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -f /tmp/forgejo-pre-15.0.9.dump forgejo'
    LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/forgejo-pre-15.0.9.dump)   # eigen exit van pg_restore telt (set -e)
    [ -n "$LIST" ]                                                                          # niet-lege inhoudslijst of STOP
    docker cp scrum4me-postgres:/tmp/forgejo-pre-15.0.9.dump /tmp/forgejo-pre-15.0.9.dump
    sudo mv /tmp/forgejo-pre-15.0.9.dump "$BK/"
    sudo chmod 0600 "$BK/forgejo-pre-15.0.9.dump"
    docker exec scrum4me-postgres rm /tmp/forgejo-pre-15.0.9.dump
    sudo sha256sum "$BK/forgejo-pre-15.0.9.dump"; sudo stat -c '%s' "$BK/forgejo-pre-15.0.9.dump"
    time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"    # koude delta
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "KOUD ROLLBACKPUNT OK" || { echo "KOUD ROLLBACKPUNT MISLUKT (exit $rc) — STOP"; false; }
  ```
  De verificatie vangt de **eigen** exit van `pg_restore --list` (`LIST=$(…)` onder `set -e`, niet die van `wc`) plus een niet-lege lijst; bij een onbruikbaar archief breekt de losstaande subshell af en is `rc` ≠ 0, dus de dump wordt niet als rollbackpunt afgetekend. Lokale socketverbindingen in het officiële Postgres-image zijn `trust`, daarom volstaat de rolnaam.

**Gate 2 (rollbackpunt bewezen):** dump aanwezig, `--list` > 0, sha256 en grootte vastgelegd; koude rsync exit 0; `app.ini.pre` met hash en `PRE_CF` vastgelegd; forge gestopt, legacy containers `running` met ongewijzigde ID's; controller op `max2` `Result=success`. Anders STOP en Rollback R2 (forge gewoon weer starten op 15.0.2 met `app.ini.pre` teruggezet).

---

## Fase 3 — configuratie-gate op 15.0.2 (~T+10 … T+15)

- **3.1 Opbrengen op de oude image (configuratie effectief maken).** `docker start scrum4me-forgejo` — de app.ini-wijziging uit 2.5(a) wordt bij containerstart gelezen. Wacht tot `curl -s http://127.0.0.1:3010/api/v1/version` `"15.0.2+gitea-1.22.0"` geeft (poort uit 0.2). `docker logs --since 3m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'` → leeg.
- **3.2 Via Caddy.** `[mac]` `curl -s https://git.jp-visser.nl/api/v1/version` → `15.0.2+gitea-1.22.0`. `[JP]` inloggen op de webinterface, één repository openen (websessies overleven de rotatie: die hangen aan `SECRET_KEY`, niet aan `JWT_SECRET`).
- **3.3 Trusted proxies effectief.** *Routerlog aanwezig (0.8):* direct na 3.2 `docker logs --since 2m scrum4me-forgejo 2>&1 | grep 'api/v1/version' | tail -3` → het gelogde client-IP is het IP waarmee de mac bij Caddy binnenkomt (`[mac]` `curl -s https://ifconfig.me`, of het Tailscale-IP als die route via de tailnet loopt), **niet** het container-IP van Caddy uit 0.11. *Routerlog afwezig:* `docker exec scrum4me-forgejo grep -E '^REVERSE_PROXY_TRUSTED_PROXIES' /data/gitea/conf/app.ini` toont de nieuwe waarde en de start was foutloos (3.1); leg vast dat het IP-bewijs niet beschikbaar was.
- **3.4 Secrets.** `docker logs --since 3m scrum4me-forgejo 2>&1 | grep -i -E 'jwt|secret'` → leeg (geen decodeerfout). Vingerafdruk gelijk aan `POST_SECRETS` uit 2.5(b).

**Gate 3:** 15.0.2 antwoordt op 3010 én via Caddy; login werkt; trusted-proxies-bewijs volgens de 0.8-tak; geen `[E]`/jwt-fouten. Anders **Rollback R3** (configuratie terug) — het venster gaat dan zonder image-upgrade dicht via Fase 5, en JP krijgt de bevinding.

---

## Fase 4 — image naar 15.0.9 (~T+15 … T+22)

- **4.1 Stoppen + vers koud rollbackpunt.** `docker stop -t 90 scrum4me-forgejo`. Neem nu, met de forge gestopt, een **vers** rollbackpunt dat óók de writes uit Fase 3 (nog op 15.0.2, dus terugdraaibaar) bevat. Dit verse **paar** (DB-dump `forgejo-pre-image.dump` + de bijgewerkte `$BK/data`) is het R4-herstelpunt. Draai de reeks in een subshell met `set -e`, zodat een falende dump/verificatie hard afbreekt vóór de image wisselt:
  ```sh
  ( set -e
    docker exec scrum4me-postgres sh -c 'pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -f /tmp/forgejo-pre-image.dump forgejo'
    LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/forgejo-pre-image.dump)   # eigen exit van pg_restore telt (set -e)
    [ -n "$LIST" ]                                                                         # niet-lege inhoudslijst of STOP
    sudo docker cp scrum4me-postgres:/tmp/forgejo-pre-image.dump "$BK/forgejo-pre-image.dump"
    sudo chmod 0600 "$BK/forgejo-pre-image.dump"
    docker exec scrum4me-postgres rm /tmp/forgejo-pre-image.dump
    sudo sha256sum "$BK/forgejo-pre-image.dump"
    time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"    # $BK/data wordt nu het VERSE volume
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "VERS ROLLBACKPUNT OK" || { echo "VERS ROLLBACKPUNT MISLUKT (exit $rc) — STOP, ga NIET naar 4.2/4.3"; false; }
  ```
  Faalt dit (`rc` ≠ 0), dan **STOP vóór 4.2**: zonder geverifieerd vers punt mag de onomkeerbare image-upgrade niet doorgaan. Let op: de `rsync --delete` overschrijft `$BK/data` met het verse volume, dus na 4.1 vormen `forgejo-pre-image.dump` + `$BK/data` één samenhangend paar; de dump van 2.7 heeft daarna géén bijpassend volume meer en dient alléén nog als Gate-2-bewijs, **niet** als R4-fallback. Een pg_dump van ~125 MB en de kleine delta passen binnen de T+15…T+22-marge.
- **4.2 Tag wisselen (alleen de forge-imageregel) en bewijzen dat niets anders verschilt.**
  ```sh
  sudo sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.2$|image: codeberg.org/forgejo/forgejo:15.0.9|' "$CF"
  ( set -e
    [ "$(grep -c 'image: codeberg.org/forgejo/forgejo:15.0.9$' "$CF")" = 1 ]      # de nieuwe tag staat er precies één keer
    [ "$(grep -c 'forgejo/forgejo:' "$CF")" = 1 ]                                  # en er is geen tweede forge-imageregel
    [ "$(sed 's|image: codeberg.org/forgejo/forgejo:15.0.9$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF" | sha256sum | cut -d' ' -f1)" = "$PRE_CF" ]   # teruggerekend gelijk aan 2.4
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "TAGWISSEL OK (alleen de forge-imageregel gewijzigd)" || { echo "TAGWISSEL NIET EENDUIDIG (exit $rc) — STOP, ga NIET naar 4.3"; false; }
  ```
  De derde toets vervangt de `diff` tegen een kopie: rekent de nieuwe inhoud met dezelfde vervanging terug naar exact de hash uit 2.4, dan verschilt alléén de imageregel. Rood → STOP vóór 4.3: tag terugzetten met het recept uit R4 stap 5 (zonder de recreate), `docker start scrum4me-forgejo`, controles 3.1/3.2, dan Fase 5 (uitkomst `rolled_back`). Beproefd met GNU sed 4.9 en bash 5.2 in een tijdelijke map, inclusief vier afwijkingsgevallen: [recept-proef-2026-09-30.md](evidence/forgejo-15.0.9/recept-proef-2026-09-30.md).
- **4.3 Service-gebonden opbrengen.** `docker compose -f "$CF" up -d --no-deps forgejo` → de container wordt hercreëerd met dezelfde naam, hetzelfde volume en dezelfde netwerken. Direct daarna: `docker inspect scrum4me-forgejo --format '{{.Config.Image}}'` → `codeberg.org/forgejo/forgejo:15.0.9`; `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → ID's gelijk aan `RID`/`DID`, beide `running` (bewijs dat `--no-deps` de legacy stack niet raakte).
- **4.4 Migraties volgen.** `docker logs -f scrum4me-forgejo` tot de HTTP-listener meldt dat hij luistert; `curl -s http://127.0.0.1:3010/api/v1/version` → een versie die met `15.0.9` begint (het achtervoegsel is voor 15.0.9 niet vooraf gemeten; op 15.0.2 is het `+gitea-1.22.0`). `docker logs --since 5m scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic'` → leeg. Caddy lost `forgejo` via Docker-DNS per verzoek op; blijft `[mac]` `curl -s https://git.jp-visser.nl/api/v1/version` na 60 s 502 geven, dan is dat een STOP-bevinding (géén eigenmachtige Caddy-herstart; JP beslist).
- **4.5 Doctor achteraf.** `docker exec -u git scrum4me-forgejo forgejo doctor check --all --log-file - > "$HOME/doctor-post.log" 2>&1; echo "exit=$?"` → exit 0; `diff <(grep -v -E '^\[I\]' "$HOME/doctor-pre-venster.log") <(grep -v -E '^\[I\]' "$HOME/doctor-post.log")` → geen nieuwe waarschuwingen of fouten.
- **4.6 [JP] Functioneel.** Inloggen, een repository, een pull request en de Actions-pagina van `janpeter/scrum4me-shared` openen; `forgejo --version` in de container: `docker exec scrum4me-forgejo forgejo --version` → bevat `15.0.9`.

**Gate 4:** versie 15.0.9 via 3010, via Caddy en via `forgejo --version`; doctor zonder nieuwe bevindingen; geen `[E]`; legacy container-ID's ongewijzigd; JP-functioneel groen. Anders **Rollback R4**. Beslisregel: is Gate 4 op **T+20** niet groen, dan begint R4 meteen, zodat het venster inclusief herstel binnen 30 min blijft.

**Restrisico writes (aftekenen door JP bij de venster-goedkeuring):** het verse rollbackpunt (4.1) dekt alle 15.0.2-writes t/m Fase 3. Writes die ná 4.3 (recreate op 15.0.9, eenmalige onomkeerbare migratie) en vóór Gate 4-acceptatie worden geaccepteerd, zijn bij R4 **niet** herstelbaar — een 15.0.9-migratie is niet terug te draaien naar 15.0.2. Dat venster is enkele minuten en operator-only; de write-fence (1.4) houdt het leeg. JP tekent dit restrisico expliciet af.

---

## Fase 5 — pool herstellen, venster sluiten (~T+22 … T+30)

Fase 5 geldt voor **beide** uitkomsten van het venster. Zet `VNOW` op de versie die na Fase 4 óf na een rollback daadwerkelijk draait — `15.0.9` bij een geslaagde upgrade, `15.0.2` na R2/R3/R4: `VNOW=$(docker exec scrum4me-forgejo forgejo --version | grep -oE '1[0-9]+\.[0-9]+\.[0-9]+' | head -1)`. Verse trustvalidatie, poolherstel en smoke gelden in beide gevallen. Een geslaagde rollback sluit het **onderhoud** (uitkomst `rolled_back`), niet de upgrade-DoD.

- **5.1 [JP] Legacy runner hervatten.** Runners → `scrum4me-srv-runner` → Resume. `[mac]` capture → id 3 `idle`, versie `v12.10.1`.
- **5.2 [max2] Trust-verdict vernieuwen, dan controller starten (runbook §5).** `sudo systemctl start forgejo-runner-trust.service && sudo systemctl show forgejo-runner-trust.service -p Result` → `Result=success`. Bewijs **mechanisch** dat het verdict vers is — `measured_at` is een epoch, `T0` een ISO-tijd, dus niet met het oog vergelijken:
    ```sh
    MA=$(python3 -c 'import json;d=json.load(open("/opt/forgejo-runner/trust-verdict.json"));print(int(d["measured_at"]) if d.get("ok") else -1)')
    [ "$MA" -gt "$(date -u -d "$T0" +%s)" ] && echo "trust vers op VNOW" || { echo "trust-verdict niet ok of niet vers — STOP"; false; }
    ```
    (bewijst dat de trust-API-endpoints op `VNOW` werken; `-1` bij `ok:false` valt automatisch door de STOP). Daarna `sudo systemctl start forgejo-runner-cycle.service; sudo journalctl -u forgejo-runner-cycle.service --since "$T0" --no-pager` → `SOURCE_WAIT` → tweemaal `READY` → `cyclus: scrub ok=True` → `cyclus: runner gestart`. `[mac]` capture → `max2-forgejo-runner-02` `idle`.
- **5.3 Smoke (runbook §6).** Tijdelijke `smoke-green.yml` (`on: [workflow_dispatch]`, `runs-on: ubuntu-latest`, `run: echo "smoke groen"; exit 0`) op `janpeter/scrum4me-shared` (staat in de trust-allowlist), dispatchen, terminale status **success**; noteer runnummer en welke runner hem draaide (Forgejo-UI of `docker ps` op de host die hem kreeg). Workflow daarna weer verwijderen. Eén groene run volstaat: het doel is het Forgejo↔runner-protocol op `VNOW`; de online/idle-status van het andere record uit 5.1/5.2 is het protocolbewijs voor die runner.
- **5.4 Venster sluiten.** `TEND=$(date -u +%FT%TZ)`; downtime = `TSTOP` (2.6) tot de listener die daadwerkelijk opkwam (4.4 bij upgrade; de `up -d`/`docker start` uit R2/R3/R4 bij rollback — dan zijn er twee losse downtime-intervallen, rond Fase 3 én rond de rollback, leg ze allebei vast); totale duur `T0`→`TEND` ≤ 30 min. Leg de uitkomst (`upgraded`/`rolled_back`) en de intervallen vast in `venster.md`.

**Gate 5:** beide records `idle` op `VNOW` (15.0.9 bij upgrade, 15.0.2 bij rollback); trust-verdict `ok:true` met `measured_at` ná `T0`; controller in `WAITING`; smoke `success`; uitkomst en tijden vastgelegd.

---

## Fase 6 — nazorg zonder downtime (dezelfde dag)

- **6.1 Evidence** onder `docs/forgejo-runner-pool/evidence/forgejo-15.0.9/`: `fase0/` (metingen, `doctor-pre.log`), `backup-manifest.md` (paden, groottes, sha256's, tijden — géén inhoud), `doctor-pre-venster.log`, `doctor-post.log`, `versies.txt` (`forgejo --version` voor/na, image-digest), `runners-voor.tsv`/`runners-na.tsv` (**zonder uuid-kolom**, zie 0.9), `smoke.md`, `venster.md` (T0/TSTOP/TEND, besluit over 2.5b, gekozen tak 3.3, `GIT_CF`, schrijversbesluit 0.14), `controller-journal-max2.txt` (uittreksel sinds `T0`). Redactie vóór commit: de recursieve grep is de handhaving van de UUID-regel (secret-scan dekt UUID's niet, zie Global Constraints): `grep -r -n -i -E 'token|secret|passw|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' docs/forgejo-runner-pool/evidence/forgejo-15.0.9/` → geen waarden. Daarna secret-scan **recursief** — de scanner slaat directory-argumenten over en recursiet niet, dus de glob `.../forgejo-15.0.9/*` zou de submap `fase0/` overslaan; geef alle reguliere bestanden mee: `bash forgejo-runner/scripts/secret-scan.sh $(find docs/forgejo-runner-pool/evidence/forgejo-15.0.9 -type f)` → exit 0.
- **6.2 Docs en compose-map (uitkomstafhankelijk).** *Bij uitkomst `upgraded` en `GIT_CF=ja`:* leg de tagwissel in de compose-map vast volgens de hostregel: `docker compose -f "$CF" config -q` → exit 0; `git -C "$CD" add docker-compose.yml`; `git -C "$CD" diff --cached` → alleen de imageregel; `git -C "$CD" commit -m "forgejo 15.0.2 -> 15.0.9 (onderhoudsvenster <datum>)"`; `git -C "$CD" status --porcelain` → leeg (beproefd in een tijdelijke compose-map met `scripts/compose-git-init`, zelfde evidence als 4.2). *Bij `rolled_back` en `GIT_CF=ja`:* `git -C "$CD" status --porcelain` → leeg, want `$CF` is terug op `PRE_CF`. *Bij uitkomst `upgraded`:* `CLAUDE.md` en `AGENTS.md` regel 3 "Forgejo 15.0.2" → "Forgejo 15.0.9"; in de Oriëntatie-tabel van `CLAUDE.md` een rij voor `forgejo-upgrade-onderzoek-2026-09.md` en één voor dit plan. *Bij uitkomst `rolled_back`:* laat de versieregel op **15.0.2** staan (er draait immers 15.0.2), noteer de mislukte poging en de naam `forgejo_failed_15_0_9` in de evidence en verklaar nergens 15.0.9 als voltooid; de Oriëntatie-rijen mogen wel toegevoegd worden (het plan/onderzoek bestaan onafhankelijk van de uitkomst). In beide gevallen: `evidence/stap-a/t-requeue.md` blijft historisch (gemeten op 15.0.2); noteer in `versies.txt` de werkelijk draaiende versie en dat `app.ini` `[actions]` nog steeds geen timeout-override heeft (`T_requeue` = 600 s blijft geldig: `docker exec scrum4me-forgejo sh -c 'sed -n "/^\[actions\]/,/^\[/p" /data/gitea/conf/app.ini'`).
- **6.3 Commit + PR (committekst volgt uitkomst én rotatiebesluit).** Branch `ops/forgejo-15.0.9`. *Bij `upgraded` mét rotatie:* `ops(forgejo): 15.0.2 → 15.0.9, trusted proxies expliciet, secrets geroteerd — evidence`. *Bij `upgraded` zónder rotatie (2.5b overgeslagen):* laat "secrets geroteerd" weg. *Bij `rolled_back`:* `ops(forgejo): poging 15.0.9 teruggedraaid naar 15.0.2 — evidence` (met of zonder "secrets geroteerd", afhankelijk van 2.5b). PR op Forgejo via de API (`Authorization: token $FORGEJO_TOKEN` via `curl --config`), JP merget.
- **6.4 Retentie rollbackpunt.** `$BK` blijft **zeven dagen** na Gate 5 staan (zelfde termijn als de stabiliteitsdefinitie §9); vernietigingsdatum in `backup-manifest.md`; verwijdering (`sudo rm -rf "$BK"`) is een [JP]-handeling. Bij een R4-rollback blijft ook de hernoemde database staan tot JP hem laat vallen.
- **6.5 Scrum4Me.** Per taak `update_task_status`; `log_implementation` met de evidence-paden; geen productdoc nodig naast dit plan en het onderzoek (JP beslist of het onderzoek als runbook in de DB moet).

**Gate 6:** PR gemerged; `secret-scan.sh` exit 0; docs consistent met de uitkomst (bij `upgraded`: `CLAUDE.md`/`AGENTS.md` noemen 15.0.9; bij `rolled_back`: docs staan op 15.0.2 en de bevinding + `forgejo_failed_15_0_9` zijn vastgelegd); vernietigingsdatum vastgelegd.

---

## Rollback

Elke terugweg herstelt naar de toestand van het laatst groene gate; er is geen "point of no return" vóór 4.3, en na 4.3 is de terugweg het **verse** rollbackpunt van 4.1 — DB-dump `forgejo-pre-image.dump` én volume `$BK/data` als één samen genomen, samen geverifieerd paar. Het punt van 2.7 is Gate-2-bewijs, geen R4-bron: na de 4.1-rsync hoort de 2.7-dump niet meer bij het volume in `$BK/data`.

- **R2 (Gate 2 rood, forge gestopt, niets veranderd behalve `app.ini`):** `sudo cp -a "$BK/app.ini.pre" "$VOL/gitea/conf/app.ini"`; `docker start scrum4me-forgejo` (`$CF` is in dit stadium niet gewijzigd). Daarna Gate 3-controles 3.1/3.2 op 15.0.2, dan Fase 5 (uitkomst `rolled_back`).
- **R3 (Gate 3 rood):** `docker stop -t 90 scrum4me-forgejo`, zelfde herstel als R2, controles 3.1/3.2, dan Fase 5 (uitkomst `rolled_back`). Het venster sluit zonder image-upgrade; bevinding naar JP.
- **R4 (Gate 4 rood of T+20 zonder groen):** herstelt naar het **verse paar** van 4.1 — `forgejo-pre-image.dump` samen met het volume in `$BK/data`. Er is bewust **geen** terugval op de 2.7-dump: die hoort na de 4.1-rsync niet meer bij dit volume, dus een gemengd paar zou een inconsistente herstelset geven. Ontbreekt of faalt het verse punt, dan is dat een STOP naar JP (het kan niet ontbreken als 4.1 groen was — zonder groen 4.1 is 4.3 nooit uitgevoerd en is er geen migratie om terug te draaien).
  1. `docker stop -t 90 scrum4me-forgejo` (indien nog niet gestopt).
  2. Verse dump in de container plaatsen en **verifiëren vóór** enige databasewijziging. `$BK` is `0700 root:root`, dus de kopie draait onder `sudo` (geen onprivileged `[ -f ]`-test: `janpeter` kan de root-only map niet doorzoeken en zou zo'n test altijd false zien). Draai het in een **losstaande** subshell met `set -e` (níét `( … ) || …`, dat zou de `set -e` onderdrukken), en verwijder eerst een eventueel achtergebleven `/tmp/rollback.dump` van een vorige poging, zodat een mislukte kopie nooit op een oude dump verifieert:
     ```sh
     ( set -e
       docker exec scrum4me-postgres rm -f /tmp/rollback.dump                              # geen stale dump van een vorige poging
       sudo docker cp "$BK/forgejo-pre-image.dump" scrum4me-postgres:/tmp/rollback.dump    # faalt luid als de verse dump er niet is
       LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/rollback.dump)          # eigen exit van pg_restore telt (set -e)
       [ -n "$LIST" ]                                                                       # niet-lege inhoudslijst of STOP
     )
     rc=$?
     [ "$rc" -eq 0 ] || { echo "verse dump ontbreekt of onbruikbaar (exit $rc) — STOP, database NIET hernoemen, escaleer naar JP"; false; }
     ```
  3. **Alleen na een groene stap 2:** de gemigreerde database wordt **hernoemd**, niet gedropt (forensisch onderzoek):
     ```sh
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE forgejo RENAME TO forgejo_failed_15_0_9"'
     docker exec scrum4me-postgres sh -c 'pg_restore -U "${POSTGRES_USER:-postgres}" -d postgres --create --exit-on-error /tmp/rollback.dump'
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -Atc "select datname from pg_database"'   # verwacht: forgejo én forgejo_failed_15_0_9
     docker exec scrum4me-postgres rm /tmp/rollback.dump
     ```
     `ALTER DATABASE … RENAME` vereist dat niemand op `forgejo` verbonden is (de forge is gestopt). `pg_restore --create` maakt de database met de in het archief vastgelegde eigenschappen opnieuw aan; `-d postgres` is alleen de onderhoudsverbinding.
  4. Volume terug: `sudo rsync -aHAX --numeric-ids --delete "$BK/data/" "$VOL/"` (bevat de `app.ini` van ná 2.5 én de Fase 3-writes; wil JP ook de configuratie terug, dan daarna `app.ini.pre` kopiëren zoals in R2).
  5. Tag terug en bewijzen dat `$CF` weer byte-gelijk is aan 2.4: `sudo sed -i 's|image: codeberg.org/forgejo/forgejo:15.0.9$|image: codeberg.org/forgejo/forgejo:15.0.2|' "$CF"; [ "$(sha256sum "$CF" | cut -d' ' -f1)" = "$PRE_CF" ] && echo "COMPOSE TERUG OP PRE_CF" || { echo "COMPOSE WIJKT AF VAN PRE_CF — STOP, JP"; false; }` → daarna `docker compose -f "$CF" up -d --no-deps forgejo`.
  6. Controles 3.1/3.2 op 15.0.2 + `doctor check --all` → dan Fase 5 (pool herstellen, uitkomst `rolled_back`). Bevinding, logs en de naam `forgejo_failed_15_0_9` naar JP; het onderzoek bepaalt of en wanneer een tweede poging volgt.
- **Fase 5 faalt (runner komt niet online, trust rood, smoke rood):** dit is een poolbevinding, geen reden om de forge terug te zetten. Legacy runner en controller volgen runbook §9 ("als iets misgaat"); JP beslist.

---

## Bevindingen buiten scope (voor JP)

- **Maintenance-record niet armbaar.** `MaintenanceRecord` bestaat in `forgejo_runner_cycle.py` en is getest (`tests/test_cycle_maintenance.py`), maar `cycle_runtime.py`, `cycle_adapters.py`, `forgejo-runner-cycle.service` en `controller.toml.example` bieden geen manier om er een te laden. Daarmee zijn stap F punt 12 (`migratieontwerp.md` §8) en de Global Constraint "control-plane-impact vereist een gearmd maintenance-record" uit het stap-G-plan op dit moment niet door een mechanisme af te dwingen. Dit plan omzeilt dat met een geplande stop plus een **handmatig gereproduceerd §7.9-nulbewijs** (2.2–2.3: stop → wachten → offline → twee jobsnapshots zonder assigned/running job); stap F heeft een echte oplossing nodig (laadpad in `controller.toml` of een bestandspad dat de runtime pollt), zodat de controller dit nulbewijs zelf in `DRAINING` levert in plaats van de operator met de hand.
- **Forgejo 17 en Runner 13** blijven buiten dit plan: 17.0 volgt eind oktober via een eigen onderzoek en plan (JP 30 sep; in voorbereiding op branch `claude/forgejo-17.0-plan`), Runner 13 blijft fase 2 (`migratieontwerp.md` §12).
- **Losse kopie in de compose-map.** `docker-compose.yml.bak-throttle-20260928T172338Z` in `/srv/scrum4me/forgejo` is van een andere sessie (`docs/runbooks/evidence/2026-09-28-compose-git-init.md:45`); dit plan laat hem staan. Opruimen hoort bij de compose-opruiming van ISS-5.

---

## Zelf-review (grondslag-dekking)

- **Upgrade-guide:** backup (2.4/2.7, Gate 2), `doctor check --all` vooraf (0.4, 2.6) en achteraf (4.5), `flush-queues` (2.6), verificatie via webinterface (4.6), loglevel-troubleshooting alleen bij een STOP.
- **Onderzoek §2 / §7.9:** service-gebonden compose (Global Constraints, 4.3), control-plane-drain in §7.9-volgorde (2.1 pauze → 2.2 stop + `fetch_timeout`+10 s + offline → 2.3 job-nulbewijs via `/api/v1/admin/actions/runners/jobs`, 0.12 toetst die bron), trust-timer (0.7, 5.2), geen versiepin in de probe (5.2 bewijst herstel op `VNOW`).
- **Onderzoek §3/§6:** trusted proxies (0.11, 2.5a, 3.3), secretrotatie met luide faaltak (2.4 vingerafdruk, 2.5b, 3.4, 0.10 impact), `T_requeue` blijft geldig (6.2).
- **Data-integriteit:** koud rollbackpunt vóór wijziging (2.7, Gate 2) én een vers **paar** (DB-dump + volume) met de forge gestopt vóór de image-recreate (4.1); beide worden in een **losstaande** `set -e`-subshell genomen met `rc=$?` erna, zodat de `pg_restore --list`-verificatie (via `LIST=$(…)`, diens eigen exit, niet die van `wc`) hard afbreekt — géén `( … ) && … || …`, dat zou de `set -e` onderdrukken. Write-fence over het venster (1.4) met expliciet restrisico ter aftekening (Gate 4). R4 herstelt uitsluitend naar het verse paar met `sudo docker cp` (geen onprivileged `[ -f ]`-selectie), verwijdert eerst een stale `/tmp/rollback.dump` en verifieert de dump als harde voorwaarde vóór `ALTER DATABASE`; geen terugval op de 2.7-dump (na de 4.1-rsync mismatcht die met het volume).
- **Shell-robuustheid:** alle zes fail-gates (2.3, 2.5b, 2.7, 4.1, 4.2, R4) gebruiken hetzelfde patroon — losstaande `( set -e … )`, dan `rc=$?`, dan branchen met een `false` op rood — omdat bash `set -e` binnen een subshell negeert zodra die in een `&&`/`||`-lijst of `if`-conditie staat. Geverifieerd met `bash -n` én een runtime-injectietest.
- **Uitkomstsymmetrie:** Fase 5/Gate 5 gelden voor `VNOW` (15.0.9 upgrade / 15.0.2 rollback); elke terugweg (R2/R3/R4) eindigt in Fase 5 met uitkomst `rolled_back`.
- **Geen placeholders:** elk commando is concreet; enige in te vullen waarden zijn `SUBNET` (0.11) en de tijdstempels. **Geen secrets:** waarden blijven in de container of in de root-only `$BK`; de UUID-regel wordt door de 6.1-grep gehandhaafd, niet door `secret-scan.sh`.
- **Consistentie:** `RID`/`DID` (2.6 → 4.3), `PRE_SECRETS`/`POST_SECRETS` (2.4 → 2.5b → 3.4), `T0`/`TSTOP`/`TEND` (2 → 5.4), `VNOW` (5-intro → 5.2/5.3/Gate 5), `PRE_CF` (2.4 → 4.2 → R4 stap 5), `GIT_CF` (0.13 → 2.4 → 6.2), takkeuze 3.3 vastgelegd in 0.8 en `venster.md`.

## Uitvoerhandoff

Volgorde: (1) **plan-review** — dubbel GO op 9 september voor doel 15.0.7 (`scrum4me-server:claude` en `mac:codex`), gevolgd door de **delta-review** van de omzetting naar 15.0.9 (één cross-model reviewer, codex; zie "Delta 30 september 2026"); (2) **JP-gate**; (3) **Scrum4Me-ceremonie** op product `cmsx8zbdh0002hk7rcgxxr00k` (sprint → PBI → story → taken per fase, met de commando's en gates uit dit plan gekopieerd) → hardstop; (4) uitvoering uitsluitend na een afzonderlijke opdracht van JP, in een door JP gepland venster, niet gelijktijdig met stap F/G of de compose-opruiming van ISS-5.

## Review record

Plan-fase van de review-loop (twee onafhankelijke cross-model reviewers, JP-armd; zij zien elkaars output niet). Persistente loop-staat.

- **Onder review:** dit plan + `forgejo-upgrade-onderzoek-2026-09.md`, tegen de Forgejo upgrade-guide, `migratieontwerp.md` §7.7/§7.9/§9, `evidence/stap-d/bring-up-runbook.md` §5–§7, `implementatieplan-stap-g.md` B3/C3 en de as-built bundel `forgejo-runner/`.
- **Scope-noot voor reviewers:** de keuze 15.0.7 in plaats van 16.0.3 en het uitstel van Runner 13 zijn onderbouwd in het onderzoek (§3–§5) en liggen bij JP; wél in scope: of het plan de drain, het rollbackpunt, de twee gates en de terugwegen correct en volledig uitvoert, en of elke boomclaim klopt.

### Ronde 1 — 2026-09-09 — **NO-GO** (dubbel)
- **Reviewers:** `scrum4me-server:claude` (ops-routed: verifieerde `$CF`, `app.ini`-sleutelnamen en containers op de host zelf; 0 BLOCKER · 1 MAJOR · 3 MINOR) + `mac:codex` (statische review; 3 BLOCKER · 2 MAJOR · 1 MINOR). Beide **NO-GO**.
- **Convergente bevinding (beide, onafhankelijk):** de drain plaatste het nulbewijs (2.2) vóór de nette stop (2.3), en `capture-forgejo-records.sh` haalt alleen `/api/v1/admin/actions/runners` op — het kan "geen assigned/running job" (§7.9) principieel niet aantonen. Geverifieerd: `capture-forgejo-records.sh:20,36` (alleen runnerstatus), `migratieontwerp.md` §7.9 (volgorde stop → wachten → offline → jobsnapshots). **Fix:** Fase 2 herordend (2.2 stop + `fetch_timeout`+10 s + offline; 2.3 job-nulbewijs via `/api/v1/admin/actions/runners/jobs`, endpoint bevestigd via de Forgejo-API-swagger en getoetst in 0.12); QUARANTINED/`min(T_requeue+30 s,10 min)`-remedie opgenomen; ook de legacy runner moet nul assigned/running tonen.
- **Alle 6 bevindingen bevestigd tegen de boom en verwerkt (geen enkele afgewezen):**
  - *(codex BLOCKER)* compose-tak maakt `$CF`-wijziging pas effectief bij recreate, niet bij `docker start` → 3.1 compose-tak nu `docker compose up -d --no-deps forgejo` (image nog 15.0.2), R2/R3 idem. Contextnoot: `scrum4me-server:claude` mat dat op déze host de app.ini-tak geldt (env-var niet in `$CF`), dus dit was latent; de compose-tak is nu correct voor het geval hij ooit actief is.
  - *(codex BLOCKER)* R4 `docker cp` uit root-only `$BK` zonder `sudo` → `sudo docker cp` + geverifieerde dump als harde voorwaarde vóór `ALTER DATABASE`; kopiepad getoetst in 1.1.
  - *(codex MAJOR)* geen write-fence na het koude rollbackpunt → expliciete write-fence over het venster (1.4), vers rollbackpunt met forge gestopt vóór 4.3 (4.1), restrisiconoot ter aftekening door JP (Gate 4).
  - *(codex MAJOR)* Fase 5/Gate 5 accepteerden alleen 15.0.7 → uitkomstafhankelijk gemaakt met `VNOW`; elke rollback eindigt met uitkomst `rolled_back`.
  - *(claude MINOR)* 5.2 vergeleek epoch met ISO → mechanische vergelijking met exitcode.
  - *(claude MINOR)* vingerafdrukcheck 2.5b faalde stil → luide faaltak (`|| { echo …; false; }`).
  - *(claude MINOR)* `secret-scan.sh` handhaaft de UUID-regel niet → herattribueerd naar de 6.1-grep; bestaande stap-A-uuid-kolom als out-of-scope aan JP.
  - *(codex MINOR)* secret-scan-glob sloeg `fase0/` over → 6.1 scant nu recursief via `find`.
- **Verdicts:** `scrum4me-server:claude` NO-GO · `mac:codex` NO-GO.

### Ronde 2 — 2026-09-09 — **NO-GO** (dubbel)
- **Reviewers:** `scrum4me-server:claude` (0 BLOCKER · 1 MAJOR · 0 MINOR) + `mac:codex` (2 BLOCKER · 0 MAJOR · 2 MINOR). Beide bevestigden dat **alle zes ronde-1-fixes correct gesloten** zijn, elk tegen de boom/host/live-API geverifieerd (o.a. `GET /api/v1/admin/actions/runners/jobs` → 200, onbekend pad → 404; `RunJobList`→`ActionRunJob` met plat string-`status` uit de instance-swagger; `VNOW`-regex op de echte `forgejo --version`). De nieuwe bevindingen waren de spiegel van de R4-fix: de dumpverificatie ontbrak op de plekken die de dump maken/kiezen.
- **Bevindingen bevestigd tegen de boom en verwerkt (geen enkele afgewezen):**
  - *(codex BLOCKER)* 2.3-nulbewijs faalde-open: `--fail-with-body` + `;`-geketende `Q`-calls + een `walk` die alleen string-`status` telt → een JSON-errorobject gaf vals `0 []`. Gereproduceerd door codex. **Fix:** subshell met `set -e` (niet-2xx-fetch stopt), validator eist een lijst-toplevel (errorobject → exit 2) en telt elke ontbrekende/niet-string/niet-terminale status als actief.
  - *(codex BLOCKER)* R4 koos door de onprivileged `[ -f "$DUMP" ]` op de `0700 root`-map altijd de oude 2.7-dump, terwijl `$BK/data` al de verse 4.1-volume was → gemengd, inconsistent paar. **Fix:** R4 gebruikt uitsluitend het verse paar (`sudo docker cp` zonder `[ -f ]`-test, subshell); oude-dumpfallback verwijderd; Rollback-intro en 4.1-prose gecorrigeerd (2.7 = enkel Gate-2-bewijs).
  - *(claude MAJOR)* 2.7 en 4.1 verifieerden de dump met `pg_restore --list | wc -l` in een `&&`-keten → pijplijn-exit is die van `wc`, geen `pipefail` → onbruikbaar archief glipte door. **Fix:** beide in een `set -e`-subshell met een expliciete `[ … -gt 0 ]`-gate; 4.1 is nu een harde STOP vóór 4.2.
  - *(codex MINOR)* luide rotatiecheck (2.5b) gaf tóch blok-exit 0 (`false` sluit de shell niet). **Fix:** subshell met `set -e`.
  - *(codex MINOR)* nazorg (6.2/6.3/Gate 6) eiste onvoorwaardelijk 15.0.7 ook na rollback. **Fix:** Fase 6 en Gate 6 uitkomstafhankelijk (`upgraded`/`rolled_back`), committekst volgt uitkomst + rotatiebesluit.
- **Verdicts:** `scrum4me-server:claude` NO-GO · `mac:codex` NO-GO.

### Ronde 3 — 2026-09-09 — **NO-GO** (dubbel, convergent)
- **Reviewers:** `scrum4me-server:claude` (1 BLOCKER · 0 MAJOR · 0 MINOR) + `mac:codex` (1 BLOCKER · 0 MAJOR · 0 MINOR). **Beide vonden onafhankelijk exact dezelfde BLOCKER** en reproduceerden hem op bash 5.3.9. Alle overige ronde-2-fixes door beide bevestigd gesloten (validator-Python correct op de volledige fixture-matrix, R4-selectiebug dicht, Fase 6 uitkomstafhankelijk).
- **Convergente BLOCKER — `set -e` in een AND-OR-context wordt genegeerd.** De vijf `( set -e … ) && … || …`-/`( set -e … ) || …`-wrappers uit ronde 2 onderdrukken de `set -e` binnen de subshell (gedocumenteerd bash-gedrag; ook `if ( set -e … )` doet dit). Gevolg: de subshell draait álle commando's en eindigt met de exit van het laatste → 2.3 telde alleen de tweede snapshot, 2.5b/2.7/4.1 meldden `OK` ná een faal, R4 was slechts toevallig veilig. Zelf nagemeten: `( set -e; false; echo X ) && … || …` → `X`/exit 0; **`( set -e; false; echo X ); rc=$?`** → exit 1 (STOP). **Fix:** alle vijf blokken naar een **losstaande** subshell + `rc=$?` + branchen; `pg_restore --list` via `LIST=$(…)` zodat diens eigen exit telt (niet `wc`); R4 verwijdert eerst een stale `/tmp/rollback.dump`. Bevestigd met `bash -n` én een runtime-injectietest.
- **Verdicts:** `scrum4me-server:claude` NO-GO · `mac:codex` NO-GO.

### Ronde 4 — 2026-09-09 — **GO** (dubbel) ✅
- **Reviewers:** `scrum4me-server:claude` (0 BLOCKER · 0 MAJOR · 0 MINOR) + `mac:codex` (0 BLOCKER · 0 MAJOR · 0 MINOR). **Beide VERDICT: GO.**
- **Verificatie:** beide toetsten de fix met een **runtime-injectietest op de geëxtraheerde blokken** (niet alleen `bash -n`). `mac:codex`: 38/38 runtimegevallen, 11/11 validator-fixtures, 8/8 sh-blokken geldig; re-run van het ronde-3-harnas bevestigt dat de oude wrappers nog vals-groen zijn en de nieuwe niet. `scrum4me-server:claude`: volledige matrix in beide richtingen — de twee ronde-3-valsgroen-scenario's (2.3 snap1 `running`/snap2 `null`; 2.5b gelijke hash + 2 regels) zijn nu ROOD/STOP, exitcodes onderscheidend (22 fetch / 2 antwoordtype / 1 actieve job), geen regressies, en de hoststand bevestigd (15.0.2, app.ini-tak, `/api/v1/admin/actions/runners/jobs` → `null` bij leeg).
- **Verdicts:** `scrum4me-server:claude` GO · `mac:codex` GO. **Plan-fase van de review-loop gesloten.**
- **Beide reviewers noteren expliciet:** dit GO is géén uitvoeringsautorisatie en vervangt de JP-gate niet.

## Loop-conclusie

De plan-fase is na **vier rondes** dubbel GO (commit `21d103e`). De trechter liep van 8 bevindingen (ronde 1) → 5 (ronde 2) → 1 convergente BLOCKER (ronde 3) → 0 (ronde 4); elke ronde bevestigden beide reviewers de vorige fixes gesloten. Volgende stap: **JP-gate** (Uitvoerhandoff stap 2), daarna pas ceremonie en uitvoering — elk op afzonderlijke opdracht van JP.

## Delta 30 september 2026 — omzetting naar 15.0.9

**Aanleiding.** Het plan is na de GO niet uitgevoerd; de forge draait nog 15.0.2 (gemeten 28 sep via `/api/v1/version`). Sindsdien zijn 15.0.8 en 15.0.9 verschenen, elk met een als *Critical* gepubliceerde RCE-fix (PR #14302, #14371; nagelezen in `release-notes-published/15.0.8.md` en `15.0.9.md`). JP-besluit 30 september: eerst 15.0.9, eind oktober 17.0.

**GO-basis en delta.** Inhoud met dubbel GO: commit `21d103e`. De delta is `git diff -M 21d103e..HEAD -- docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.7.md docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.9.md` (het bestand is hernoemd).

| # | Wijziging | Waarom | Waar |
|---|---|---|---|
| D1 | Doelversie 15.0.7 → 15.0.9: imagetag, paden, evidence-map, databasenaam bij R4, branch- en commitnamen; bestand hernoemd. Het review record hierboven noemt 15.0.7 zoals het toen was | JP-besluit; nieuwste LTS-patch | hele operationele deel |
| D2 | Grondslag noemt de twee *Critical*-fixes | reden voor het doel | Spec / grondslag |
| D3 | 0.2 toetst de compose-regels op inhoud, niet meer op de regelnummers van 9 sep | op 28 sep verscheen een kopie van een andere sessie in de map (`docs/runbooks/evidence/2026-09-28-compose-git-init.md:45`); regelnummers zijn geen houdbare toets | 0.2, Gate 0, 4.2 |
| D4 | Geen losse kopie van `$CF` meer: sha256 `PRE_CF` in 2.4, tagwissel met teruggerekende hash in 4.2, hashcontrole bij terugzetten in R4 stap 5 | hostregel "Compose-bestanden wijzigen" (design van 28 sep, §4 B2) verbiedt losse kopieën | Global Constraints, 2.4, Gate 2, 4.2, R4 stap 5 |
| D5 | Compose-tak geschrapt: `FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES` in `$CF` is nu een STOP in 0.2 | de tak was latent (ronde 1: op de host geldt de app.ini-tak) en zijn terugweg was een losse kopie; schrappen is kleiner dan een nieuwe snapshotprocedure | 0.2, 2.5a, 3.1, R2, R3 |
| D6 | Compose-map onder git: stand meten, schone werkboom eisen, tagwissel committen volgens de hostregel | de forge-map komt onder git (ISS-5); een vuile werkboom is daar een STOP | 0.13, 2.4, 6.2 |
| D7 | Write-fence gecorrigeerd: er bestaan geautomatiseerde schrijvers (mirror-sync 's nachts; vier applicaties) | de zin "er draaien geen geautomatiseerde schrijvers" klopte niet (`scripts/forgejo-mirror/README.md`; inventaris 28 sep) | 0.7, 0.14, 1.4, Gate 0 |
| D8 | Versie-verwachting na de upgrade op het voorvoegsel `15.0.9` | het achtervoegsel van 15.0.9 is niet vooraf gemeten | 4.4, 4.6 |
| D9 | "Bevindingen buiten scope" en Uitvoerhandoff bijgewerkt (17.0 via eigen plan; kopie van een andere sessie blijft staan) | actuele stand | Bevindingen, Uitvoerhandoff |

**Beproefd vóór opname** (tijdelijke mappen, proefwaarden): het hashrecept van D4 met vier afwijkingsgevallen en de git-stappen van D6 — [evidence/forgejo-15.0.9/recept-proef-2026-09-30.md](evidence/forgejo-15.0.9/recept-proef-2026-09-30.md).

**Opnieuw gemeten tegen `main@4d9f873` (30 sep)** — de boomclaims waarop het plan leunt gelden nog: `trust-verdict.json` draagt `ok` en `measured_at` (`forgejo-runner/scripts/publish-trust-verdict.sh:51,67`); de journaalregels `cyclus: scrub ok=` en `cyclus: runner gestart` (`cycle_runtime.py:229,266`); trust-timer 00/06/12/18 + 300 s (`forgejo-runner-trust.timer:12,15`); `marker_path` (`controller.toml.example:17`); `self.maintenance = None` en geen laadpad (`forgejo_runner_cycle.py:229`; geen treffer op `maintenance` in `cycle_runtime.py`, `cycle_adapters.py`, `controller.toml.example`); runnerprofiel `cycle` (`compose.yaml:41`); runbook §5–§7 en §9; `fetch_timeout: 5s`. De Postgres-rolwissel van ISS-38/39 raakt het plan niet: backups lopen via `docker exec` en lokale `trust` (`docs/runbooks/credential-rotation.md`, kaart "Do not break"), en 0.5 bewijst dat pad vóór het venster.

**Ongewijzigd sinds de GO:** drain en nulbewijs (2.1–2.3), rotatie (2.5b), rollbackpunten (2.7, 4.1), R4 stappen 1–4, Fase 5.

### Delta-ronde 1 — 2026-09-30
- **Reviewer:** één cross-model reviewer (codex), JP-armd. Verdict volgt.
