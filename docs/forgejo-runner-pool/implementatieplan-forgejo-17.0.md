# Implementatieplan — Forgejo 15.0.9 → 17.0 op `scrum4me-server`

> **Voor uitvoerders:** dit is een **operator-gedreven onderhoudsactie** op een productiehost, geen code-implementatie. Voer fase voor fase uit met de gate ná elke fase; bij een rode gate: **STOP** (stoppen, uitvoer vastleggen, JP melden — niet forceren, niet de gate versoepelen). Commando's zonder host-label draaien **op `scrum4me-server`** als `janpeter` (docker-groep, `sudo` waar aangegeven); `[max2]`-stappen op `max2`; `[mac]`-stappen op de mac met persoonlijk `FORGEJO_TOKEN`; `[JP]`-stappen zijn JP-only (beheerinterface, besluiten). Alle shellblokken zijn bash.

**Doel:** de live forge `scrum4me-forgejo` van `codeberg.org/forgejo/forgejo:15.0.9` naar de nieuwste **17.0.x** (`$V17`) brengen — nadat een geïsoleerde proefmigratie op een kopie van onze eigen data heeft aangetoond dat de migratie slaagt, hoe lang ze duurt, en dat de trustgate en Runner 12.10.1 tegen 17 werken. Met een vóór de wijziging bewezen rollbackpunt en een netjes gedraind en hersteld runnerpool.

**Uitgangspunt (JP, 30 september 2026):** eerst 15.0.9 via [implementatieplan-forgejo-15.0.9.md](implementatieplan-forgejo-15.0.9.md) (delta-review GO 30 sep), eind oktober 17.0. Dit plan start daarom vanaf een forge die **15.0.9** draait en waarop het 15.0.9-venster de configuratie (trusted proxies, secretrotatie) al heeft afgehandeld. Er zit in dit plan dus geen configuratiestap: alleen de image verandert.

**Architectuur:** drie delen. (1) **Releasegate en read-only metingen** (Fase 0): de finale 17.0-releasenotes tegen de breaking-changematrix van het onderzoek. (2) **Proefmigratie** (Fase R): een kopie van database en volume, gestart met 17 op een intern Docker-netwerk zonder uitgaand verkeer, zonder gepubliceerde poorten en met geheugenlimieten; meet migratieduur, doctor, onze trustgate en een echte `one-job --wait`-cyclus van de gepinde Runner 12.10.1; daarna volledig opgeruimd. (3) **Eén onderhoudsvenster** volgens het patroon van het 15.0.9-plan, zonder diens configuratiefase: drainen → stoppen → koud rollbackpunt → image naar `V17` → pool herstellen. Vensterbudget = 30 min + 2 × de gemeten migratieduur.

**Beproefd vóór de review:** Fase R, het venster (2.4–4.5) en de terugweg R4 zijn op 30 september 2026 letterlijk uit dit plan uitgevoerd in een wegwerpomgeving (Docker-in-Docker op de mac; broninstance 15.0.9 met de productienamen en hetzelfde volumepad; doel het experimentele `17.0-test`-image). Uitvoer, afwijkingen van productie en de fouten die de proef in eerdere versies van het recept vond: [evidence/forgejo-17.0/recept-proef-2026-09-30.md](evidence/forgejo-17.0/recept-proef-2026-09-30.md).

**Tech stack:** Ubuntu 26.04, Docker Engine 29.8.1, Docker Compose 5.5.1 (gemeten op de host op 30 sep door de ops-reviewer; firewallbackend iptables; compose-project `forgejo`), Forgejo rootful image, Postgres 17 (`scrum4me-postgres`, gedeeld met de scrum4me-app), Caddy 2, systemd-cyclecontroller op `max2` (bundel `forgejo-runner/`), Runner 12.10.1.

**Spec / grondslag:** [forgejo-17-onderzoek-2026-09.md](forgejo-17-onderzoek-2026-09.md) (§2 upgradepad, §3 breaking changes B1–B12, §4 inventaris eigen tooling, §5 runnercompatibiliteit, §6 beveiligingsstand); [forgejo-upgrade-onderzoek-2026-09.md](forgejo-upgrade-onderzoek-2026-09.md) §1–§2 (gemeten uitgangssituatie, wat een upgrade hier betekent); [implementatieplan-forgejo-15.0.9.md](implementatieplan-forgejo-15.0.9.md) (dubbel GO 9 sep + delta-GO 30 sep na vijf rondes; dit plan hergebruikt diens drain, rollbackpunt, R4 en shellpatronen — afwijkingen staan per stap benoemd); [upgrade-guide v17](https://codeberg.org/forgejo/docs/src/branch/v17.0/docs/admin/upgrade/index.md); de hostregel "Compose-bestanden wijzigen" (`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md` §4 B2); `migratieontwerp.md` §7.7/§7.9/§9/§12; `evidence/stap-d/bring-up-runbook.md` §5–§7; `implementatieplan-stap-g.md` B3/C3; `CLAUDE.md`-hardstops.

---

## Global Constraints (bindend)

- **Geen secrets in Git.** Geen tokenwaarden, JWT-secrets, wachtwoorden, runner-UUID's of `app.ini`-kopieën in evidence of docs. Backup- en proefmappen op de host zijn root-only (`0700`). De UUID-regel wordt gehandhaafd door de recursieve grep in 6.1 (`secret-scan.sh` sluit UUID's bewust uit). Ook de wegwerpgeheimen van de proef (databasewachtwoord, admin-token, runnertoken — alleen geldig in de wegwerp-database) blijven in `$RH` en verdwijnen in R.7.
- **Compose-project `forgejo` uitsluitend service-gebonden.** Nooit `docker compose down`, `up -d` zonder servicenaam, `--remove-orphans`, `prune` of `-v` in dit project: het bevat naast de forge de legacy runner en DinD (stap-G-plan B3/C3). Toegestaan: `docker compose -f "$CF" up -d --no-deps forgejo`, `docker stop/start scrum4me-forgejo`.
- **Hostregel "Compose-bestanden wijzigen".** Geen losse kopie van een compose-bestand, ook niet in de backupmap: de terugweg voor `$CF` is de omkeerbare tagwissel met een sha256-bewijs (2.4, 4.2, R4). Staat `/srv/scrum4me/forgejo` onder git (0.13), dan begint het werk aan `$CF` met een schone `git status` en eindigt het met een commit volgens die regel (6.2).
- **Proef is geïsoleerd en wegwerpbaar.** De proefcontainers vallen buiten elk compose-project: `docker run` met vaste namen `fj17-rh`, `fj17-rh-db`, `fj17-rh-runner` en kortlevende helpers met `--rm`, op netwerk `fj17-rh-net` (`--internal`: geen route naar buiten), zonder gepubliceerde poorten, met `--memory`-limiet; de proefdatabase staat op het benoemde volume `fj17-rh-pgdata`. `[mirror]` en `[mailer]` staan uit. Reden: de kopie bevat 18 push-mirrors naar GitHub (onderzoek §3 B5) en een proef met internettoegang zou verouderde refs kunnen pushen. De overige crontaken van Forgejo blijven lopen zoals in productie: `[cron] ENABLED` zet de afzonderlijke taken niet uit (ze lezen `[cron.<taak>]`), ze werken alleen op de kopie, en ze draaien in het echte venster na de upgrade ook; de mirrortaak wordt met `[mirror] ENABLED = false` niet geregistreerd. Een intern netwerk is geen afscherming van de host zelf: de beheerhost kan de proefcontainers bereiken, andersom is er geen pad naar productiecontainers of naar buiten. Opruimen gebeurt uitsluitend op die namen, inclusief volumes (`docker rm -f -v`, `docker volume rm fj17-rh-pgdata`); geen `prune`. Ook een afgebroken proef eindigt met R.7.
- **Productiecontext (`CLAUDE.md`).** Host-Dockerdaemon niet herstarten, `/etc/docker/daemon.json` niet wijzigen, geen hostbrede prune. `scrum4me-postgres` wordt niet herstart of gewijzigd; het plan raakt die container alleen met `pg_dump` en, in R4, met `pg_restore`/`ALTER DATABASE` op database `forgejo`. De proef herstelt nooit in `scrum4me-postgres`, alleen in de wegwerpcontainer `fj17-rh-db`.
- **Backup vóór wijziging, bewezen restorepad.** De migratie naar 17 is onomkeerbaar (upgrade-guide); Gate 2 is voorwaarde voor 4.2, en na 4.3 is de enige terugweg het koude paar uit 2.7.
- **Control-plane-onderhoud = pool drainen** (§7.9), zoals in het 15.0.9-plan: de as-built controller kan geen maintenance-record laden, dus nette stop plus handmatig Forgejo-side nulbewijs.
- **Niet gelijktijdig met ander werk op de hosts** (stap F/G, reboots, bundelwijzigingen, Runner 13 / fase 2, de compose-opruiming van ISS-5 in `/srv/scrum4me/forgejo`). `git status --porcelain` van de uitvoerder toont alleen eigen evidence.
- **Releasegate.** Uitvoering pas ná de release van 17.0 en een groene 0.0; een breaking change in de finale notes die niet in onderzoek §3 staat, is een STOP en vraagt een delta-review van onderzoek en plan.
- **Meten, niet aannemen.** Elke waarde uit de onderzoeken (9 en 28 sep) en uit de wegwerpproef van 30 sep wordt in Fase 0 en Fase R op de host opnieuw gemeten; een afwijking is een STOP tot het plan is bijgewerkt.
- **Forge = Forgejo.** Evidence via een branch + PR op `git.jp-visser.nl` (API of `tea`), nooit via GitHub-tooling; uitrol nooit via Forgejo Actions.

Vaste namen in dit plan (op `scrum4me-server`, in elke shell opnieuw zetten):

```sh
CD=/srv/scrum4me/forgejo                                  # compose-map van project "forgejo" (mapnaam)
CF=$CD/docker-compose.yml
VOL=/var/lib/docker/volumes/forgejo_forgejo-data/_data    # forge-datavolume (/data in de container)
S=15.0.9                                                  # startversie, gemeten in 0.1
V17=17.0.N                                                # nieuwste 17.0.x volgens 0.0; image-ID in 1.3
BK=/srv/backups/manual/forgejo-pre-17.0                   # koud rollbackpunt, root-only
RH=/srv/backups/manual/forgejo-proef-17.0                 # proefmigratie, root-only, weg na R.7
RUNNER_IMAGE=code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533   # = forgejo-runner/.env.example:8 (12.10.1)
doctorlog() {            # $1 = container, $2 = logbestand: draait doctor en faalt luid bij een niet-nul exit
  docker exec -u git "$1" forgejo doctor check --all --log-file - > "$2" 2>&1; local rc=$?
  [ "$rc" -eq 0 ] && echo "doctor exit 0 → $2" || { echo "DOCTOR-RUN MISLUKT (exit $rc) — STOP; $2 is onvolledig"; return 1; }
}
doctorschoon() {         # $1 = log: de doctor-uitvoer zonder logregels met tijdstempel en zonder kleurcodes
  grep -v -E '^[0-9]{4}/[0-9]{2}/[0-9]{2} ' "$1" | sed -E 's/\x1b\[[0-9;]*m//g'
}
doctorsamenvatting() {   # V<TAB>check<TAB>OK|ERROR|GEEN-VERDICT per check, I<TAB>check<TAB>regel per [W]/[E]-melding; zonder volgnummers
  doctorschoon "$1" | awk '
    function sluit() { if (o) print "V\t" n "\tGEEN-VERDICT"; o = 0 }
    /^\[[0-9]+\] /    { sluit(); sub(/^\[[0-9]+\] /, ""); n = $0; o = 1; next }
    /^ - \[(W|E)\]/   { print "I\t" n "\t" $0; next }
    /^(OK|ERROR)$/    { if (o) { print "V\t" n "\t" $0; o = 0 }; next }
    END               { sluit() }'
}
doctorvolledig() {       # $1 = log: leesbaar, met verdicts, geen check zonder verdict, en afgesloten met "All done (checks: N)." waarin N = het aantal verdicts
  local v klaar
  [ -r "$1" ] || { echo "DOCTOR ROOD: $1 ontbreekt of is onleesbaar — STOP"; return 1; }
  v=$(doctorsamenvatting "$1" | awk -F'\t' '$1 == "V" { c++ } END { print c + 0 }')
  [ "$v" -gt 0 ] || { echo "DOCTOR ROOD: $1 bevat geen checkverdicts — STOP"; return 1; }
  [ "$(doctorsamenvatting "$1" | awk -F'\t' '$1 == "V" && $3 == "GEEN-VERDICT" { c++ } END { print c + 0 }')" -eq 0 ] \
    || { echo "DOCTOR ROOD: $1 is onvolledig (een check zonder verdict) — STOP"; return 1; }
  klaar=$(doctorschoon "$1" | sed -n -E 's/^All done \(checks: ([0-9]+)\)\.$/\1/p')
  [ "$klaar" = "$v" ] || { echo "DOCTOR ROOD: $1 sluit niet af met \"All done (checks: $v).\" (gevonden: \"${klaar:-niets}\") — de run is niet aantoonbaar volledig — STOP"; return 1; }
}
doctorbaseline() {       # $1 = log: alleen van een volledige run — het aantal checks en elke regel die geen OK-verdict is
  doctorvolledig "$1" || return 1
  echo "checks: $(doctorsamenvatting "$1" | awk -F'\t' '$1 == "V" { c++ } END { print c + 0 }')"
  doctorsamenvatting "$1" | awk -F'\t' '!($1 == "V" && $3 == "OK")'
}
doctortoets() {          # $1 = log vóór, $2 = log na: exit 0 alleen als beide runs volledig zijn en $2 niets nieuws bevat
  local nieuw
  doctorvolledig "$1" || return 1
  doctorvolledig "$2" || return 1
  nieuw=$(awk -F'\t' 'FILENAME == ARGV[1] { gezien[$0] = 1; next } !($0 in gezien) && !($1 == "V" && $3 == "OK")' <(doctorsamenvatting "$1") <(doctorsamenvatting "$2")) \
    || { echo "DOCTOR ROOD: de vergelijking zelf mislukte — STOP"; return 1; }
  [ -z "$nieuw" ] && { echo "DOCTOR OK (volledige run, geen nieuwe bevindingen)"; return 0; }
  printf '%s\n' "$nieuw"; echo "DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP"; return 1
}
```

De `doctor…`-functies zijn dezelfde als in het 15.0.9-plan (daar in de delta-review in vier rondes aangescherpt). Ze bestaan omdat de ruwe doctor-uitvoer niet te vergelijken is: met `--log-file -` staan er logregels met tijdstempels doorheen, en de exitcode van `doctor check` is ook 0 wanneer een check `ERROR` meldt of wanneer doctor na een initialisatiefout voortijdig terugkeert. `doctorlog` dwingt exit 0 af; `doctorvolledig` eist een leesbaar log met verdicts, zonder check zonder verdict, afgesloten met Forgejo's eigen regel `All done (checks: N).` met N gelijk aan het aantal verdicts; `doctorbaseline` en `doctortoets` weigeren een log dat daar niet aan voldoet.

---

## Fase 0 — releasegate en read-only metingen (na 15 oktober, ~30 min, geen impact)

Leg alle uitvoer vast onder `evidence/forgejo-17.0/fase0/` (redactieregels: Fase 6).

- **0.0 Releasegate.** `[mac]` `curl -s https://codeberg.org/api/v1/repos/forgejo/forgejo/releases?limit=10` → `v17.0.N` bestaat, `prerelease: false`; zet `V17`. Lees `release-notes-published/17.0.0.md` t/m `17.0.N.md` op `https://codeberg.org/forgejo/forgejo/src/branch/forgejo/` en de PR's met label `breaking` in milestone "Forgejo v17.0.0": elk item moet in onderzoek §3 (B1–B12) staan of aantoonbaar niet raken (leg per item het oordeel vast in `fase0/releasegate.md`). Een niet-gedekte breaking change → **STOP**, onderzoek + plan bijwerken, delta-review. Het venster valt standaard niet eerder dan 7 dagen na 17.0.0 (`[JP]` kan afwijken). Komt er tussen de proef (Fase R) en het venster een nieuwere 17.0.x uit, dan geldt die als `V17` mits de tussenliggende releasenotes geen breaking change noemen **en de bron geen migratie toevoegt** — releasenotes noemen migraties niet systematisch, dus toets de bron: `curl -s "https://codeberg.org/api/v1/repos/forgejo/forgejo/compare/v<oud>...v<nieuw>" | python3 -c 'import json,sys; print([f["filename"] for f in json.load(sys.stdin).get("files", []) if f["filename"].startswith(("models/forgejo_migrations", "models/gitea_migrations"))])'` → `[]`. Anders R.3–R.6 opnieuw (Fase R op een verse kopie).
- **0.1 Startversie en compose-project.** `docker exec scrum4me-forgejo forgejo --version` → bevat `15.0.9`. Een andere versie is een **STOP**: dit plan start vanaf 15.0.9 met het 15.0.9-venster afgerond (uitkomst `upgraded` in `evidence/forgejo-15.0.9/venster.md`); `[JP]` beslist hoe verder. `docker compose -f "$CF" config --services` → bevat `forgejo`, `runner`, `dind`. `docker compose ls --filter name=forgejo` → project `forgejo` running.
- **0.2 Compose-regels (op inhoud).** `grep -n -E 'image:|depends_on|ports:|container_name' "$CF"` → exact één regel `image: codeberg.org/forgejo/forgejo:15.0.9` (`grep -c 'forgejo/forgejo:' "$CF"` → `1`); de forge-service heeft géén `depends_on`; poort `127.0.0.1:3010:3000`. `stat -c '%U:%G %a' "$CF"`.
- **0.3 Containergebruiker, configpad, gereedschap in de image.** `docker exec scrum4me-forgejo id git`; `docker exec scrum4me-forgejo stat -c '%U:%G %a' /data/gitea/conf/app.ini` → de containergebruiker kan `app.ini` schrijven (Forgejo 17 schrijft het bij een niet-ladend JWT-secret, onderzoek B1). `docker inspect scrum4me-forgejo --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^USER_(UID|GID)='` → waarden (niet geheim; ontbreken = 1000) → `UID0`/`GID0` voor R.2. `docker inspect scrum4me-forgejo --format '{{.HostConfig.RestartPolicy.Name}} {{.Config.Image}}'`. `docker exec scrum4me-forgejo sh -c 'command -v curl'` → een pad (R.3 gebruikt curl in de image).
- **0.4 Doctor vooraf (baseline).** `doctorlog scrum4me-forgejo "$HOME/doctor-pre.log" && doctorbaseline "$HOME/doctor-pre.log"` → `doctor exit 0`, `checks:` met het aantal checks (een `DOCTOR ROOD` hier betekent dat de run onvolledig was: STOP), en daaronder elke regel die geen OK-verdict is (een check met `ERROR`, of een `[W]`/`[E]`-melding): die beoordelen en als baseline vastleggen. Een onbegrepen `ERROR` is een STOP.
- **0.5 Omvang, ruimte, geheugen.** `sudo du -sb "$VOL"`; `PGU=$(docker exec scrum4me-postgres sh -c 'printf %s "${POSTGRES_USER:-postgres}"')`; `docker exec scrum4me-postgres psql -U "$PGU" -d postgres -Atc "select pg_database_size('forgejo')"`; `sudo mkdir -p /srv/backups/manual && df -B1 --output=avail /srv/backups | tail -1` → vrij ≥ **3 ×** (volume + database): rollbackpunt, proefkopie en de herstelde proefdatabase. En de naam die R4 stap 3 aan de gemigreerde database geeft, is nog vrij: `docker exec scrum4me-postgres psql -U "$PGU" -d postgres -Atc "select count(*) from pg_database where datname = 'forgejo_failed_17_0'"` → `0` (bestaat hij al, dan faalt de hernoeming in R4 met *database already exists*; `[JP]` laat hem dan eerst vallen). `grep MemAvailable /proc/meminfo` → ≥ 4 GiB voor de proef (limieten 2 GiB + 1 GiB + 512 MiB + helper); minder → proef in een rustig uur of `[JP]` beslist.
- **0.6 Gereedschap en versies op de host.** `command -v rsync openssl python3`; `docker exec scrum4me-postgres pg_restore --version`; `docker version --format '{{.Server.Version}}'` en `docker compose version --short` → noteren (30 sep: 29.8.1 en 5.5.1).
- **0.7 Timers en tijdzone.** `systemctl list-timers --all --no-pager | grep -i -E 'backup|restic|mirror'` → het venster én Fase R vallen buiten drie slagen: `server-backup.timer` (restic; 30 sep rond 03:30 lokaal), `scrum4me-pg-backup.timer` (rond 03:18 lokaal) en `forgejo-mirror-sync.timer` (02:30 UTC ± 5 min, `scripts/forgejo-mirror/README.md`; na het einde van de zomertijd op 25 oktober is dat 03:30 lokaal). Lees de tijden opnieuw af. De uurlijkse `forgejo-dind-prune.timer` en `worker-logs-prune.timer` tellen niet mee: ze raken de forge en de host-images niet. `[max2]` `systemctl list-timers forgejo-runner-trust.timer --no-pager` en `timedatectl | grep 'Time zone'` → het venster valt buiten 00:00–00:06, 06:00–06:06, 12:00–12:06 en 18:00–18:06 lokale tijd van `max2`.
- **0.9 Runnerrecords vooraf.** `[mac]` `bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-17.0/voor` → twee records (`scrum4me-srv-runner` id 3 en `max2-forgejo-runner-02`), beide `idle`, versie `v12.10.1`. Commit alleen `cut -f1,2,4,5,6,7,10 runners-summary.tsv` (zonder `uuid`-kolom).
- **0.10 OAuth2-applicaties (onderzoek B2).** `[JP]` Site Administration → Applications: OAuth2-applicaties die Forgejo als provider gebruiken? (Inventaris 28 sep: 0 bij `janpeter`.) Zijn er wel, dan beoordeelt `[JP]` of ze tokens zonder `exp`-claim aanbieden.
- **0.12 Jobstatus-endpoint.** `[mac]` `curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") -s -o /dev/null -w '%{http_code}\n' https://git.jp-visser.nl/api/v1/admin/actions/runners/jobs` → `200` (admin-token). `403` → STOP tot een geschikt token beschikbaar is.
- **0.13 Compose-map onder git?** `if [ -d "$CD/.git" ]; then echo GIT_CF=ja; git -C "$CD" status --porcelain; else echo GIT_CF=nee; fi` → noteer `GIT_CF`. Bij `ja` moet de statusuitvoer leeg zijn; een vuile werkboom is volgens de hostregel een STOP. `ls -la "$CD"` → in de evidence, zodat losse kopieën naast `$CF` zichtbaar zijn (30 sep: `GIT_CF=nee` en één kopie `docker-compose.yml.bak-throttle-…` van een andere sessie; dit plan raakt die niet aan, opruimen hoort bij ISS-5).
- **0.14 Push-mirrors — baseline (onderzoek B5/B6).** `[mac]` schema, host, laatste sync en foutvlag per mirror; geen credentials (alleen schema en hostnaam van `remote_address` worden geprint):
  ```sh
  mkdir -p /tmp/fj-17.0
  python3 - > /tmp/fj-17.0/push-mirrors.tsv <<'PY'
  import json, os, urllib.parse, urllib.request
  B = "https://git.jp-visser.nl/api/v1"
  H = {"Authorization": "token " + os.environ["FORGEJO_TOKEN"]}
  def get(p):
      with urllib.request.urlopen(urllib.request.Request(B + p, headers=H), timeout=30) as r:
          return json.load(r)
  repos, page = [], 1
  while True:
      d = get(f"/repos/search?limit=50&page={page}")["data"]
      if not d:
          break
      repos += d; page += 1
  print("repo\tschema\thost\tlast_update\theeft_fout")
  for r in repos:
      for m in get(f"/repos/{r['full_name']}/push_mirrors") or []:
          u = urllib.parse.urlsplit(m.get("remote_address", ""))
          print(r["full_name"], u.scheme, u.hostname, m.get("last_update"), bool(m.get("last_error")), sep="\t")
  PY
  ```
  Verwacht 18 regels `https`/`github.com`. Een `http`- of `git`-schema → STOP (B6: `[JP]` kiest remote aanpassen of `[migrations] ALLOW_UNENCRYPTED`).
- **0.15 Custom server-side git-hooks (B8).** `docker exec scrum4me-forgejo sh -c 'grep -E "^(DISABLE_GIT_HOOKS|ROOT) *=" /data/gitea/conf/app.ini'` (geen `DISABLE_GIT_HOOKS` = default `true`; geen `ROOT` = `/data/git/repositories`). `sudo find "$VOL/git/repositories" -path '*/hooks/*.d/*' -type f ! -name gitea ! -name forgejo | wc -l` (pad aanpassen als `ROOT` afwijkt) → `0`. Meer dan 0 → STOP: `[JP]` beoordeelt of die hooks onder de gecentraliseerde hooks van 16+ nog moeten werken.
- **0.16 Automatische schrijvers (invulling van de write-fence).** Naast de runnerpool schrijven naar Forgejo: de nachtelijke mirror-sync (0.7) en de applicaties `scrum4me-mcp` (PR's, reviews, issue-mirror), `Scrum4Me` (review-dispatch, issue-sync), `scrum4me-docker` (docs-audit-PR's, releasetags) en de review-bot `s4m-codex-reviewer` (onderzoek §4). `[JP]` besluit per schrijver: pauzeren voor het venster, of accepteren onder het restrisico van Gate 4; vastleggen in `venster.md`.
- **0.17 Proefgereedschap.** `PGIMG=$(docker inspect -f '{{.Config.Image}}' scrum4me-postgres)` → lokaal aanwezig (`docker image inspect "$PGIMG" >/dev/null`). `docker image inspect "$RUNNER_IMAGE" >/dev/null` → aanwezig, anders `docker pull "$RUNNER_IMAGE"`. `docker run --rm --entrypoint /bin/sh "$RUNNER_IMAGE" -c 'echo sh-ok; id'` → `sh-ok` en de uid van de runnergebruiker (in de wegwerpproef: uid 1000; R.5 draait de proefjob met de `host`-executor in de runnercontainer). `docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token --help` → vlaggen `--username`, `--token-name`, `--scopes`, `--raw` bestaan (R.3 gebruikt ze uitsluitend tegen de proefinstance).
- **0.18 Actueel trustverdict (vergelijkingsbasis voor R.4).** `[max2]` `sudo journalctl -u forgejo-runner-trust.service -n 30 --no-pager` en `python3 -c 'import json;d=json.load(open("/opt/forgejo-runner/trust-verdict.json"));print(d.get("ok"), d.get("measured_at"))'` → laatste meting groen, met of zonder zachte meldingen; noteer welke. Bepaal ook met welk account de productiescan meet (alleen de naam; het token blijft in het root-only bestand en komt niet in argv): `sudo bash -c 'set -a; . /opt/forgejo-runner/credentials/trust-scan.env; set +a; curl --config <(printf "header = \"Authorization: token %s\"\n" "$FORGEJO_TOKEN") -sS --fail-with-body --max-time 30 https://git.jp-visser.nl/api/v1/user' | python3 -c 'import json,sys; print(json.load(sys.stdin)["login"])'` → `TRUSTUSER`. R.3 maakt het proeftoken voor datzelfde account, zodat R.4 dezelfde repositories ziet als de productiescan.

**Gate 0:** releasegate groen en `V17` vastgesteld; startversie 15.0.9 en compose-regel kloppen; doctor-baseline vastgelegd zonder onbegrepen `ERROR`; ruimte ≥ 3×, geheugen voldoende en de R4-databasenaam vrij; gereedschap aanwezig; venster buiten de drie slagen uit 0.7; beide runnerrecords `idle`; jobstatus-endpoint `200`; `GIT_CF` bekend en de werkboom schoon; push-mirrors alle `https`; 0 custom hooks; schrijversbesluit vastgelegd; proefgereedschap aanwezig; actueel trustverdict bekend. Anders STOP.

---

## Fase R — proefmigratie op een geïsoleerde kopie (dagen vóór het venster, ~1–2 u, geen impact op productie)

Doel: vóór het onomkeerbare venster op onze eigen data bewijzen dat (a) de migratie 15.0.9 → `V17` slaagt en hoe lang ze duurt, (b) doctor schoon is, (c) de trustgate en het runner-recordcontract tegen 17 werken, en (d) Runner 12.10.1 een job via `one-job --wait` kan draaien tegen 17. Productie merkt alleen een online `pg_dump` en een rsync-leeslast. Plan de fase buiten de slagen uit 0.7 (in de praktijk: niet tussen 03:00 en 04:00 lokaal), zodat `$RH` met de proefkopie niet in een restic-snapshot belandt. *Optioneel, vóór 15 oktober:* dezelfde fase met vooraf `IMG=codeberg.org/forgejo-experimental/forgejo:17.0-test` als vroege waarschuwing op de echte data; dat telt niet als Gate R.

- **R.0 Opzet.** Eerst een schone lei: `docker ps -a --filter name=fj17 --format '{{.Names}}'`, `docker network ls --filter name=fj17 --format '{{.Name}}'` en `docker volume ls -q --filter name=fj17` → alle drie leeg, en `sudo test -e "$RH"` → bestaat niet. Staat er nog iets van een eerdere, afgebroken proef, dan eerst R.7: een overgebleven `fj17-rh-pgdata` zou anders stil als database van de nieuwe proef worden hergebruikt.
  ```sh
  sudo install -d -m 0700 -o root -g root "$RH" "$RH/data" "$RH/runner" "$RH/trust"
  docker network create --internal fj17-rh-net
  docker network inspect fj17-rh-net --format '{{.Internal}}'      # → true, anders STOP
  docker volume ls -qf dangling=true | sort > /tmp/fj17-dangling-voor.txt     # vergelijkingsbasis voor R.7
  ```
  `[mac]` de trustgate-bestanden (geen geheimen) naar de host, met de SSH-alias `scrum4me-srv` uit `~/.ssh/config`: `ssh scrum4me-srv mkdir -p /tmp/fj17-bundle && scp forgejo-runner/scripts/trust_scope.py forgejo-runner/scripts/trust_scope_cli.py forgejo-runner/trusted-actions-scope.yml forgejo-runner/labels.txt scrum4me-srv:/tmp/fj17-bundle/` vanaf de checkout op de SHA die `max2` draait (`[max2]` `cat /opt/forgejo-runner/BUNDLE_COMMIT`; `git checkout <die SHA> -- <de vier bestanden>` in een tijdelijke worktree als `main` inmiddels afwijkt). Helper-image: `docker pull python:3.13-slim && docker image inspect python:3.13-slim --format '{{index .RepoDigests 0}}'` → digest vastleggen.
- **R.1 Kopie van database en volume** (online; de kopie is warm, dus database en volume kunnen enkele seconden uiteenlopen — voor een proef aanvaardbaar, voor een rollbackpunt niet; daarom werkt Fase 2 koud):
  ```sh
  ( set -e
    docker exec scrum4me-postgres sh -c 'pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -f /tmp/forgejo-proef.dump forgejo'
    LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/forgejo-proef.dump)
    [ -n "$LIST" ]
    sudo docker cp scrum4me-postgres:/tmp/forgejo-proef.dump "$RH/forgejo-proef.dump"
    docker exec scrum4me-postgres rm /tmp/forgejo-proef.dump
    time sudo rsync -aHAX --numeric-ids "$VOL/" "$RH/data/"
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "PROEFKOPIE OK" || { echo "PROEFKOPIE MISLUKT (exit $rc) — STOP"; false; }
  ```
- **R.2 Wegwerp-Postgres en restore.** Eigen databasewachtwoord alleen voor de proef, in env-bestanden (niet in argv); de forge-proef krijgt de databaseverbinding en het uitzetten van mirrors en mail via env, dat de entrypoint ook bij een bestaand `app.ini` in de **kopie** schrijft (`environment-to-ini` in de s6-setup; productie zet zijn `FORGEJO__database__*` op dezelfde manier). De proefdatabase krijgt een **benoemd** volume: het image `postgres:17` declareert `VOLUME /var/lib/postgresql/data`, en zonder naam zou een anoniem volume met de herstelde database `docker rm` overleven. Zou de env-override onverhoopt niet werken, dan wijst de kopie naar `scrum4me-postgres:5432`, een naam die op het proefnetwerk niet bestaat: de start faalt dan, hij raakt productie niet.
  ```sh
  PGIMG=$(docker inspect -f '{{.Config.Image}}' scrum4me-postgres)
  sudo sh -c 'umask 077; pw=$(openssl rand -hex 24)
    printf "POSTGRES_USER=forgejo\nPOSTGRES_DB=forgejo\nPOSTGRES_PASSWORD=%s\n" "$pw" > "$1/pg.env"
    printf "FORGEJO__database__DB_TYPE=postgres\nFORGEJO__database__HOST=fj17-rh-db:5432\nFORGEJO__database__NAME=forgejo\nFORGEJO__database__USER=forgejo\nFORGEJO__database__PASSWD=%s\nFORGEJO__mirror__ENABLED=false\nFORGEJO__mailer__ENABLED=false\nUSER_UID=%s\nUSER_GID=%s\n" "$pw" "$2" "$3" > "$1/fj.env"' _ "$RH" "$UID0" "$GID0"
  ( set -e
    sudo docker run -d --name fj17-rh-db --network fj17-rh-net --memory 1g --env-file "$RH/pg.env" -v fj17-rh-pgdata:/var/lib/postgresql/data "$PGIMG"
    timeout 180 sh -c 'until docker exec fj17-rh-db pg_isready -h 127.0.0.1 -U forgejo -d forgejo >/dev/null 2>&1; do sleep 2; done'
    sudo docker cp "$RH/forgejo-proef.dump" fj17-rh-db:/tmp/p.dump
    docker exec fj17-rh-db pg_restore -U forgejo -d forgejo --no-owner --no-acl --exit-on-error /tmp/p.dump
    docker exec fj17-rh-db rm /tmp/p.dump
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "PROEF-DB OK" || { echo "PROEF-DB MISLUKT (exit $rc) — STOP"; false; }
  ```
  `pg_isready -h 127.0.0.1` (TCP) en niet via de socket: tijdens de initialisatie luistert de tijdelijke server van het officiële image alleen op de socket.
- **R.3 Forgejo `V17` op de kopie — migratieduur meten.**
  ```sh
  IMG=${IMG:-codeberg.org/forgejo/forgejo:$V17}     # vroege proef: vooraf IMG=codeberg.org/forgejo-experimental/forgejo:17.0-test zetten
  docker pull "$IMG"
  T_START=$(date +%s)
  sudo docker run -d --name fj17-rh --network fj17-rh-net --memory 2g --env-file "$RH/fj.env" -v "$RH/data:/data" "$IMG"
  ( set -e
    until docker exec fj17-rh curl -sf -m 5 http://localhost:3000/api/v1/version >/dev/null 2>&1; do
      [ "$(docker inspect -f '{{.State.Running}}' fj17-rh)" = true ]      # container gestopt = migratie gefaald → exit
      [ $(( $(date +%s) - T_START )) -lt 3600 ]                            # na een uur: STOP
      sleep 5
    done
  )
  rc=$?
  MIG=$(( $(date +%s) - T_START )); echo "migratie + start: ${MIG}s"
  [ "$rc" -eq 0 ] && docker exec fj17-rh curl -s http://localhost:3000/api/v1/version \
    || { echo "PROEF-START MISLUKT (exit $rc) — STOP; docker logs fj17-rh bewaren"; false; }
  ```
  → versie `V17`; `MIG` noteren (door de 5 s-lus een bovengrens). Isolatie bewijzen, op naam én op IP-adres: `docker exec fj17-rh sh -c 'curl -s -m 5 -o /dev/null https://codeberg.org; echo "curl-dns-exit=$?"; curl -s -m 5 -o /dev/null https://1.1.1.1; echo "curl-ip-exit=$?"'` → beide ≠ 0 (in de wegwerpproef 6 en 7); `docker port fj17-rh` → leeg. Effectieve instellingen in de kopie: `docker exec fj17-rh awk '/^\[/{s=$0} (s=="[mirror]"||s=="[mailer]") && /^ENABLED/{print s, $0}' /data/gitea/conf/app.ini` → `[mirror] ENABLED = false` en `[mailer] ENABLED = false`. Token **alleen voor de proefinstance** (staat alleen in de wegwerp-database), voor het account van de productiescan, via een pipe naar een root-only bestand: `docker exec -u git fj17-rh forgejo admin user generate-access-token --username "$TRUSTUSER" --token-name proef --scopes all --raw | sudo tee "$RH/proef.token" >/dev/null && sudo chmod 0600 "$RH/proef.token"` (`TRUSTUSER` uit 0.18).
- **R.4 Doctor en onze consumenten tegen 17.**
  - `doctorlog fj17-rh "$HOME/proef-doctor.log" && doctortoets "$HOME/doctor-pre.log" "$HOME/proef-doctor.log"` → `doctor exit 0` en `DOCTOR OK`; bij `DOCTOR ROOD` elke getoonde regel beoordelen, een onverklaarde nieuwe bevinding is een STOP. Op 17 verdwijnt de check "Check if hook files are up-to-date and executable" (sinds 16 gecentraliseerde hooks, onderzoek B8; in de wegwerpproef 28 checks op 15.0.9 en 27 op 17.0-test); een verdwenen check is geen nieuwe bevinding.
  - **Trustgate** (vóór R.5, zodat de proefrepo er nog niet is) in een helpercontainer op het proefnetwerk:
    ```sh
    sudo docker run --rm --network fj17-rh-net --memory 256m -v /tmp/fj17-bundle:/b:ro -v "$RH:/rh" python:3.13-slim \
      sh -c 'FORGEJO_URL=http://fj17-rh:3000 FORGEJO_TOKEN=$(cat /rh/proef.token) \
             python3 /b/trust_scope_cli.py --allowlist /b/trusted-actions-scope.yml --labels /b/labels.txt --out /rh/trust; echo "trust-exit=$?"'
    ```
    → `trust-exit=0` of `10`, en dezelfde uitkomst (groen, of dezelfde zachte meldingen) als het productieverdict uit 0.18. `20`/`30` of een andere uitkomst dan productie → STOP: dan faalt 5.2 in het venster ook.
  - **Runner-records en jobbron** (contract van `capture-forgejo-records.sh` en het nulbewijs uit 2.3):
    ```sh
    sudo docker run -i --rm --network fj17-rh-net --memory 256m -v "$RH:/rh:ro" python:3.13-slim python3 - <<'PY'
    import json, urllib.request
    T = open("/rh/proef.token").read().strip()
    def get(p):
        req = urllib.request.Request("http://fj17-rh:3000/api/v1" + p, headers={"Authorization": "token " + T})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    data = get("/admin/actions/runners")
    runners = data if isinstance(data, list) else data.get("runners", [])   # zelfde acceptatie als capture-forgejo-records.sh
    assert isinstance(runners, list) and len(runners) == 2, f"verwacht 2 runnerrecords, kreeg {str(data)[:200]}"
    for r in runners:
        assert all(isinstance(l, str) for l in (r.get("labels") or [])), "labels geen lijst van strings"
        assert isinstance(r.get("status"), str), "status geen string"
    jobs = get("/admin/actions/runners/jobs")
    assert jobs is None or (isinstance(jobs, list) and all(isinstance(j.get("status"), str) for j in jobs)), "jobbron heeft een andere vorm"
    print("CONTRACT OK:", len(runners), "runners,", 0 if jobs is None else len(jobs), "jobs")
    PY
    ```
    → `CONTRACT OK`. De controle gebruikt dezelfde acceptatie als `capture-forgejo-records.sh` (kale lijst of lijst onder `runners`); een andere vorm zou dat script stil nul regels laten schrijven, en faalt hier luid. `docker run -i` is nodig: zonder `-i` bereikt de heredoc de container niet.
- **R.5 Runner 12.10.1 draait een job tegen 17** (onderzoek §5). Een proefrepo, een runnerrecord en een workflow — alles alleen in de wegwerp-database — en daarna één `one-job --wait`-cyclus met de gepinde productie-image en dezelfde `server.connections`-vorm als `render-config.sh`, maar met de `host`-executor (geen DinD nodig):
  ```sh
  sudo docker run -i --rm --network fj17-rh-net --memory 256m -v "$RH:/rh" python:3.13-slim python3 - <<'PY'
  import base64, json, os, urllib.request
  T = open("/rh/proef.token").read().strip()
  def api(method, p, body=None):
      req = urllib.request.Request("http://fj17-rh:3000/api/v1" + p, method=method,
                                   data=None if body is None else json.dumps(body).encode(),
                                   headers={"Authorization": "token " + T, "Content-Type": "application/json"})
      with urllib.request.urlopen(req, timeout=30) as r:
          raw = r.read()
          return json.loads(raw) if raw else None
  me = api("GET", "/user")["login"]
  api("POST", "/user/repos", {"name": "proef-smoke", "auto_init": True, "private": True})
  api("PATCH", f"/repos/{me}/proef-smoke", {"has_actions": True})
  rec = api("POST", "/admin/actions/runners", {"name": "proef-runner"})
  os.umask(0o077)
  with open("/rh/runner/token", "w") as f:
      f.write(rec["token"])
  with open("/rh/runner/config.yml", "w") as f:
      f.write("runner:\n  capacity: 1\n  timeout: 10m\n  fetch_timeout: 5s\n  fetch_interval: 2s\n"
              "cache:\n  enabled: false\n"
              "server:\n  connections:\n    forgejo:\n      url: http://fj17-rh:3000/\n"
              f"      uuid: {rec['uuid']}\n      token_url: file:/etc/forgejo-runner/token\n"
              "      labels:\n        - proef:host\n")
  wf = "on: [push]\njobs:\n  smoke:\n    runs-on: proef\n    steps:\n      - run: echo proef-smoke-ok\n        shell: sh\n"
  api("POST", f"/repos/{me}/proef-smoke/contents/.forgejo/workflows/smoke.yml",
      {"content": base64.b64encode(wf.encode()).decode(), "message": "proef smoke"})
  print("PROEF-SETUP OK voor", me)
  PY
  # De runner draait in de container als een gewone gebruiker (0.17): de gemounte map moet doorzoekbaar
  # en de twee bestanden leesbaar zijn. $RH zelf blijft 0700 root, dus op de host kan niemand erbij.
  sudo chmod 0755 "$RH/runner" && sudo chmod 0644 "$RH/runner/token" "$RH/runner/config.yml"
  timeout 300 sudo docker run --rm --name fj17-rh-runner --network fj17-rh-net --memory 512m -v "$RH/runner:/etc/forgejo-runner:ro" \
    "$RUNNER_IMAGE" /bin/forgejo-runner -c /etc/forgejo-runner/config.yml one-job --wait; echo "runner-exit=$?"
  ```
  → `runner-exit=0`, met in de uitvoer `declared successfully` en `successfully fetched one task` (bij een `timeout` kan de container blijven draaien; R.7 verwijdert hem op naam). Daarna de runstatus (zelfde responsvorm-tolerantie als `pick-heaviest-workflow.py`):
  ```sh
  sudo docker run -i --rm --network fj17-rh-net --memory 256m -v "$RH:/rh:ro" python:3.13-slim python3 - <<'PY'
  import json, sys, urllib.request
  T = open("/rh/proef.token").read().strip()
  H = {"Authorization": "token " + T}
  me = json.load(urllib.request.urlopen(urllib.request.Request("http://fj17-rh:3000/api/v1/user", headers=H)))["login"]
  d = json.load(urllib.request.urlopen(urllib.request.Request(f"http://fj17-rh:3000/api/v1/repos/{me}/proef-smoke/actions/runs", headers=H)))
  runs = d.get("workflow_runs", d.get("runs", d.get("data"))) if isinstance(d, dict) else d
  st = [r.get("status") for r in (runs or [])]
  print("runs:", st)
  sys.exit(0 if st and st[0] == "success" else 1)
  PY
  ```
  → exit 0 (`success`). Faalt R.5 op **opzet** (repo, record, workflow of image), dan is dat geen protocolbewijs: bevinding vastleggen, `[JP]` beslist of het venster zonder R.5 mag (dan is 5.3 het eerste protocolbewijs, ná de onomkeerbare migratie). Faalt de **job** of de runnercyclus zelf, dan is dat een STOP: Runner 12.10.1 werkt dan niet tegen 17 en het plan moet eerst Runner 13 of een andere volgorde uitwerken (JP).
- **R.6 Logs.** `docker logs fj17-rh 2>&1 | grep -E '\[F\]|panic|creating new key'` → leeg; `creating new key` zou betekenen dat een JWT-secret niet is geladen en is vervangen (onderzoek B1). `docker logs fj17-rh 2>&1 | grep -c '\[E\]'` → elke `[E]`-regel verklaard in de evidence (in de wegwerpproef: 0; een fout van een taak die naar buiten wil, zoals de update-checker, is een verwacht gevolg van de isolatie); onverklaard → STOP.
- **R.7 Opruimen.**
  ```sh
  docker rm -f -v fj17-rh fj17-rh-db                              # -v: ook de anonieme volumes van deze containers
  docker rm -f -v fj17-rh-runner 2>/dev/null || true              # bestaat alleen na een afgebroken R.5
  docker volume rm fj17-rh-pgdata                                 # de herstelde proefdatabase
  docker network rm fj17-rh-net
  sudo rm -rf "$RH" /tmp/fj17-bundle
  docker ps -a --filter name=fj17 --format '{{.Names}}'               # → leeg
  docker network ls --filter name=fj17 --format '{{.Name}}'           # → leeg
  docker volume ls -q --filter name=fj17                              # → leeg
  diff <(docker volume ls -qf dangling=true | sort) /tmp/fj17-dangling-voor.txt && echo "GEEN NIEUW DANGLING VOLUME"
  ```
  Toont de `diff` een verschil, dan is er een naamloos volume bijgekomen (of verdwenen) sinds R.0: beoordelen of het van de proef is en alleen dán dat ene volume op naam verwijderen — geen `prune`; volumes van andere sessies blijven staan. R.7 geldt ook na een afgebroken proef: de stappen falen dan deels op "bestaat niet", de controles eronder beslissen. `/tmp/fj17-dangling-voor.txt` (alleen volumenamen) gaat naar de evidence en wordt daarna verwijderd. De images (`$IMG`, `python:3.13-slim`) blijven staan; `$IMG` is in 1.3 toch nodig.

**Gate R:** `PROEFKOPIE OK`, `PROEF-DB OK`, 17 draait op de kopie met versie `V17`, `MIG` vastgelegd; isolatie bewezen; `doctor exit 0` en `DOCTOR OK` (of alleen verklaarde bevindingen); trustgate gelijk aan productie; `CONTRACT OK`; runnerjob `success` (of een vastgelegd JP-besluit over een opzetfout in R.5); logs zonder `[F]`/panic/*creating new key*; opgeruimd (geen container, netwerk of volume met `fj17` in de naam, `GEEN NIEUW DANGLING VOLUME`, `$RH` weg). Leg vast in `evidence/forgejo-17.0/proef.md`: `MIG`, versie, image-digest, doctor-verschillen, trust-exit, vorm van `/admin/actions/runners`, R.5-uitkomst. Anders STOP — geen venster.

---

## Fase 1 — voorbereiden zonder downtime (uren tot een dag vóór het venster)

- **1.1 Backupmap + R4-kopiepad.** `sudo mkdir -p "$BK" && sudo chmod 0700 "$BK" && sudo chown root:root "$BK"`. `echo pad-test | sudo tee "$BK/.cptest" >/dev/null && sudo docker cp "$BK/.cptest" scrum4me-postgres:/tmp/.cptest && docker exec scrum4me-postgres rm /tmp/.cptest && sudo rm "$BK/.cptest"` → exit 0. `[JP]` ter kennis: de nachtelijke restic-run neemt heel `/srv` mee, dus `$BK` komt de zeven dagen van 6.5 in de snapshots op de NAS en in B2 (Object Lock) terecht; accepteren of vooraf een exclude laten toevoegen (buiten dit plan).
- **1.2 Warme kopie van het volume:** `time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"` → exit 0; duur en `sudo du -sb "$BK/data"` noteren.
- **1.3 Image vooraf.** `docker pull codeberg.org/forgejo/forgejo:$V17 && docker image inspect codeberg.org/forgejo/forgejo:$V17 --format '{{.Id}} {{index .RepoDigests 0}}'` → `IMGID17` (het image-ID) en de digest vastleggen; 4.3 toetst ertegen.
- **1.4 Venster vastleggen + write-fence.** `[JP]` datum/tijd (UTC én lokaal), duur **30 min + 2 × `MIG`** (afgerond op hele minuten), buiten de 0.7-slagen; aankondiging aan wie de forge gebruikt. De forge is het hele venster (`T0` → Gate 5) in onderhoud en neemt geen schrijfacties aan; alleen operator en JP verifiëren gates. Geautomatiseerde schrijvers bestaan (0.16): de runnerpool is gedraind (2.1–2.3), het venster ligt buiten de mirror-sync, en voor de overige schrijvers geldt JP's 0.16-besluit.
- **1.5 Rollbacktijd schatten.** Uit 0.5 en 1.2: koude delta (2.7) in minuten; de R4-restore (`pg_restore` + rsync terug) past binnen het resterende venster na de R4-beslisgrens (Gate 4). Past het niet, dan verlengt JP het venster vóóraf.

**Gate 1:** Gate R groen; `$BK/data` gevuld en rsync exit 0; image `V17` lokaal met vastgelegd ID en digest; venster gepland en aangekondigd met write-fence en schrijversbesluit; R4-kopiepad exit 0; rollbacktijd passend.

---

## Fase 2 — venster openen: drainen, stoppen, rollbackpunt (T+0 … ~T+10)

Noteer `T0=$(date -u +%FT%TZ)` bij de eerste handeling. De nummering volgt het 15.0.9-plan; 2.5 (configuratie) en Fase 3 (configuratie-gate) bestaan hier niet, omdat dit venster alleen de image wisselt.

- **2.1 Pauzeren.** `[JP]` Site Administration → Actions → Runners → `scrum4me-srv-runner` (id 3) → Pause. De schrijvers pauzeren die JP in 0.16 heeft aangewezen.
- **2.2 `[max2]` Controller netjes stoppen (runbook §7), daarna offline-bewijs.** `sudo systemctl stop forgejo-runner-cycle.service; sudo systemctl show forgejo-runner-cycle.service -p ExecMainStatus -p Result` → `ExecMainStatus=0`, `Result=success`; `cd /opt/forgejo-runner && docker compose ps --profile cycle runner` → leeg; `ls /opt/forgejo-runner/state/cycle-op.marker` → bestaat niet. Wacht **≥ 15 s** (`fetch_timeout: 5s` + 10 s, §7.9). `[mac]` `bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out /tmp/fj-17.0/na-stop` → `max2-forgejo-runner-02` `offline`, id 3 niet `active`.
- **2.3 `[mac]` Assignment-nulbewijs (§7.9)** — ongewijzigd uit het 15.0.9-plan (in de plan-review van 9 sep in twee rondes aangescherpt en met runtime-injectietests bewezen), alleen de map heet `/tmp/fj-17.0`:
```sh
mkdir -p /tmp/fj-17.0
cat > /tmp/fj-17.0/nulbewijs.py <<'PY'
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
# De subshell staat op een eigen regel en wordt NIET gevolgd door && of || en staat niet in
# een `if (...)`: in een AND-OR-lijst of if-conditie negeert bash de `set -e` binnen de
# subshell. Alleen een losstaande subshell gevolgd door `rc=$?` handhaaft hem.
( set -e
  Q > /tmp/fj-17.0/jobs1.json
  sleep 15
  Q > /tmp/fj-17.0/jobs2.json
  python3 /tmp/fj-17.0/nulbewijs.py /tmp/fj-17.0/jobs1.json
  python3 /tmp/fj-17.0/nulbewijs.py /tmp/fj-17.0/jobs2.json
)
rc=$?
[ "$rc" -eq 0 ] && echo "NULBEWIJS SCHOON (beide snapshots leeg)" \
  || { echo "NULBEWIJS ROOD of jobfetch faalde (exit $rc) — STOP, pas §7.9-remedie toe"; false; }
```
  Bij `NULBEWIJS ROOD` geldt §7.9: gepauzeerd blijven, `min(T_requeue + 30 s, 10 min)` wachten (`T_requeue` = 600 s); is de job dan niet aantoonbaar gerequeued of terminaal, dan annuleert `[JP]` de run en dispatcht dezelfde workflow vanaf dezelfde commit opnieuw. Pas ná een schoon nulbewijs mag 2.6 de forge stoppen.
- **2.4 Compose-hash vastleggen.** Van `$CF` komt géén kopie (hostregel): `PRE_CF=$(sha256sum "$CF" | cut -d' ' -f1); echo "$PRE_CF"` → hash in evidence. Bij `GIT_CF=ja` eerst `git -C "$CD" status --porcelain` → leeg, anders STOP.
- **2.6 Doctor + queues, dan stoppen.** `doctorlog scrum4me-forgejo "$HOME/doctor-pre-venster.log" && doctorvolledig "$HOME/doctor-pre-venster.log" && echo "VOORLOG VOLLEDIG"` → `doctor exit 0` en `VOORLOG VOLLEDIG`. Ontbreekt een van beide, dan STOP terwijl de forge nog draait: dit log is de vergelijkingsbasis voor 4.5 én voor R4 stap 6, dus eerst de oorzaak onderzoeken en een geldige verse run opnemen. Pas daarna `docker exec -u git scrum4me-forgejo forgejo manager flush-queues --timeout 2m` → exit 0 (bij een timeout eenmaal herhalen, upgrade-guide). `docker stop -t 90 scrum4me-forgejo`; `docker ps -a --filter 'name=^/scrum4me-forgejo$' --format '{{.Status}}'` → `Exited (…)`. `TSTOP=$(date -u +%FT%TZ)`. `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → beide `running`; ID's bewaren als `RID`/`DID`.
- **2.7 Koud rollbackpunt** (forge gestopt; dit paar — dump én volume — is het enige R4-herstelpunt):
  ```sh
  ( set -e
    docker exec scrum4me-postgres sh -c 'pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -f /tmp/forgejo-pre-17.dump forgejo'
    LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/forgejo-pre-17.dump)
    [ -n "$LIST" ]
    sudo docker cp scrum4me-postgres:/tmp/forgejo-pre-17.dump "$BK/forgejo-pre-17.dump"
    sudo chmod 0600 "$BK/forgejo-pre-17.dump"
    docker exec scrum4me-postgres rm /tmp/forgejo-pre-17.dump
    sudo sha256sum "$BK/forgejo-pre-17.dump"; sudo stat -c '%s' "$BK/forgejo-pre-17.dump"
    time sudo rsync -aHAX --numeric-ids --delete "$VOL/" "$BK/data/"    # koude delta
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "KOUD ROLLBACKPUNT OK" || { echo "KOUD ROLLBACKPUNT MISLUKT (exit $rc) — STOP"; false; }
  ```
  Afwijkingen van het 15.0.9-plan: de dump gaat direct met `sudo docker cp` naar `$BK` (niet via `/tmp` op de host), en er is maar één rollbackpunt — het 15.0.9-plan neemt in zijn 4.1 een tweede, vers punt omdat de forge daar tussen 2.7 en de imagewissel nog een keer draait; hier blijft hij gestopt tot 4.3.

**Gate 2:** `NULBEWIJS SCHOON`; `PRE_CF` vastgelegd; `VOORLOG VOLLEDIG` (2.6); forge gestopt, legacy containers `running` met ongewijzigde ID's; controller op `max2` `Result=success`; `KOUD ROLLBACKPUNT OK` met sha256 en grootte van de dump vastgelegd. Anders STOP en Rollback R2.

---

## Fase 4 — image naar `V17`

- **4.2 Tag wisselen (alleen de forge-imageregel) en bewijzen dat niets anders verschilt.**
  ```sh
  sudo sed -i "s|image: codeberg.org/forgejo/forgejo:$S\$|image: codeberg.org/forgejo/forgejo:$V17|" "$CF"
  ( set -e
    [ "$(grep -c "image: codeberg.org/forgejo/forgejo:$V17\$" "$CF")" = 1 ]      # de nieuwe tag staat er precies één keer
    [ "$(grep -c 'forgejo/forgejo:' "$CF")" = 1 ]                                 # en er is geen tweede forge-imageregel
    [ "$(sed "s|image: codeberg.org/forgejo/forgejo:$V17\$|image: codeberg.org/forgejo/forgejo:$S|" "$CF" | sha256sum | cut -d' ' -f1)" = "$PRE_CF" ]   # teruggerekend gelijk aan 2.4
  )
  rc=$?
  [ "$rc" -eq 0 ] && echo "TAGWISSEL OK (alleen de forge-imageregel gewijzigd)" || { echo "TAGWISSEL NIET EENDUIDIG (exit $rc) — STOP, ga NIET naar 4.3"; false; }
  ```
  Zelfde recept als 4.2 van het 15.0.9-plan, met `$S`/`$V17` als variabelen (de punten in een versienummer zijn in de `sed`-expressie jokertekens; ze matchen ook de letterlijke punt en de derde toets vangt elk onbedoeld verschil). Rood → STOP vóór 4.3: tag terugzetten met R4 stap 5 (zonder de recreate), `docker start scrum4me-forgejo`, controle `curl -s http://127.0.0.1:3010/api/v1/version` → 15.0.9, dan Fase 5 (uitkomst `rolled_back`).
- **4.3 Service-gebonden opbrengen.** `T43=$(date +%s); docker compose -f "$CF" up -d --no-deps forgejo`. Direct daarna: `docker inspect scrum4me-forgejo --format '{{.Config.Image}} {{.Image}}'` → tag `V17` en `IMGID17` uit 1.3; `docker inspect -f '{{.Id}} {{.State.Status}}' scrum4me-forgejo-runner scrum4me-forgejo-dind` → gelijk aan `RID`/`DID`, beide `running`.
- **4.4 Migraties volgen.** `docker logs -f scrum4me-forgejo` tot de listener opkomt; `curl -s http://127.0.0.1:3010/api/v1/version` → `V17`. Verwachte duur ≈ `MIG` uit R.3. `docker logs --since "$(date -u -d @"$T43" +%FT%TZ)" scrum4me-forgejo 2>&1 | grep -E '\[E\]|\[F\]|panic|creating new key'` → leeg (*creating new key* = een JWT-secret is niet geladen, B1). `[mac]` `curl -s https://git.jp-visser.nl/api/v1/version` → `V17`; blijft dat na 60 s 502, dan STOP-bevinding (geen eigenmachtige Caddy-herstart; JP beslist).
- **4.5 Doctor achteraf.** `doctorlog scrum4me-forgejo "$HOME/doctor-post.log" && doctortoets "$HOME/doctor-pre-venster.log" "$HOME/doctor-post.log"` → `doctor exit 0` en `DOCTOR OK`. `DOCTOR-RUN MISLUKT` maakt Gate 4 rood; bij `DOCTOR ROOD` elke getoonde regel beoordelen — alleen bevindingen die in R.4 al zijn verklaard mogen blijven staan, anders is Gate 4 rood.
- **4.6 `[JP]` Functioneel.** Inloggen, een repository, een pull request en de Actions-pagina van `janpeter/scrum4me-shared` openen; `docker exec scrum4me-forgejo forgejo --version` → bevat `V17`.

**Gate 4:** versie `V17` via 3010, via Caddy en via `forgejo --version`; image-ID gelijk aan 1.3; `doctor exit 0` en `DOCTOR OK` in 4.5 — of, bij `DOCTOR ROOD`, uitsluitend de bevindingen die in R.4 zijn vastgelegd en verklaard (een mislukte of onvolledige doctor-run blijft rood); geen `[E]`/*creating new key*; legacy container-ID's ongewijzigd; JP-functioneel groen. Anders **Rollback R4**. **Beslisgrens:** is Gate 4 niet groen op `T43 + max(10 min, 2 × MIG)`, dan begint R4 meteen.

**Restrisico writes (aftekenen door JP bij de venstergoedkeuring):** het rollbackpunt (2.7) dekt alles tot de stop in 2.6. Writes die ná 4.3 en vóór de Gate 4-acceptatie binnenkomen, zijn bij R4 niet herstelbaar in de teruggezette database — ze blijven wel inzichtelijk in de hernoemde `forgejo_failed_17_0`. Zijn alle schrijvers uit 0.16 gepauzeerd, dan is dat venster operator-only; voor schrijvers die JP in 0.16 heeft geaccepteerd, kunnen hun writes sinds 4.3 bij R4 verloren gaan.

---

## Fase 5 — pool herstellen, venster sluiten

Geldt voor **beide** uitkomsten. `VNOW=$(docker exec scrum4me-forgejo forgejo --version | grep -oE '1[0-9]+\.[0-9]+\.[0-9]+' | head -1)` → `V17` bij een geslaagde upgrade, `15.0.9` na R2/R4.

- **5.1 `[JP]` Legacy runner hervatten.** Runners → `scrum4me-srv-runner` → Resume. `[mac]` capture → id 3 `idle`, versie `v12.10.1`.
- **5.2 `[max2]` Trust-verdict vernieuwen, dan controller starten (runbook §5).** `sudo systemctl start forgejo-runner-trust.service && sudo systemctl show forgejo-runner-trust.service -p Result` → `Result=success`, en mechanisch vers (`T0` uit Fase 2 in deze shell zetten):
    ```sh
    MA=$(python3 -c 'import json;d=json.load(open("/opt/forgejo-runner/trust-verdict.json"));print(int(d["measured_at"]) if d.get("ok") else -1)')
    [ "$MA" -gt "$(date -u -d "$T0" +%s)" ] && echo "trust vers op VNOW" || { echo "trust-verdict niet ok of niet vers — STOP"; false; }
    ```
    Daarna `sudo systemctl start forgejo-runner-cycle.service; sudo journalctl -u forgejo-runner-cycle.service --since "$T0" --no-pager` → `SOURCE_WAIT` → tweemaal `READY` → `cyclus: scrub ok=True` → `cyclus: runner gestart`. `[mac]` capture → `max2-forgejo-runner-02` `idle`.
- **5.3 Smoke (runbook §6).** Tijdelijke `smoke-green.yml` (`on: [workflow_dispatch]`, `runs-on: ubuntu-latest`, `run: echo "smoke groen"; exit 0`) op `janpeter/scrum4me-shared`, dispatchen, terminale status **success**; runnummer en uitvoerende runner noteren; workflow weer verwijderen. Dit is het productiebewijs van het Forgejo↔runner-protocol op `VNOW` (R.5 was het proefbewijs).
- **5.4 Venster sluiten.** Hervat de schrijvers die voor dit venster volgens 0.16 zijn gepauzeerd — alleen die, bij upgrade én rollback — controleer dat ze terug zijn in hun toestand van vóór het venster en teken dat af in de 0.16-lijst in `venster.md`. `TEND=$(date -u +%FT%TZ)`; downtime (`TSTOP` → listener in 4.4, of tot de start in R2/R4) en uitkomst (`upgraded`/`rolled_back`) in `venster.md`.

**Gate 5:** beide records `idle` op `VNOW`; trust-verdict `ok:true` met `measured_at` ná `T0`; controller in `WAITING`; smoke `success`; gepauzeerde schrijvers hervat; uitkomst en tijden vastgelegd.

---

## Fase 6 — nazorg zonder downtime (dezelfde dag en D+1)

- **6.1 Evidence** onder `docs/forgejo-runner-pool/evidence/forgejo-17.0/`: `fase0/` (metingen, `releasegate.md`, `push-mirrors.tsv`, `doctor-pre.log`), `proef.md` (Gate R), `backup-manifest.md` (paden, groottes, sha256's, tijden — géén inhoud), `doctor-pre-venster.log`, `doctor-post.log`, `versies.txt` (`forgejo --version` voor/na, image-ID en digest), `runners-voor.tsv`/`runners-na.tsv` (zonder uuid-kolom), `smoke.md`, `venster.md` (T0/TSTOP/TEND, `PRE_CF`, `GIT_CF`, schrijversbesluit), `controller-journal-max2.txt` (uittreksel sinds `T0`). Redactie vóór commit: `grep -r -n -i -E 'token|secret|passw|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' docs/forgejo-runner-pool/evidence/forgejo-17.0/` → geen waarden; `bash forgejo-runner/scripts/secret-scan.sh $(find docs/forgejo-runner-pool/evidence/forgejo-17.0 -type f)` → exit 0.
- **6.2 Compose-map en docs (uitkomstafhankelijk).** *`upgraded` en `GIT_CF=ja`:* de tagwissel vastleggen volgens de hostregel: `docker compose -f "$CF" config -q` → exit 0; `git -C "$CD" add docker-compose.yml`; `git -C "$CD" diff --cached` → alleen de imageregel; `git -C "$CD" commit -m "forgejo $S -> $V17 (onderhoudsvenster <datum>)"`; `git -C "$CD" status --porcelain` → leeg. *`rolled_back` en `GIT_CF=ja`:* `git -C "$CD" status --porcelain` → leeg, want `$CF` is terug op `PRE_CF`. *`upgraded`:* `CLAUDE.md` en `AGENTS.md` regel 3 → "Forgejo `V17`"; in de Oriëntatie-tabel van `CLAUDE.md` rijen voor beide onderzoeken en dit plan. *`rolled_back`:* de versieregel blijft 15.0.9; mislukte poging en `forgejo_failed_17_0` in de evidence. In beide gevallen: `docker exec scrum4me-forgejo sh -c 'sed -n "/^\[actions\]/,/^\[/p" /data/gitea/conf/app.ini'` → nog steeds geen timeout-override, dus `T_requeue` = 600 s blijft geldig (in `versies.txt`).
- **6.3 D+1-controles (alleen bij `upgraded`, volgende dag).**
  - Push-mirrors: script uit 0.14 opnieuw → elke mirror heeft `last_update` ná `TEND`, en geen mirror heeft een fout die in de baseline niet had (B5/B6). Een nieuwe fout → bevinding voor JP (remote-adres of redirect).
  - `forgejo-mirror-sync`: `systemctl status forgejo-mirror-sync.service` → laatste run `success`.
  - Trust-timer: `[max2]` `sudo journalctl -u forgejo-runner-trust.service --since "$TEND" --no-pager` → alle slagen groen.
  - Tooling: de eerstvolgende door `scrum4me-mcp` aangemaakte PR heeft een web-`html_url` (B4); de Ops-dashboard-releasegate verwerkt de eerstvolgende main-commit (B9, zie "Bevindingen buiten scope"). Afwijkingen → bevinding voor JP, geen forge-rollback.
- **6.4 Commit + PR.** Branch `ops/forgejo-17.0`. *`upgraded`:* `ops(forgejo): 15.0.9 → V17 (proefmigratie + venster) — evidence`. *`rolled_back`:* `ops(forgejo): poging V17 teruggedraaid naar 15.0.9 — evidence`. PR op Forgejo via de API (`curl --config`), JP merget.
- **6.5 Retentie rollbackpunt.** `$BK` blijft **zeven dagen** na Gate 5 staan; vernietigingsdatum in `backup-manifest.md`; verwijderen (`sudo rm -rf "$BK"`) is een `[JP]`-handeling. Na R4 blijft ook `forgejo_failed_17_0` staan tot JP hem laat vallen.
- **6.6 Scrum4Me.** Per taak `update_task_status`; `log_implementation` met de evidence-paden.

**Gate 6:** PR gemerged; `secret-scan.sh` exit 0; docs en compose-map consistent met de uitkomst; D+1-controles vastgelegd; vernietigingsdatum vastgelegd.

---

## Rollback

Elke terugweg herstelt naar het laatst groene gate. Vóór 4.3 is er geen point of no return; na 4.3 is de enige terugweg het koude paar van 2.7 (dump `forgejo-pre-17.dump` + volume `$BK/data`, samen genomen met de forge gestopt).

- **R2 (Gate 2 rood; forge gestopt, niets gewijzigd):** `docker start scrum4me-forgejo`; `curl -s http://127.0.0.1:3010/api/v1/version` → 15.0.9; `[mac]` idem via Caddy; dan Fase 5 (`rolled_back`).
- **R4 (Gate 4 rood of de beslisgrens verstreken):**
  1. `docker stop -t 90 scrum4me-forgejo` (indien nog actief).
  2. Dump plaatsen en verifiëren vóór enige databasewijziging (losstaande subshell; eerst een eventuele oude `/tmp/rollback.dump` weg):
     ```sh
     ( set -e
       docker exec scrum4me-postgres rm -f /tmp/rollback.dump
       sudo docker cp "$BK/forgejo-pre-17.dump" scrum4me-postgres:/tmp/rollback.dump
       LIST=$(docker exec scrum4me-postgres pg_restore --list /tmp/rollback.dump)
       [ -n "$LIST" ]
     )
     rc=$?
     [ "$rc" -eq 0 ] || { echo "dump ontbreekt of onbruikbaar (exit $rc) — STOP, database NIET hernoemen, escaleer naar JP"; false; }
     ```
  3. Alleen na een groene stap 2 — de gemigreerde database wordt **hernoemd**, niet gedropt:
     ```sh
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE forgejo RENAME TO forgejo_failed_17_0"'
     docker exec scrum4me-postgres sh -c 'pg_restore -U "${POSTGRES_USER:-postgres}" -d postgres --create --exit-on-error /tmp/rollback.dump'
     docker exec scrum4me-postgres sh -c 'psql -U "${POSTGRES_USER:-postgres}" -d postgres -Atc "select datname from pg_database"'   # forgejo én forgejo_failed_17_0
     docker exec scrum4me-postgres rm /tmp/rollback.dump
     ```
  4. Volume terug: `sudo rsync -aHAX --numeric-ids --delete "$BK/data/" "$VOL/"`.
  5. Tag terug en bewijzen dat `$CF` weer byte-gelijk is aan 2.4: `sudo sed -i "s|image: codeberg.org/forgejo/forgejo:$V17\$|image: codeberg.org/forgejo/forgejo:$S|" "$CF"; [ "$(sha256sum "$CF" | cut -d' ' -f1)" = "$PRE_CF" ] && echo "COMPOSE TERUG OP PRE_CF" || { echo "COMPOSE WIJKT AF VAN PRE_CF — STOP, JP"; false; }` → daarna `docker compose -f "$CF" up -d --no-deps forgejo`.
  6. `curl -s http://127.0.0.1:3010/api/v1/version` → 15.0.9; `[mac]` idem via Caddy; `doctorlog scrum4me-forgejo "$HOME/doctor-r4.log" && doctortoets "$HOME/doctor-pre-venster.log" "$HOME/doctor-r4.log"` → `doctor exit 0` en `DOCTOR OK` (anders STOP: de pool gaat niet open op een onvolledige of rode doctor); dan Fase 5 (`rolled_back`). Bevinding, logs en `forgejo_failed_17_0` naar JP.
- **Fase 5 faalt** (runner niet online, trust rood, smoke rood): poolbevinding, geen reden om de forge terug te zetten; runbook §9, JP beslist. Door R.4 en R.5 is een protocol- of trustprobleem op `V17` hier niet meer de verwachte oorzaak.

---

## Bevindingen buiten scope (voor JP)

- **Ops-dashboard-releasegate en `skipped` (B9).** `lib/release-candidates/service.ts:142` eist dat álle commit-contexts `success` zijn; sinds 16 krijgt een overgeslagen job `skipped`. Raakt releasekandidaten zodra een relevante workflow een overgeslagen job heeft; aanpassing hoort in de Ops-dashboard-repo.
- **Ops-dashboard `scripts/ci/verify-canary.mjs:2`** pint `SERVER_VERSION = '15.0.2'`; een nieuw canaryrapport na een upgrade wordt geweigerd tot die constante is bijgewerkt (geldt al na het 15.0.9-venster).
- **`~/.codex/AGENTS.md`** noemt drie repositories pull-mirrors; er is er geen (inventaris 28 sep).
- **Maintenance-record niet armbaar** (ongewijzigd uit het 15.0.9-plan): de drain blijft handwerk tot stap F een laadpad krijgt.
- **LTS-lijn verlaten:** 17.0 is end-of-life op **28 januari 2027**; vóór die datum is de stap naar 18.0 nodig (release 14 jan 2027, dus een krap venster van twee weken). 19.0 LTS verschijnt pas op 15 apr 2027 (EOL 13 jul 2028) en is dus de stap dáárna, geen alternatief voor 18. Een eigen plan per stap.
- **Optionele opruiming volgens de upgrade-guide** (oude per-repo `hooks`-mappen, `pulls/*.patch`) valt buiten het venster; eventueel een eigen onderhoudsactie ná 0.15 = 0.
- **Runner 13** blijft fase 2 van het migratieontwerp (§12); R.5 toetst alleen dat 12.10.1 tegen 17 werkt.

---

## Zelf-review (grondslag-dekking)

- **Upgrade-guide v17:** directe sprong (onderzoek §2), consistente koude backup (2.7), `flush-queues` vooraf (2.6), `doctor check --all` voor en na (0.4, 2.6, 4.5) én in de proef (R.4), vergeleken met `doctortoets`; rollback = restore (R4).
- **Breaking changes B1–B12:** B1 (R.6, 4.4, 0.3 schrijfbaarheid), B2 (0.10), B3 (afgehandeld in het 15.0.9-venster), B4 (6.3; code leest `html_url`), B5/B6 (0.14, 6.3), B7 (R.3 start op onze eigen `app.ini`), B8 (0.15, R.4), B9 (6.3 + bevinding), B10–B12 geen actie (onderzoek §3). Niet-gedekte nieuwe items → releasegate 0.0.
- **Onbekenden gemeten, niet aangenomen:** migratieduur (`MIG`, R.3 → vensterbudget 1.4 en beslisgrens Gate 4), runnercompatibiliteit (R.5), trustgate en jobbron op 17 (R.4), vorm van `/admin/actions/runners` (R.4).
- **Beproefd:** Fase R, 2.4–4.5 en R4 zijn letterlijk uit dit plan uitgevoerd in een wegwerpomgeving (evidence 30 sep); wat die omgeving níét dekt (echte data en omvang, de drain, Caddy, `max2`) staat in dat bewijs en wordt op de host gemeten in Fase 0 en Fase R.
- **Isolatie van de proef:** `--internal`-netwerk (R.0, gecontroleerd; R.3 bewijst op naam en op IP dat er geen verkeer naar buiten is, en dat er geen poorten zijn), mirror en mailer uit met de effectieve waarden getoond (R.3), crontaken bewust aan zoals in productie, `--memory` op elke proefcontainer, wegwerpgeheimen in `$RH` (0700) en de proefdatabase op een benoemd volume, opruimen op naam inclusief volumes met een dangling-vergelijking (R.7); `scrum4me-postgres` levert alleen een online dump (R.1).
- **Hergebruik van het 15.0.9-plan:** drain 2.1–2.3, rollbackpunt 2.7, R4, `VNOW`-symmetrie, compose-hashbewijs en hostregel-commit, write-fence met schrijversbesluit, en alle fail-gates in het patroon losstaande `( set -e … )` + `rc=$?` (ook R.1, R.2, R.3). Afwijkingen: geen configuratiefase (2.5, Fase 3, R3 vervallen), één rollbackpunt in plaats van twee, vensterbudget en beslisgrens uit `MIG`, image-ID-check in 4.3, D+1-controles in 6.3.
- **Geen secrets:** productiewaarden blijven in de container of `$BK`; proefgeheimen alleen in `$RH`; de UUID-regel via de 6.1-grep.
- **Consistentie:** `S`/`V17` (0.0/0.1 → R.3, 4.2, 4.3, R4 stap 5, 6.2), `MIG` (R.3 → 1.4, 4.4, Gate 4), `PRE_CF` (2.4 → 4.2 → R4 stap 5), `GIT_CF` (0.13 → 2.4 → 6.2), `IMGID17` (1.3 → 4.3), `RID`/`DID` (2.6 → 4.3), `T0`/`TSTOP`/`T43`/`TEND`, `VNOW` (Fase 5).

## Uitvoerhandoff

Volgorde: (1) **plan-review** (review-loop, twee cross-model reviewers: `scrum4me-server:claude` ops-routed — Docker/Postgres/compose op de host zelf — en `mac:codex`) tot dubbel GO; (2) **JP-gate**; (3) het **15.0.9-venster** (eigen plan) afgerond met uitkomst `upgraded`; (4) **Scrum4Me-ceremonie** op product `cmsx8zbdh0002hk7rcgxxr00k` (sprint → PBI → story → taken per fase, commando's en gates uit dit plan gekopieerd) → hardstop; (5) Fase 0.0 en Fase R ná 15 oktober, daarna het venster — elk alleen op een afzonderlijke opdracht van JP en niet gelijktijdig met stap F/G of de compose-opruiming van ISS-5.

## Review record

Plan-fase van de review-loop (twee onafhankelijke cross-model reviewers, JP-armd; zij zien elkaars output niet). Persistente loop-staat.

- **Onder review:** dit plan + `forgejo-17-onderzoek-2026-09.md` + `evidence/forgejo-17.0/recept-proef-2026-09-30.md`, tegen de upgrade-guide v17, de releasenotes en PR's die het onderzoek citeert, het 15.0.9-plan, de hostregel voor compose-bestanden, `migratieontwerp.md` §7.7/§7.9/§9/§12, `evidence/stap-d/bring-up-runbook.md` §5–§7, `implementatieplan-stap-g.md` B3/C3 en de as-built bundel `forgejo-runner/`.
- **Scope-noot voor reviewers:** de keuze voor 17.0 (in plaats van 16.0.5 of de LTS-lijn) en de volgorde "eerst 15.0.9" zijn besluiten van JP (28 en 30 sep 2026) en liggen niet ter review. Wél in scope: of de proef veilig geïsoleerd is en meet wat ze belooft, of drain, rollbackpunt, gates en terugwegen correct en volledig zijn, en of elke claim over de boom, de host en de upstream-bronnen klopt. De finale 17.0-notes bestaan nog niet; releasegate 0.0 vangt dat af.

### Ronde 1 — 2026-09-30 — **NO-GO** (dubbel)
- **Reviewers:** `scrum4me-server:claude` (ops-routed, las de hoststand read-only uit; 0 BLOCKER · 1 MAJOR · 6 MINOR) + `mac:codex` (statisch, met eigen stubproeven; 0 BLOCKER · 2 MAJOR · 2 MINOR), op commit `8090eeb`; beide controleerden de vier sha256-pins. Beide **NO-GO**. Geen van beiden ziet een schrappingskandidaat: de proef op eigen data, R.5, de contractcheck, de mirror-baseline, de hookscheck en de D+1-controles hebben elk een benoemde functie.
- **Convergente MAJOR (beide, onafhankelijk): R.7 liet de gekopieerde database achter in een anoniem volume.** `postgres:17` declareert `VOLUME /var/lib/postgresql/data`; `fj17-rh-db` draaide zonder benoemd volume en `docker rm -f` zonder `-v` laat het anonieme volume staan, terwijl Gate R "opgeruimd" aftekende op alleen containers en netwerken. Nagemeten in de wegwerpomgeving (evidence §5: het oude recept laat per run één dangling volume achter). **Fix:** benoemd volume `fj17-rh-pgdata` (R.2); R.7 met `docker rm -f -v`, `docker volume rm fj17-rh-pgdata`, een controle op volumes met `fj17` in de naam en een vergelijking van de dangling volumes met de stand van R.0; Gate R en de Global Constraint noemen de volumes.
- **MAJOR (`mac:codex`): de globale cron-override schakelt de afzonderlijke taken niet uit.** Forgejo leest `[cron.<taak>]`; `FORGEJO__cron__ENABLED=false` doet daar niets aan (`modules/setting/cron.go`, `services/cron/setting.go` op `v17.0/forgejo`). **Fix:** de variabele en de claim "cron uit" zijn geschrapt; de Global Constraint zegt nu wat wél geldt — `[mirror]` en `[mailer]` uit (de mirrortaak wordt dan niet geregistreerd), het netwerk intern, en de overige crontaken lopen bewust zoals in productie op de kopie. R.3 toont de effectieve `[mirror]`/`[mailer]`-waarden.
- **MINORs, alle bevestigd en verwerkt (geen afgewezen):**
  - *(claude)* tech stack noemde Docker 29.7.2 / Compose 5.1.4; de host draait 29.8.1 / 5.5.1 → gecorrigeerd, en 0.6 meet de versies.
  - *(claude)* het isolatiebewijs toonde alleen een DNS-fout (exit 6) → R.3 toetst nu ook op IP-adres (`https://1.1.1.1`, exit 7 in de proef).
  - *(claude)* of een nieuwere 17.0.x een migratie bevat, staat niet betrouwbaar in de releasenotes → 0.0 toetst de bron via de compare-API op `models/forgejo_migrations*` en `models/gitea_migrations`. Nagemeten: tussen 16.0.0 en 16.0.5 zit een migratiebestand (evidence §5).
  - *(claude)* de trustvergelijking gebruikte een ander account dan de productiescan kan hebben → 0.18 bepaalt de `login` van het productietoken (`TRUSTUSER`), R.3 maakt het proeftoken voor dat account.
  - *(claude)* de timergate was dubbelzinnig en miste `scrum4me-pg-backup.timer` → 0.7 noemt de drie relevante slagen en sluit de uurlijkse prune-timers uit.
  - *(claude)* restic neemt `/srv/backups/manual` mee, en 0.13 legde de losse compose-kopie niet vast → 1.1 meldt het aan JP, Fase R valt buiten 03:00–04:00, 0.13 doet `ls -la "$CD"`.
  - *(codex)* Gate 4 noemde de in R.4 verklaarde doctorbevindingen niet → Gate 4 herhaalt de uitzondering; een mislukte of onvolledige run blijft rood.
  - *(codex)* de EOL-noot bood 19.0 LTS aan als route vóór 28 januari 2027 → gecorrigeerd: 18.0 is de stap vóór die datum, 19.0 LTS de stap erna.
- **Hostfeiten van de ops-reviewer die het plan bevestigen** (gemeten 30 sep, forge nog op 15.0.2): precies één forge-imageregel in `$CF` (`janpeter:janpeter 664`, `sudo sed -i` behoudt eigenaar en mode), services `forgejo`/`dind`/`runner`, poort `127.0.0.1:3010:3000`; `GIT_CF=nee`; `USER_UID`/`USER_GID` 1000; `curl` in de image; productie zet zelf `FORGEJO__database__*` via env (de env-to-ini-route van R.2 werkt dus in deze image-familie); volume 2,2 GB en database 197 MB tegen 189 GB vrij; `MemAvailable` 10,2 GB; `postgres:17` en het gepinde runnerdigest lokaal aanwezig; geen `fj17`-containers, -netwerken of `forgejo_failed_17_0`.
- **Verdicts:** `scrum4me-server:claude` NO-GO · `mac:codex` NO-GO.
