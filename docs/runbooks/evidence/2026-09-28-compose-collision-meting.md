# Compose-collision — meting 28 september 2026

Hoort bij `docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Methode.** Read-only gemeten vanaf `mac` via SSH (`janpeter@scrum4me-srv`, `janpeter@max2`),
2026-09-28 14:15–14:45Z. Geen bestand gewijzigd, geen container gestart of gestopt, geen
queue-bericht verstuurd. Waar bestanden op secrets zijn getoetst, toonde de meting alleen
sleutelnamen en aantallen, nooit waarden. `sudo` is alleen gebruikt om te lezen.

## 1. Trend uit de queue

Nachtelijke rapporten van `compose-collision-check` aan `mac:jp`.

| Rapport (UTC) | Host | Gescand | Destructief | Bericht-ID |
|---|---|---|---|---|
| 2026-09-25 22:36 | scrum4me-server | 13 | 2 | `257996d5-8c49-482f-8917-3b39f76469d6` |
| 2026-09-26 22:43 | scrum4me-server | 14 | 3 | `f6fca3ae-643f-4cc3-a1dd-79c8731af8a1` |
| 2026-09-27 22:39 | scrum4me-server | 15 | 4 | `bbc91fda-4902-40a8-9617-b53d24037747` |
| 2026-09-25 22:38 | max2 | 24 | 1 (15 mappen) | `ffa6d322-5e20-415b-9f38-8113a99aae49` |
| 2026-09-26 22:37 | max2 | 25 | 1 (16 mappen) | `0d44da1e-34ca-4abf-891d-95bac73aad8e` |
| 2026-09-27 22:35 | max2 | 25 | 1 (16 mappen) | `f497fe55-a542-4b91-8072-24bce2ae21fe` |

De opruiming van ISS-5 was op 2026-09-25 14:56Z. In de inbox van `mac:jp` staan daarnaast
dagelijkse `ops-agent config drift`-rapporten van beide hosts met hetzelfde herhaalpatroon.

## 2. De twee scannerkopieën

| | Ops-dashboard | scrum4me-docker |
|---|---|---|
| Pad | `deploy/ops-agent/check-compose-collision.sh` | `scripts/check-compose-collision.sh` |
| Gemeten op | `origin/main` @ `6e5e4c5a7` | `origin/master` @ `52ded13` |
| Regels | 364 | 216 |
| sha256 | `faf0176619b400d5b927aabcf6d00221ea1716d14c1c0c886cd7382c543eda20` | `37b942accb726e7fc52fc7d1463bba682ad726c5f14a0b114cba49ba18674400` |
| Laatste wijziging | `935c63a9b`, 2026-09-10 | `570b95a`, 2026-07-10 |
| Zoekpatroon | `docker-compose*.yml*`, `compose.yaml*` | `docker-compose*.yml`, `compose.yaml` |
| Check (c) | ja | nee |

| Host | `ExecStart` van `compose-collision-check.service` | sha256 runtime |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/ops-agent-drift/check-compose-collision.sh 154 /srv` | `faf0176619b4…` |
| max2 | `/srv/scrum4me/repos/scrum4me-docker/scripts/check-compose-collision.sh max2 /srv` | `37b942accb72…` |

Beide timers draaien dagelijks rond 00:35–00:50 CEST. Beide units draaien als root met
`S4M_QUEUE_ENV=/home/janpeter/.config/s4m-queue.env`.

## 3. scrum4me-server

`docker compose ls --all`:

| Project | Status | Geregistreerd configbestand |
|---|---|---|
| `compose` | running(13) | `/srv/scrum4me/compose/docker-compose.yml` |
| `forgejo` | running(3) | `/srv/scrum4me/forgejo/docker-compose.yml` |
| `scrum4us` | running(6) | `/srv/scrum4us/checkout/infra/compose/docker-compose.srv.yml` |
| `scrum4us-dev` | exited(1) | een scratchpad-pad onder `/tmp/claude-1000/-home-janpeter-claude/` |

Compose-bestanden met een suffix na de extensie onder `/srv` (zonder `_attic`, `.git`,
`node_modules`, `.next`; het sjabloon `docker-compose.yml.tmpl` niet meegeteld):

| Pad | Eigenaar | Mode |
|---|---|---|
| `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/docker-compose.yml.bak` | janpeter | 664 |
| `/srv/scrum4me/forgejo/docker-compose.yml.bak.20260607-174910` | janpeter | 664 |
| `/srv/scrum4me/forgejo/docker-compose.yml.iss8.bak` | janpeter | 664 |
| `/srv/scrum4me/forgejo/docker-compose.yml.bak.20260926T071930Z` | janpeter | 664 |
| `/srv/scrum4me/compose/docker-compose.yml.bak.clipins-20260927T114046Z` | janpeter | 664 |
| `/srv/scrum4me/compose/docker-compose.yml.bak.20260928T005811-workerdb` | janpeter | 664 |

De onderste vijf staan naast een live `.env`. De twee kopieën in `/srv/scrum4me/compose`
dragen allebei `name: compose`.

Let op: `cp -p` bewaart de mtime van het origineel. De mtime van een kopie is dus niet het
moment waarop hij is gemaakt; de ctime is dat wel.

| Map | Eigenaar, mode | Git-werkboom | Live bestanden |
|---|---|---|---|
| `/srv/scrum4me/compose` | janpeter, 755 | nee | `docker-compose.yml` (janpeter, 664) |
| `/srv/scrum4me/forgejo` | janpeter, 775 | nee | `docker-compose.yml`, `runner-config.yaml` (janpeter, 664) |

Overig:

- `/srv/_attic` is van root, mode 755.
- `/srv/_attic/2026-09-25/` bevat `compose-history.tar`, `MANIFEST.txt` en
  `SHA256SUMS.compose-history`, alle drie mode 644, root:root.
- `git` 2.53.0 is aanwezig; er is geen globale `user.name`.
- `server-backup.sh` neemt `/srv` mee in `RESTIC_BACKUP_PATHS`.
- Hostinstructies: `/home/janpeter/claude/CLAUDE.md` (184 regels; `AGENTS.md` is een symlink
  ernaar), `~/.codex/AGENTS.md`, `~/.claude/rules/s4m-queue.md`,
  `~/.claude/rules/scrum4me-methodiek.md`. Geen ervan noemt compose-kopieën, `.bak` of
  `_attic`. `CLAUDE.md` regel 51 noemt de live compose-file met "Niet aanpassen zonder reden".

## 4. max2

`docker compose ls --all`, voor zover relevant:

| Project | Status | Geregistreerd configbestand |
|---|---|---|
| `scrum4me` | running(5) | `/srv/scrum4me/compose/docker-compose.yml`, `…override.yml`, `…codex.yml` |
| `when2watch` | running(2) | `/srv/apps/when2watch/releases/5dd8b3f/compose.yaml` |
| `media-organizer` | exited(1), running(4) | twee bestanden onder `/srv/apps/media-organizer/.media-deploy.*/` |
| `tei-gpu` | exited(1) | `/srv/apps/tei/docker-compose.yml` |

Compose-bestanden met een suffix na de extensie onder `/srv`: **30**, het sjabloon niet
meegeteld.

| Map | Aantal |
|---|---|
| `/srv/scrum4me/compose` | 24 |
| `/srv/immich` | 2 |
| `/srv/apps/media-organizer/repo/deploy` | 2 |
| `/srv/apps/tei` | 1 |
| `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16` | 1 |

In `/srv/scrum4me/compose`: 16 kopieën van `docker-compose.yml`, 4 van
`docker-compose.override.yml`, 4 van `docker-compose.codex.yml`. De vijf nieuwste, van 27 en
28 september:

- `docker-compose.yml.bak.clipins-20260927T114828Z`
- `docker-compose.codex.yml.bak.clipins-20260927T114828Z`
- `docker-compose.yml.bak.iss35-20260927T133213Z`
- `docker-compose.yml.bak.20260928T002106-workerdb`
- `docker-compose.codex.yml.bak.20260928T002106-workerdb`

`/srv/scrum4me/compose` is van janpeter (755) en is geen git-werkboom. De drie live
bestanden dragen `name: scrum4me`.

### When2Watch

`/srv/apps/when2watch` is van janpeter, mode 700. `current` wijst naar
`/srv/apps/when2watch/releases/5dd8b3f`. Er zijn 16 releases, samen 16 MB.

| Release | Aangemaakt (ctime) | `compose.yaml` | `name:` | `.env`-symlinks | `db`-service |
|---|---|---|---|---|---|
| `dfc39bb` | 2026-09-23 18:12 | ja | `when2watch` | `.env` | nee |
| `4a50e76` | 2026-09-23 18:23 | ja | `when2watch` | `.env` | nee |
| `4c290be` | 2026-09-23 20:24 | ja | `when2watch` | `.env` | nee |
| `961fc09` | 2026-09-23 20:29 | ja | `when2watch` | `.env` | nee |
| `93bbaed` | 2026-09-24 09:40 | ja | `when2watch` | `.env` | nee |
| `4379141` | 2026-09-24 09:45 | ja | `when2watch` | `.env` | nee |
| `d13cad0` | 2026-09-24 10:16 | ja | `when2watch` | `.env` | nee |
| `2153d94` | 2026-09-24 11:01 | ja | `when2watch` | `.env` | nee |
| `b31af05` | 2026-09-24 11:18 | ja | `when2watch` | `.env` | nee |
| `b2e4de9` | 2026-09-24 12:59 | ja | `when2watch` | `.env` | nee |
| `790ed77` | 2026-09-24 13:14 | ja | `when2watch` | `.env` | nee |
| `e864397` | 2026-09-24 15:27 | ja | `when2watch` | `.env` | nee |
| `c04812c` | 2026-09-24 16:51 | ja | `when2watch` | `.env` | nee |
| `fb7a690` | 2026-09-24 21:21 | ja | `when2watch` | `.env` | nee |
| `8b87838` | 2026-09-25 21:17 | ja | `when2watch` | `.env`, `.env.db`, `.env.migrate` | ja |
| `5dd8b3f` | 2026-09-26 00:41 | ja | `when2watch` | `.env`, `.env.db`, `.env.migrate` | ja |

Containers `when2watch-web-1` en `when2watch-db-1` zijn healthy en dragen als
`config_files` het bestand in `releases/5dd8b3f`. Er staan 18 images `when2watch:<tag>`
van elk circa 1,3 GB volgens `docker images`; gedeelde lagen zijn niet uitgesplitst.

Geen van de releasemappen is een git-werkboom.

### Overig

- `/srv/_attic` is van root (755); `/srv/_attic/iss35-20260927` is van janpeter (700).
- `git` 2.53.0 is aanwezig; er is geen globale `user.name`.
- Hostinstructies: `/home/janpeter/claude/CLAUDE.md` (107 regels; `AGENTS.md` is een symlink
  ernaar) en `~/.claude/rules/s4m-queue.md`. Er is geen `~/.codex/AGENTS.md`. Geen ervan noemt
  compose-kopieën.
- De backup-sectie van `CLAUDE.md` op max2 meldt dat alleen de `scrum4me`-database gedekt is.
  `/srv/scrum4me/compose` valt op max2 dus buiten de backup.

## 5. Droogloop van de actuele scanner op max2

```bash
ssh max2 'sudo DRIFT_NO_NOTIFY=1 bash -s -- max2 /srv' < deploy/ops-agent/check-compose-collision.sh
```

Uitvoer op stderr:

```text
[check-compose-collision] scanning 56 compose file(s) under /srv
[check-compose-collision] FINDINGS: 22 destructive, 22 warning(s)
[check-compose-collision] DRIFT_NO_NOTIFY=1 — skipping queue push
```

Exitcode 1. Opbouw van de 22 destructieve bevindingen:

| Check | Project | Aantal |
|---|---|---|
| (a) zelfde projectnaam uit meerdere mappen | `when2watch`, 16 mappen | 1 |
| (c) bestand resolvet naar draaiend project | `when2watch`, 15 releasemappen | 15 |
| (c) bestand resolvet naar draaiend project | `scrum4me`, in `/srv/scrum4me/compose` | 6 |

Opbouw van de 22 waarschuwingen: 16× (b) dubbele `container_name`, 6× (c).

| (c)-waarschuwing | Project | Aantal |
|---|---|---|
| interpoleert niet vanaf deze plek | `scrum4me` | 3 |
| interpoleert niet vanaf deze plek | `media-organizer` | 1 |
| resolvet, project is `exited(1), running(4)` | `media-organizer` | 1 |
| resolvet, project is `exited(1)` | `tei-gpu` | 1 |

**Defect in de scanner.** De regel voor `media-organizer` is te laag gerangschikt. De scanner
toetst of de status met `running` begint (`${st#running}`). De status `exited(1), running(4)`
begint met `exited`, terwijl er vier containers draaien.

De juli-versie meldde op hetzelfde moment: 25 bestanden gescand, 1 destructief, 0
waarschuwingen.

## 6. Letterlijke secret-vormige waarden

Getoetst met een `awk`-filter dat per regel alleen de sleutelnaam en een classificatie toont.
Het filter kent de namen `PASSWORD`, `PASSWD`, `SECRET`, `TOKEN`, `API_KEY`, `PRIVATE_KEY`,
`DSN`, `DATABASE_URL` en `DIRECT_URL`, en daarnaast elke URL met `gebruiker:wachtwoord@`.
Het is een patroontoets, geen volledige secrets-scan.

**Live bestanden: geen letterlijke waarden.**

| Host | Bestand | Letterlijk | Geïnterpoleerd |
|---|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose/docker-compose.yml` | 0 | 3 |
| scrum4me-server | `/srv/scrum4me/forgejo/docker-compose.yml` | 0 | 2 |
| scrum4me-server | `/srv/scrum4me/forgejo/runner-config.yaml` | 0 | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.yml` | 0 | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.override.yml` | 0 | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.codex.yml` | 0 | 0 |
| max2 | `/srv/apps/when2watch/releases/5dd8b3f/compose.yaml` | 0 | 0 |

**Kopieën: wel.**

| Host | Waar | Gescand | Met letterlijke waarde |
|---|---|---|---|
| scrum4me-server | losse kopieën onder `/srv` | 6 | 0 |
| scrum4me-server | `/srv/_attic/2026-09-25/compose-history.tar` (mode 644) | 24 | 4 |
| max2 | losse kopieën onder `/srv` | 30 | 8 |

Treffers op max2, allemaal in `/srv/scrum4me/compose`:

| Kopie | Treffer | Mode |
|---|---|---|
| `docker-compose.yml.bak.20260522-234028` | `POSTGRES_PASSWORD` | 664 |
| `docker-compose.yml.bak.20260525-195132` | `POSTGRES_PASSWORD`, URL met credentials | 664 |
| `docker-compose.yml.bak.20260526-202520` | `POSTGRES_PASSWORD` | 644 |
| `docker-compose.yml.bak.20260526-213957` | `POSTGRES_PASSWORD` | 644 |
| `docker-compose.override.yml.bak.1780161296` | URL met credentials | 644 |
| `docker-compose.override.yml.bak.pre-rename-20260711T063757` | URL met credentials | 644 |
| `docker-compose.override.yml.bak.lanswitch.20260919T232455Z` | URL met credentials | 640 |
| `docker-compose.override.yml.bak.iss1-20260925T173506Z` | URL met credentials | 600 |

De treffers in de tar op scrum4me-server zijn dezelfde vier `docker-compose.yml.bak.202605…`-
namen.

**Niet getoetst:** of deze waarden nog geldig zijn. De superuser `scrum4me` is op 2026-09-27
geroteerd en T-117 (ISS-38) heeft waarden ter plekke vervangen door een plaatshouder van
dezelfde lengte. Het filter kan een plaatshouder niet van een echte waarde onderscheiden.

## 7. Queue-CLI

`s4m-queue push` kent `--idempotency-key <sleutel>`. In `src/db.ts` van s4m-queue
(`origin/main` @ `39aa5f9`) is dat een `INSERT … ON CONFLICT (idempotency_key) WHERE
idempotency_key IS NOT NULL DO NOTHING`, gevolgd door het teruggeven van de bestaande id. De
sleutel is dus uniek over alle berichten, ongeacht hun status. De CLI staat op beide hosts
als `/usr/bin/s4m-queue`. De CLI heeft geen commando om issues aan te maken.

## 8. Hostagenten (nameting 14:57Z, na reviewronde 1)

| | scrum4me-server | max2 |
|---|---|---|
| `codex` op het PATH | `/home/janpeter/.local/bin/codex` | `/home/janpeter/.local/bin/codex` |
| `claude` op het PATH | `/home/janpeter/.local/bin/claude` | `/home/janpeter/.local/bin/claude` |
| Processen met de naam `codex` | 0 | 0 |
| Processen met de naam `claude` | 1 | 1 |
| `~/.codex/AGENTS.md` | aanwezig, mtime 2026-09-23 | ontbreekt |
| `~/.codex/config.toml` | mtime 2026-09-27 | mtime 2026-09-14 |
| Nieuwste statusbestand in `~/.codex` | 2026-09-28 00:32 | 2026-09-14 20:12 |

Codex is dus op beide hosts geïnstalleerd. Op scrum4me-server is het recent gebruikt, op max2
voor het laatst op 14 september. Een eerdere telling met `pgrep -f` gaf op beide hosts 2
codex-processen; die telling was een artefact, want het patroon stond in de opdrachtregel
van de meting zelf.
