# Onderzoek — Forgejo 15.0.2 → 16.0.3 en de koppeling met Runner 13

**Datum:** 9 september 2026  
**Vraag (JP):** wat betekent het om Forgejo te updaten, en kunnen we dat combineren met de upgrade van de runners naar versie 13? Forgejo 16.0.3 is beschikbaar; wij draaien `15.0.2+gitea-1.22.0`.  
**Status:** onderzoeksrecord met aanbeveling. Het uitvoerbare plan voor de eerste stap staat in [implementatieplan-forgejo-15.0.9.md](implementatieplan-forgejo-15.0.9.md) (op 30 september 2026 omgezet van 15.0.7 naar 15.0.9; waar dit onderzoek 15.0.7 noemt, geldt nu de nieuwste LTS-patch 15.0.9).  
**Antwoord in één zin:** Forgejo 16 en Runner 13 zijn technisch onafhankelijk (geen van beide vereist de ander); combineer ze niet in één wijziging, patch nu naar 15.0.7 (LTS), laat fase 2 (Runner 13) zoals ontworpen ná stap H lopen, en ga alleen naar 16 bij een bewuste keuze voor de kwartaaltrein.

## 1. Gemeten uitgangssituatie op `scrum4me-server`

Bronnen: stap-A-bewijs in deze repo en een read-only inspectie door JP op 9 september 2026 (`grep` op `app.ini` en `docker-compose.yml`, wachtwoorden niet gelezen). Twee secretwaarden zijn bij die inspectie per ongeluk in een agent-gesprek beland; zie §6.

| Feit | Waarde | Bron |
|---|---|---|
| Forgejo-versie | `15.0.2+gitea-1.22.0` (release name 15.0.2) | `evidence/stap-a/t-requeue.md` |
| Container / image | `scrum4me-forgejo`, `codeberg.org/forgejo/forgejo:15.0.2` (tag-gepind) | `evidence/stap-a/productiecontainers-voor.txt` |
| Compose-project | `forgejo`, `/srv/scrum4me/forgejo/docker-compose.yml`; bevat óók de legacy runner (regel 58, `depends_on: [forgejo, dind]` op regel 61) en de legacy DinD (regel 101) | `evidence/stap-a/scrum4me-server/containers.json`; JP 9 sep |
| Image-regel forge | regel 22 `image: codeberg.org/forgejo/forgejo:15.0.2` | JP 9 sep |
| Poorten forge | HTTP alleen `127.0.0.1:3010:3000`; Caddy bereikt `forgejo:3000` via het gedeelde composenetwerk; SSH alleen op het Tailscale-IP | JP 9 sep (compose regels 44–48) |
| Datavolume | `forgejo_forgejo-data` → `/data` (alle git-repositories) | `implementatieplan-stap-g.md` B3 |
| Database | `DB_TYPE = postgres`, `HOST = scrum4me-postgres:5432`, `NAME = forgejo`, `USER = forgejo` — de forge deelt de productie-Postgres (`postgres:17`) met de scrum4me-app; het compose-project heeft géén eigen Postgres-service | JP 9 sep; `productiecontainers-voor.txt` |
| Reverse proxy | `[security] REVERSE_PROXY_TRUSTED_PROXIES = *` staat **expliciet** in `app.ini`; `[service]` zet `ENABLE_REVERSE_PROXY_AUTHENTICATION` niet (default `false`) | JP 9 sep |
| JWT | `[oauth2] JWT_SECRET` en `[server] LFS_JWT_SECRET` aanwezig | JP 9 sep |
| Actions | `[actions] ENABLED = true`, geen timeout-overrides (`T_requeue` = 600 s) | `evidence/stap-a/t-requeue.md` |
| Backup | nachtelijke restic-run (`/srv/backups/scripts/server-backup.sh`, env `/etc/restic-backup.env`), RPO ≤ 24 u | `implementatieplan-stap-g.md` B3/C3 |
| Host-Docker / DinD-Docker | 29.7.2 / `DOCKER_VERSION=29.4.3` in het gepinde `docker:dind`-image | `implementatieplan-stap-a-b.md`; `evidence/stap-a/scrum4me-server/images.json` |
| Runner | legacy `scrum4me-srv-runner` (id 3) op 12.10.1; poolbundel pint 12.10.1 op digest; `max2-forgejo-runner-02` draait de cyclecontroller (stap D/E af) | `evidence/stap-a/forgejo/runners-summary.tsv`; `forgejo-runner/.env.example`; `evidence/stap-d/` |

## 2. Wat een Forgejo-upgrade hier betekent

Volgens de [upgrade-guide](https://forgejo.org/docs/latest/admin/upgrade/): volledige backup (verplicht bij een nieuwe major, aangeraden bij een patch), `forgejo doctor check --all`, `forgejo manager flush-queues`, image wisselen, starten, opnieuw `doctor check`. Databasemigraties lopen automatisch bij de start en zijn **onomkeerbaar**: Forgejo weigert te starten op een database van een nieuwere versie. Rollback is dus uitsluitend restore uit een backup. De [Docker-installatiedocs](https://forgejo.org/docs/latest/admin/installation/docker/) stellen dat een stap van major X naar X+1 een handmatige operatie met menselijke verificatie is; binnen een major kan de tag `:15` automatisch patches volgen.

Specifiek voor deze host:

- **Het compose-project bevat de live forge én de legacy runner/DinD.** Projectbrede compose-commando's zijn verboden (stap-G-plan B3/C3); een upgrade werkt uitsluitend service-gebonden: `docker compose up -d --no-deps forgejo`.
- **Het is control-plane-onderhoud voor de runnerpool** (`migratieontwerp.md` §7.7/§7.9): de controller op `max2` gaat naar `SOURCE_WAIT` zolang Forgejo onbereikbaar is. Het ontwerp voorziet een vooraf gearmd maintenance-record (max 30 min), maar dat record is in de as-built controller **nog niet armbaar**: `forgejo_runner_cycle.py` definieert `MaintenanceRecord`, `cycle_runtime.py`/`cycle_adapters.py`/`controller.toml.example` kennen er geen laadpad voor (`self.maintenance` blijft `None`). Zolang stap H niet loopt is er geen stabiliteitsklok om te resetten; het plan kiest daarom voor een nette geplande stop van de controller (runbook §7) in plaats van een vals availability-incident.
- **De trust-timer** op beide hosts slaat om 00/06/12/18 uur (+ ≤ 5 min spreiding). Faalt de meting omdat Forgejo net herstart, dan invalideert `publish-trust-verdict.sh` het verdict fail-closed en start er geen runner meer tot de volgende slag. Na een venster wordt de trust-service daarom handmatig gedraaid.
- **De readinessprobe pint geen versie:** `cycle_adapters.py` toetst `/api/v1/version` alleen op schema (`"version"` aanwezig). Een versiewissel quarantaineert de pool dus niet.

## 3. 15.0.7 (LTS) versus 16.0.3 (stable)

Bron: [releases](https://forgejo.org/releases/), [release schedule](https://forgejo.org/docs/latest/admin/release-schedule/).

| Lijn | Versie | Status | Einde support |
|---|---|---|---|
| 15.0 | 15.0.7 (20 aug 2026) | LTS | 15 juli 2027 |
| 16.0 | 16.0.3 (20 aug 2026) | stable | 29 oktober 2026 |
| 17.0 | 15 oktober 2026 | stable | 28 januari 2027 |
| 18.0 | 14 januari 2027 | stable | 29 april 2027 |
| 19.0 | 15 april 2027 | LTS | 13 juli 2028 |

**Wat 15.0.2 mist (15.0.3–15.0.7, releasenotes op Codeberg):** stored XSS op de Actions-pagina en in Actions-foutmeldingen, ongeautoriseerde toegang tot draft releases via de API, arbitrary file read via org-mode, hooks actief tijdens diff-patch, CGNAT-range ontbrak in de `private`-hostmatcher, write-permission-caching bij een eerste push, LFS-locks buiten de bedoelde repo, plus Actions-fixes: *"prevent stuck runner jobs when FetchTask performance is slower than client-side timeout"* (raakt onze `one-job --wait` met `fetch_timeout: 5s`) en *"only look for jobs in repositories where Actions are enabled"*. Patchreleases dragen per semver geen breaking changes.

**CVE-2026-20896** ([security-announcement #56](https://codeberg.org/forgejo/security-announcements/issues/56), 15 juli 2026): het Docker-image zet standaard `REVERSE_PROXY_TRUSTED_PROXIES = *`; met reverse-proxy-authenticatie aan is de login te omzeilen via de directe webpoort. Hier is dat **niet exploitabel** (reverse-proxy-auth uit, poort 3000 alleen op `127.0.0.1:3010`), maar de instelling bepaalt ook welke `X-Forwarded-For` wordt vertrouwd voor het client-IP in logs en rate-limits. Handmatig zetten op v15; bij v16 verdwijnt de default uit het image, maar een expliciet in `app.ini` staande `*` blijft gewoon staan.

**Breaking changes v16.0** ([aankondiging](https://forgejo.org/2026-07-release-v16-0/), releasenotes 16.0.0): (1) pull-mirrors volgen geen HTTP-redirects meer; (2) EXIF-stripping van avatars verwijderd; (3) de trusted-proxies-default; (4) het API-veld `url` van een pull request geeft nu de API-URL in plaats van de web-URL — controleer scrum4me-tooling op `url` versus `html_url`; (5) git-hooks gecentraliseerd (optionele opschoning per repo); (6) JWT-signing-configuratie geünificeerd — `[oauth2] JWT_SECRET` moet dan tegen de nieuwe sleutels worden gecontroleerd. De 16.x-lijn vraagt daarna elk kwartaal een major-upgrade (17 in oktober, 18 in januari) tot v19 LTS.

## 4. Runner 13 en de koppeling met de server-major

Bronnen: [Runner v13.0.0](https://forgejo.org/2026-08-runner-release-v13/) (3 aug 2026), [Runner v13.1.0](https://forgejo.org/2026-09-runner-release-v131/) (31 aug 2026), [runner-releases](https://code.forgejo.org/forgejo/runner/releases), `cmd.go` en `config.example.yaml` op tag v13.1.0.

- **Geen wederzijdse eis.** Runner 13 documenteert geen minimale Forgejo-versie; het enige versiegebonden onderdeel is `one-job --handle` (*"Forgejo >= 15"*). Omgekeerd bundelt Forgejo 16.0.1 nog runner-module v12.13.1. Server en runner zijn dus los van elkaar te upgraden.
- **Breaking changes 13.0.0:** workflowsyntaxfouten worden errors (expressie-interpolatie, ongeldige matrix-excludes); `::set-output`/`::add-path`/`::set-env` verwijderd (geen `ACTIONS_ALLOW_UNSECURE_COMMANDS`-uitweg); automatische `DOCKER_USERNAME`/`DOCKER_PASSWORD`-credentials verwijderd; `${{ gitea.* }}`-context weg; `container.network_mode` weg (`container.network`); `GITEA_*`-omgevingsvariabelen genegeerd; Docker ≥ 25, liefst ≥ 28.0.1 (IPv6-bug). **13.1.0:** geen pseudo-tty meer bij commando-uitvoering (`docker run -it` in een workflow faalt zonder `-t`-verwijdering); experimentele plugin-engine.
- **Security in 13.0.0:** *"prevent commit impersonation via refs/replace/* during action checkout"*. In de 12.x-notes tot 12.13.2 staat die fix niet; of hij is teruggeport is niet gecontroleerd.
- **Gemeten geschiktheid van onze omgeving (9 sep 2026):**
  - Workflows: 14 workflows in 12 repositories (de `workflows`-lijst uit `evidence/stap-a/trust/trust-inventory.json`) via de API opgehaald en gescand op `::set-output|::add-path|::set-env|\bgitea\.[A-Za-z_]+|DOCKER_USERNAME|DOCKER_PASSWORD|docker run … -it|network_mode|ACTIONS_ALLOW_UNSECURE_COMMANDS|^\s*exclude:|format\(`: **nul treffers**. De strengere expressie-evaluatie is niet met grep te bewijzen; Runner 13.1 heeft een `validate`-subcommando dat fase-2 stap 1 (§12 migratieontwerp) kan invullen.
  - Docker: DinD draait 29.4.3 ≥ 28.0.1; host 29.7.2.
  - Config: het 13.1.0-schema heeft nog `server.connections` (`url`, `uuid`, `token`, `token_url`, `labels`, `fetch_interval`), `runner.capacity/timeout/shutdown_timeout/fetch_timeout/envs`, `cache`, `container.network/privileged/docker_host/valid_volumes`, `host.workdir_parent`; `one-job --wait` bestaat nog. De bundel (`runner-config.policy.yml`, `compose.yaml`) gebruikt geen verwijderde sleutel en geen `GITEA_*`-variabele.
  - Registry: de docs verwijzen nu naar `data.forgejo.org/forgejo/runner:13`; `code.forgejo.org` publiceert 13.0.0 en 13.1.0 eveneens. Pin op digest en vergelijk beide registries.

## 5. Aanbeveling en volgorde

1. **Nu: Forgejo 15.0.2 → 15.0.7** in één onderhoudsvenster, samen met het expliciet zetten van `REVERSE_PROXY_TRUSTED_PROXIES` en de rotatie van de twee gelekte secrets (§6). Zelfde major, geen breaking changes, rollback via een vóór het venster bewezen backup. Plan: [implementatieplan-forgejo-15.0.9.md](implementatieplan-forgejo-15.0.9.md).
2. **Fase 2 (Runner 13) blijft zoals ontworpen** (`migratieontwerp.md` §12): ná stap H, canary op `max2`, hoeft niet op Forgejo 16 te wachten. De workflowscan en `validate` vormen stap 1 van §12.
3. **Forgejo 16 alleen als bewuste keuze voor de kwartaaltrein.** Anders op de LTS-lijn blijven tot v19 LTS (april 2027); rechtstreeks naar de laatste versie upgraden wordt door de upgrade-guide ondersteund, per-major stappen zijn het troubleshooting-pad.

Het ontwerpprincipe uit `migratieontwerp.md` §2 (één variabele tegelijk, elke stap terugdraaibaar) is het sterkste argument tegen combineren: runner-rollback is triviaal via de gepinde 12.10.1-image, Forgejo-rollback is een restore.

## 6. Secretlek bij de inspectie van 9 september 2026

De grep op `JWT` in `app.ini` heeft de waarden van `[server] LFS_JWT_SECRET` en `[oauth2] JWT_SECRET` in een agent-gesprek (Claude-transcript, lokaal en bij de leverancier opgeslagen) laten belanden. De waarden staan nergens in deze repo. Rotatie is goedkoop en zit in het plan: `forgejo generate secret JWT_SECRET` / `LFS_JWT_SECRET`, in `app.ini` zetten, herstarten. Gevolgen: OAuth2-tokens die Forgejo als provider heeft uitgegeven en lopende Actions-runtime-tokens vervallen; personal access tokens (gehasht in de database) en websessies blijven werken; LFS-tokens zijn kortlevend.
