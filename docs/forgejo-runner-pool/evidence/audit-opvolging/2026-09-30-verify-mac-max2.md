# `scripts/verify.sh` op de Mac en op max2 — 2026-09-30

Taak T-154 (story ST-043, PBI-29). Branch `feat/audit-sprint-1`, commit `28afe5b` (max2) en
dezelfde boom op de Mac. Op max2 gedraaid vanuit een wegwerpclone in `/tmp` (niet in
`/opt/forgejo-runner`), daarna verwijderd.

## Mac (macOS, bash 3.2 als `/bin/bash`, bsdtar)

| Onderdeel | Stand | Pass | Fail | Skip | Toelichting |
|---|---|---|---|---|---|
| bats | PASS | 159 | 0 | 0 | integratiebestand `test_compose_runner_exec.bats` bewust uitgesloten (opt-in `VERIFY_INTEGRATION=1`) |
| py | PASS | 327 | 0 | 17 | 14× compose-inpak (vereist GNU tar), 2× Postgres-integratie (opt-in), 1× POSIX-ACL (Linux); 4 expected failures (controller-scenario's A, C, D, E tot PBI-34/35) |
| shellcheck | FAIL | 19 | 2 | 0 | de 3 bekende meldingen in `scripts/forgejo-mirror/` (SC2155, SC1090×2); opgelost op `feat/audit-sprint-2` |

## max2 (Ubuntu, bash 5, GNU tar 1.35, Python 3.14.4)

| Onderdeel | Stand | Pass | Fail | Skip | Toelichting |
|---|---|---|---|---|---|
| bats | PASS | 155 | 0 | 4 | 3× shellcheck ontbreekt op de host; 1× bash-3.2-geval n.v.t. |
| py | PASS | 342 | 0 | 2 | alleen de opt-in Postgres-integratie; **de 14 compose-inpak-tests en de ACL-test draaien hier en slagen** |
| shellcheck | FAIL | – | – | – | `shellcheck` is niet geïnstalleerd op max2 |

## Gevonden en opgelost in deze taak

De eerste run op max2 faalde op drie tests die van de host afhingen (commit `28afe5b`):
- `test_check_nonexistent_paths_all_listed` gebruikte de `/opt/forgejo-runner`-paden uit `VALID_TOML`, die op max2 wél bestaan; de test gebruikt nu een niet-bestaande map in tmp.
- `test_scrub_dind.bats` "is POSIX sh" en twee cases in `scripts/tests/test_verify.bats` vereisten `shellcheck`; ze slaan nu met reden over als het ontbreekt.

## Faalgedrag

Aangetoond in de hermetische suite `scripts/tests/test_verify.bats` (falende py-test, falende bats-test,
shellcheck-melding → exit ≠ 0) en live: de Mac-run hierboven eindigt met exit 1 door de shellcheck-meldingen.
