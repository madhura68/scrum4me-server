# T-170 — gefixte mirror-scripts geïnstalleerd op scrum4me-server — 2026-09-30

Taak T-170 (story ST-052, sprint S-2026-09-30-4), akkoord JP 30 september 2026. Bron: `main` na PR #85.

| Stap | Resultaat |
|---|---|
| Uitgangssituatie | `/srv/scrum4me/scripts/forgejo-mirror-{sync,lib}.sh` byte-gelijk aan de repo-versie vóór #85 (sha256 `5f7f98f1…`, `dfdb7c98…`); laatste run 11:19: total 22, mirrored 18, skipped_other 4, errors 0 |
| Installatie | backups `*.bak.20260930-t170`; nieuwe versies `0356dfeb…` (sync) en `b8b350db…` (lib), gelijk aan `main` |
| `DRY_RUN=1`, `REPOS_FILTER=scrum4me-server` | rc 0, geen muterende calls, Forgejo 15.0.9, beide tokens OK |
| Echte run (`systemctl start forgejo-mirror-sync.service`, 167 s) | total 22, mirrored 17, skipped_other 4 (ontbrekende GitHub-tegenhangers, bekend), **errors 1** |
| De ene fout | `janpeter/inspannings-monitor`: `push_mirrors-sync` HTTP 500 ×3. Forgejo-log: GitHub weigert de push op `main` door een repository rule (`Review all repository rules at …/inspannings-monitor/rules?ref=refs/heads/main`). Om 11:19 lukte die sync nog. Geen scriptfout; de run ging per repo door, zoals bedoeld (AUDIT-017) |
| Clone-map `/srv/scrum4me/repos/mirrors/` | leeg; geen credential in een git-config |

## Tokens in procesargumenten

Gemeten door `ps` iedere 0,1–0,2 s te bemonsteren tijdens de runs en regels met een tokenwaarde uit
`/etc/forgejo-mirror/{forgejo,github}.env` alleen te tellen (waarden nooit getoond).

- Tweede run, alleen `scrum4me-server`: **0 treffers van het mirror-script** (curl/git). Alle 8 treffers
  kwamen van Forgejo's eigen push-mirror: `git remote-https remote_mirror_<id> https://<user>:<token>@github.com/…`
  en `git-remote-https …` (host-user `janpeter`). Geregistreerd als **ISS-48**; hangt samen met ISS-43 (geen `hidepid`).
- Eerste, volledige run: dezelfde soort Forgejo-regels, plus 7 regels die het patroon
  "Authorization-header in argv" raakten. Welke processen dat waren is niet vastgesteld; in de tweede run kwam
  het niet terug.

## Gelijktijdig op max2 (T-164-vervolg)

Na merge van PR #86 wijst `/opt/forgejo-runner/BUNDLE_COMMIT` naar `main` `943383ea…`; de bundelhash
`ef9dc406…` is ongewijzigd en `verify-stack.sh 943383ea… ef9dc406…` geeft exit 0. `shellcheck` 0.11.0 is op
max2 geïnstalleerd (akkoord JP); `scripts/verify.sh` op max2 tegen `main`: bats 191/0 (1 skip), py 373/0
(2 skips, Postgres-integratie opt-in), shellcheck 21/0 — **GESLAAGD**.
