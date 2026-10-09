# Scanner-uitrol op beide hosts — 9 oktober 2026

Hoort bij T-138 (scrum4me-server PBI-23, ST-037), max2 ISS-16 en ISS-5, en bij stap 8 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Uitkomst.** Beide hosts draaien sinds 2026-10-09 dezelfde compose-collision-scanner. De sha256 van het
bestand uit `ExecStart` is op beide hosts `4b2f739bea7578f947c5178986f10b85436858d5c15d3b69487b6d47e339a233`.
Dat is de bron in Ops-dashboard op `0e38abc` (merge van PR 270, T-132), en via scrum4me-docker `d523e6a`
(merge van PR 126, T-136). Een droogloop van de geïnstalleerde scanner gaf op beide hosts exitcode 0 en
dezelfde hash in de eerste logregel. **Nog open:** de eerstvolgende nachtelijke run (stap 8 van de taak).

Ontwerp gelijk aan de pin `c5c60a9a…`. Er is geen container herstart, geen compose-bestand gewijzigd en geen
systemd-unit gewijzigd.

Dit bestand bevat alleen namen, hashes en aantallen.

## Vooraf

| Host | `ExecStart` | sha256 vooraf | Laatste run | Volgende run |
|---|---|---|---|---|
| scrum4me-server | `/srv/scrum4me/ops-agent-drift/check-compose-collision.sh 154 /srv` | `faf0176619b4…` | 2026-10-09 00:42 CEST, clean | 2026-10-10 00:49 CEST |
| max2 | `/srv/scrum4me/repos/scrum4me-docker/scripts/check-compose-collision.sh max2 /srv` | `37b942accb72…` (10 juli) | 2026-10-09 00:41 CEST, pushte een melding | 2026-10-10 00:37 CEST |

## max2: checkout van scrum4me-docker

De checkout is van `ops-agent`. De bestaande route is een fast-forward als `ops-agent`, dezelfde opdracht als
de ops-agent-commando's `git_fetch` en `git_pull` (`--ff-only`). Geen pull als root. De redeploy-flows zijn
niet gebruikt: die doen `reset --hard` en bouwen de workers opnieuw.

- `fc1ce31` → `d523e6a`, fast-forward. Mee kwamen ook PR 124 (worker-TMPDIR) en PR 125 (docs).
- Geen draaiende container heeft een bind-mount op deze checkout. Alleen `compose-collision-check.service` en
  `ops-agent-drift.service` lezen eruit; `check-ops-agent-drift.sh` is niet gewijzigd. De workercode uit PR 124
  wordt pas actief bij een volgende image-build.
- De bestaande lokale wijziging aan de submodule `vendor/scrum4me-shared` bleef staan.
- Bijvangst, niet aangeraakt: `.git/modules/vendor/scrum4me-shared/index` is van `root:root`, sinds
  2026-10-02 20:33. Dat dateert van vóór deze taak.

## scrum4me-server: alleen de scanner

`apply-drift-runtime.sh` (Ops-dashboard) installeert behalve de scanner ook de drift-checker, de baseline en
vier units, en doet `daemon-reload`. Vooraf vergeleken, repo `/srv/scrum4me/ops-dashboard@c9b6722` tegen
de runtime:

| Onderdeel | Repo vs runtime |
|---|---|
| `check-ops-agent-drift.sh` | gelijk |
| de vier units (`ops-agent-drift.*`, `compose-collision-check.*`) | gelijk |
| baseline `commands.yml` | **verschilt** |
| baseline `flows/redeploy_all.yml`, `refresh_worker_db_env.yml`, `update_codex_worker.yml`, `update_mcp_worker.yml` | **verschilt** |
| overige 19 baseline-flows | gelijk |

Het volledige script had de referentie van de drift-detector verschoven. Dat valt buiten deze taak en had de
vergelijking van de nachtelijke drift-run voor T-135 (stap 9) vertroebeld. Daarom is alleen de scanner
geïnstalleerd, met de regel die het script daarvoor zelf gebruikt:

```bash
install -m 0755 -o root -g root /srv/scrum4me/ops-dashboard/deploy/ops-agent/check-compose-collision.sh \
  /srv/scrum4me/ops-agent-drift/check-compose-collision.sh
```

De bron was in de checkout ongewijzigd ten opzichte van `HEAD`. De vorige runtime-versie (`faf0176619b4…`)
staat tot na de nachtelijke run in `/tmp/check-compose-collision.sh.voor-t138` op scrum4me-server.

**Open, buiten deze taak:** de baseline op scrum4me-server loopt in 5 bestanden achter op de repo. Synchroniseren
is een eigen beslissing (runbook host-config-discipline).

## Na de uitrol

| Host | sha256 van `ExecStart`-bestand | Eigenaar, mode |
|---|---|---|
| scrum4me-server | `4b2f739bea75…` | root:root 755 |
| max2 | `4b2f739bea75…` | ops-agent:ops-agent 755 |

Droogloop, `sudo DRIFT_NO_NOTIFY=1 <pad uit ExecStart> <label> /srv`:

```text
== max2
[check-compose-collision] scanner sha256 (first 12 hex chars): 4b2f739bea75
[check-compose-collision] scanning 11 compose file(s) under /srv
[check-compose-collision] clean: no destructive finding (1 warning(s): duplicate container_name and/or non-runnable stray copies — not alerting)
exit=0
== scrum4me-server
[check-compose-collision] scanner sha256 (first 12 hex chars): 4b2f739bea75
[check-compose-collision] scanning 11 compose file(s) under /srv
[check-compose-collision] clean: no destructive finding (2 warning(s): duplicate container_name and/or non-runnable stray copies — not alerting)
exit=0
```

## Nog te doen

- Stap 8: na de runs van 2026-10-10 (00:37 CEST max2, 00:49 CEST scrum4me-server) het journal van
  `compose-collision-check.service` lezen. De run moet geslaagd zijn en op beide hosts `4b2f739bea75` loggen.
  Daarna `/tmp/check-compose-collision.sh.voor-t138` op scrum4me-server verwijderen.
