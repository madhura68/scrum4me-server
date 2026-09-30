# Onderzoek — Forgejo 15.0.2 → 17.0 op `scrum4me-server`

**Datum:** 28 september 2026; bijgewerkt 30 september 2026 (besluit 15.0.9 eerst, wegwerpproef, mirror-scripts in de repo)  
**Besluit (JP, 28 sep 2026):** doel is Forgejo **17.0 na de release van 15 oktober 2026**, niet 16.0.5 (16.0 is end-of-life op 29 oktober 2026) en niet de LTS-lijn 15.0.x. Dit vervangt aanbeveling 3 van [forgejo-upgrade-onderzoek-2026-09.md](forgejo-upgrade-onderzoek-2026-09.md) §5; §1–§2 en §6 van dat onderzoek (gemeten uitgangssituatie, wat een upgrade hier betekent, secretlek) blijven de grondslag.  
**Besluit (JP, 30 sep 2026):** eerst naar **15.0.9** (LTS-patch, §6), eind oktober naar 17.0. Het 17.0-plan start dus vanaf 15.0.9, met trusted proxies en secretrotatie al afgehandeld in het 15.0.9-venster.  
**Status:** onderzoeksrecord bij [implementatieplan-forgejo-17.0.md](implementatieplan-forgejo-17.0.md).  
**Antwoord in één zin:** een directe sprong 15 → 17 wordt door de upgrade-guide ondersteund; de breaking changes van 16.0 en 17.0 raken onze eigen tooling nauwelijks (alle PR-links lezen `html_url`), in een wegwerpproef draaide Runner 12.10.1 een job tegen het 17.0-testimage (§5); wat alleen op onze eigen data te bewijzen is — de migratieduur, de trustgate met het echte verdict, de finale release — meet het plan in een geïsoleerde proefmigratie vóór het venster; los daarvan mist 15.0.2 vandaag twee als *Critical* gepubliceerde RCE-fixes, reden voor de tussenstap naar 15.0.9.

## 1. Versiestand (gemeten 28 september 2026)

| Wat | Waarde | Bron |
|---|---|---|
| Live forge | `15.0.2+gitea-1.22.0` | `GET https://git.jp-visser.nl/api/v1/version` |
| Forgejo 15.0 (LTS) | 15.0.9 (17 sep 2026), EOL **15 juli 2027** | Codeberg-releases `forgejo/forgejo`; docs `release-schedule.md` (branch `next`) |
| Forgejo 16.0 | 16.0.5 (17 sep 2026), EOL **29 okt 2026** | idem |
| Forgejo 17.0 | release **15 okt 2026**, EOL **28 jan 2027**; branch `v17.0/forgejo` bestaat, tag `v18.0.0-dev` op 24 sep; milestone "Forgejo v17.0.0" 0 open | idem; Codeberg-API branches/tags/milestones |
| Forgejo 18.0 / 19.0 (LTS) | 14 jan 2027 / 15 apr 2027 (EOL 19: 13 jul 2028) | `release-schedule.md` |
| Forgejo Runner | 13.2.0 (18 sep 2026), 13.1.0, 13.0.0; laatste 12.x = 12.13.2 | `code.forgejo.org/forgejo/runner` releases |

Gevolg van de keuze voor 17.0: de forge verlaat de LTS-lijn. 17.0 is tot 28 januari 2027 ondersteund; daarna volgt 18.0 (januari) en 19.0 LTS (april 2027). Patchreleases hebben geen vaste cadans (16.0.x: 21 jul, 30 jul, 20 aug, 10 sep, 17 sep).

## 2. Upgradepad

- **Direct 15 → 17 is de ondersteunde route.** De upgrade-guide op branch `v17.0` van `forgejo/docs` (`docs/admin/upgrade/index.md` r. 65): *"upgrade straight to the latest released Forgejo version"*; er is geen verplichte tussenstap op 16.x. Voor 16 en 17 staan alleen **optionele** opruimstappen (r. 109: per-repo `pulls/*.patch`; r. 119–130: de oude per-repo `hooks`-mappen, veilig te verwijderen als er geen custom server-side hooks zijn).
- **Backup:** verplicht bij een major; de guide wil een consistent momentopname. Wij nemen die koud (forge gestopt): `pg_dump` van database `forgejo` + rsync van `/data` — hetzelfde model als het 15.0.9-plan.
- **Vooraf `forgejo manager flush-queues`** (queue-data is niet compatibel tussen versies), **achteraf `forgejo doctor check --all`**.
- **Downgrade is onmogelijk:** een ouder binary weigert te starten op een database van een nieuwere versie. Rollback = restore.

## 3. Breaking en relevante wijzigingen 16.0 + 17.0, met onze blootstelling

Bronnen: `release-notes-published/16.0.0.md`, de PR's hieronder (Codeberg `forgejo/forgejo`, label en milestone nagekeken 28 sep), de v17-broncode op `v17.0/forgejo`. De finale 17.0-releasenotes bestaan nog niet (`release-notes-published/17.0.0.md` is een placeholder); het plan heeft daarom een releasegate (Fase 0.0).

| # | Wijziging | Bron | Onze blootstelling (gemeten) | Maatregel |
|---|---|---|---|---|
| B1 | JWT-signingconfig geünificeerd (`<prefix>SECRET`, `…SIGNING_ALGORITHM`, …); *"existing behavior is preserved"*. Een secret dat niet decodeert → Forgejo logt *creating new key*, genereert een nieuwe en schrijft `app.ini` | #11194 (16.0); `modules/setting/security.go` op `v17.0/forgejo` | `[oauth2] JWT_SECRET` en `[server] LFS_JWT_SECRET` staan in `app.ini` (JP 9 sep) | Proef R.6 en venster 4.4: startlog vrij van *creating new key*; `app.ini` schrijfbaar voor de containergebruiker (0.3) |
| B2 | `[oauth2] JWT_KEYS_ACCEPTED`; JWT-parser eist standaard een `exp`-claim | #12307 (17.0) | 0 OAuth2-apps bij `janpeter` (inventaris); site-breed door JP te bevestigen (0.10) | 0.10 |
| B3 | Default `REVERSE_PROXY_TRUSTED_PROXIES = *` uit de Docker-template | #12782 (16.0, `breaking`) | Template geldt alleen voor een nieuw `app.ini`; onze expliciete `*` blijft staan | Expliciet zetten op het proxynetwerk gebeurt in het 15.0.9-venster (2.5a van dat plan) |
| B4 | API-veld `url` van een pull request (en van een issue dat een PR is) = API-URL i.p.v. web-URL; `html_url` ongewijzigd | #12643 (16.0, `breaking`) | **Niet geraakt:** alle PR-links in onze code lezen `html_url` (§4) | Geen actie vooraf; D+1-controle 6.3 op de eerstvolgende tooling-PR |
| B5 | Mirrors volgen geen HTTP-redirects meer; `[migrations]`-allow/denylijsten bij elke pull/push | #13129 (16.0, `breaking`) | 0 pull-mirrors; 18 push-mirrors, alle naar `github.com` | Baseline 0.14, D+1-controle 6.3 |
| B6 | Mirroring/migraties over `http://`/`git://` falen tenzij `[migrations] ALLOW_UNENCRYPTED = true` | #13490 (17.0, `breaking`) | idem B5; schema per mirror te meten | 0.14 |
| B7 | Configduren strikt geparsed; een ongeldige waarde faalt het laden | #10273 (17.0, `breaking`) | Onbekend welke duurwaarden `app.ini` bevat | Proef R.3 start 17 op een kopie van ónze `app.ini`; configfouten zijn sinds #14408 luid |
| B8 | Server-side git-hooks gecentraliseerd (`core.hooksPath`); doctor-check `hooks` en `admin regenerate hooks` verwijderd | #10397 (16.0) | Custom hooks onbekend (API weigert zonder hook-recht). In de wegwerpproef verdwijnt in `doctor check --all` precies één check ("Check if hook files are up-to-date and executable": 28 → 27 checks) | 0.15 meet `DISABLE_GIT_HOOKS` + custom hookbestanden; R.4 toont de verdwenen check |
| B9 | Overgeslagen checks krijgen status `skipped` i.p.v. `success` | #12606 (16.0) | Ops-dashboard-releasegate eist dat **alle** contexts `success` zijn (`lib/release-candidates/service.ts:142`); `scrum4me-mcp` `ci.yml:13` heeft een job met `if: github.event_name == 'pull_request'` die op main wordt overgeslagen | Buiten scope van de forge-upgrade: bevinding voor JP (plan, "Bevindingen buiten scope"); D+1-observatie 6.3 |
| B10 | Markdown: absolute links resolven vanaf de repo-root | #12939 (17.0, `breaking`) | Weergave in de web-UI; geen tooling | Geen |
| B11 | Run-`started`/`stopped` = `null` als niet gezet; action-run-webhookevents deprecated | #14512, #14356 (17.0) | 0 webhooks (inventaris) | Geen |
| B12 | Standaard logbestand `forgejo.log` (symlink `gitea.log`) | #13035 (17.0) | Wij lezen `docker logs`, geen logbestand | Geen |

**Ongewijzigd (gemeten in de v15/v16/v17-swagger en -broncode, onderzoeksagent 28 sep):** paden, parameters en respons van `/api/v1/admin/actions/runners` en `/api/v1/admin/actions/runners/jobs` (lege lijst blijft `null`; `ActionRunJob.status` blijft een platte string, met extra velden `run_id`, `html_url`, `steps`); `cmd/generate.go` en `cmd/manager.go` (dus `generate secret` en `flush-queues`); het Docker-image (gebruiker `git` uid/gid 1000, `GITEA_CUSTOM=/data/gitea`, `VOLUME /data`, s6-entrypoint; Alpine 3.23 → 3.24); minimale PostgreSQL blijft 14 (wij: 17). Nieuw in 17: zes additieve migraties (`v17a_*`), waarvan één `package_version.total_size` over alle pakketversies vult — de looptijd schaalt met het aantal pakketten (Ops-dashboard en `scrum4me-mcp` publiceren generic packages), vandaar de gemeten migratieduur in de proef.

## 4. Inventaris van onze eigen Forgejo-API-consumenten (28 sep 2026)

Alle 22 repositories (defaultbranch, `--depth 1`) plus `~/.claude/skills`, `~/.claude/rules` en de tekstbestanden in `~/.codex` doorzocht.

| Consument | Waar | Wat het leest | Oordeel |
|---|---|---|---|
| PR aanmaken/mergen/reviewen | `scrum4me-mcp` `src/git/pr.ts:112,130,209,519,533` | `html_url`, `merged`, `merge_commit_sha`, `head.sha` | niet geraakt (B4) |
| Auto-merge-detectie | `scrum4me-mcp` `src/git/forgejo-rest.ts:434–468` | `/api/v1/version`; swagger `MergePullRequestOption.merge_when_checks_succeed` | niet in de proef; D+1-controle 6.3 |
| Dispatch-/docs-audit-PR's | `scrum4me-mcp` `src/dispatch/publication.ts:60–72`; `scrum4me-docker` `lib/docs-audit-publication.ts:98` (exacte `html_url`-vergelijking) | `html_url`, `head`/`base` | niet geraakt (B4); D+1-controle 6.3 |
| Review-queue | `Scrum4Me` `lib/review-dispatch/pr-detector.ts:57,84` | `html_url`, `draft`, `head.sha` | niet geraakt |
| Storybuild-checks | `Scrum4Us` `packages/forgejo/src/index.ts:62–142` | `draft`, `merged`, `head`/`base` | niet geraakt |
| Releasegate | `Ops-dashboard` `lib/release-candidates/service.ts:135–145,249–257`; `ops-agent/src/control-room/mac-release-preparer.ts:254–259` | commit-`statuses` (`context`, `status`) | **B9-risico**, zie §3 |
| Trustgate (timer) | `scrum4me-server` `forgejo-runner/scripts/trust_scope_cli.py` | `repos/search`, `contents`, `collaborators`, `teams`, `branch_protections`; faalt dicht bij een onverwachte respons | proef R.4 draait hem tegen 17 |
| Runner-records | `forgejo-runner/scripts/capture-forgejo-records.sh:20` | `/admin/actions/runners`, `labels` als lijst van strings | proef R.4 |
| Connectiviteitsprobe | `forgejo-runner/scripts/cycle_adapters.py:20` | `/api/v1/version` alleen op schema | niet geraakt |
| Canary-verifier | `Ops-dashboard` `scripts/ci/verify-canary.mjs:2` `SERVER_VERSION = '15.0.2'` (handmatig bewijsgereedschap, geen CI-stap) | versie-string | weigert elk nieuw canaryrapport na de upgrade; bevinding voor JP |
| Webhook-ontvanger | `Ops-dashboard` `app/api/release-candidates/webhook/route.ts:24,29` (`X-Gitea-Signature`/`X-Gitea-Event`) | — | 0 webhooks geconfigureerd (repo, user, `/admin/hooks`); niet in gebruik |

De hostdienst `forgejo-mirror-sync.service` op `scrum4me-server` stond op 28 sep in geen enkele repo; op 30 sep zijn de scripts geïmporteerd in `scripts/forgejo-mirror/` (README: elke nacht 02:30 UTC ± 5 min; per repository een push-mirror waarborgen en een sync starten via de Forgejo-API). Het is dus een automatische schrijver; het plan houdt het venster buiten dat tijdstip (0.7) en neemt hem op in het schrijversbesluit (0.16). Achterhaalde instructie buiten deze repo: `~/.codex/AGENTS.md` noemt drie repos pull-mirrors; geen enkele repo is een mirror.

## 5. Runner 12.10.1 tegen Forgejo 17

- Het Actions-protocol gaat van `actions-proto` 0.7.0 naar 0.8.0; de enige wijziging is een nieuwe RPC `UpdateStepSummary`. `runner.go` in 17 doet geen versiecontrole op de runner, en `FetchSingleTask` (gebruikt door `one-job`) bestaat nog. Geen van beide projecten publiceert een compatibiliteitsmatrix of minimumversie.
- **Gemeten op 30 sep in een wegwerpomgeving** ([evidence/forgejo-17.0/recept-proef-2026-09-30.md](evidence/forgejo-17.0/recept-proef-2026-09-30.md)): de gepinde Runner v12.10.1 meldt zich met `server.connections` aan bij `17.0.0-dev-577` (het experimentele `17.0-test`-image), haalt via `one-job --wait` een taak op en de run eindigt `success`. Dat is een proef met de `host`-executor op een lege instance tegen een voorloper van de release; het plan herhaalt hem in R.5 tegen de uitgebrachte 17.0.x op een kopie van onze data.
- Een incompatibiliteit zou anders pas in Fase 5 van het venster blijken, ná de onomkeerbare migratie, en Runner 13 is volgens het ontwerp (§12) pas aan de beurt als fase 1 stabiel is. Daarom blijft R.5 een vast onderdeel van Gate R.
- Runner 13 blijft een losse stap (migratieontwerp §12); de koppeling 16/17 ↔ Runner 13 uit het vorige onderzoek (§4) is ongewijzigd.

## 6. Beveiligingsstand van de draaiende 15.0.2

15.0.2 mist onder meer twee fixes die Forgejo als **Critical** (remote code execution) publiceert: **#14302** (15.0.8: RCE via een kwaadaardige template-repository) en **#14371** (15.0.9: RCE via `ApplyDiffPatch` — web-UI, cherry-pick en de `/diffpatch`-API — plus CSRF op OpenID-koppelingen). #14371 is volgens de releasenotes een variant van de kwetsbaarheid uit #13705, gefixt in 15.0.6, die 15.0.2 dus evenmin heeft. Beide *Critical*-teksten zijn op 28 sep nagelezen in `release-notes-published/15.0.8.md` en `15.0.9.md`. Uitbuiten vereist een geauthenticeerde gebruiker die repositories mag aanmaken of beschrijven; op deze instance hebben naast JP ook agent- en bot-accounts met tokens zulk recht. De 17.0-upgrade kan op zijn vroegst eind oktober; tot dan blijft deze blootstelling bestaan. Een tussenstap naar **15.0.9** is een patch binnen de LTS-lijn (het goedgekeurde 15.0.7-plan, op 30 sep omgezet naar 15.0.9 via een delta-review) en belemmert de latere sprong naar 17 niet. **JP heeft op 30 september voor die tussenstap gekozen** ([implementatieplan-forgejo-15.0.9.md](implementatieplan-forgejo-15.0.9.md)); het 17.0-plan start vanaf 15.0.9.

## 7. Wat nog niet vaststaat

- De finale 17.0.0-releasenotes en eventuele breaking changes die tussen nu en 15 oktober landen → releasegate 0.0 in het plan (niet-gedekte breaking change = STOP + delta-review).
- Een officiële server/runner-compatibiliteitsmatrix bestaat niet; de wegwerpproef (§5) en R.5 op de release vervangen haar.
- De migratieduur op onze data → proef R.3; bepaalt het venster en de R4-beslisgrens.
