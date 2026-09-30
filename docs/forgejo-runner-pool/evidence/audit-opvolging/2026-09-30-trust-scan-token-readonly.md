# Trust-scan-token op max2 vervangen door een read-only token — 2026-09-30

Taak T-149 (story ST-041, PBI-27, sprint S-2026-09-30-3); bevinding AUDIT-013 uit `docs/repo-audit/`.
Geen tokenwaarde in dit document, in argv of in logs: het token werd door JP via `read -rs` in een
staging-bestand op max2 gezet; controles lazen het uitsluitend binnen `sudo sh -c` op de host, en de
koppeling met het databaserecord liep via de laatste acht tekens zonder die te tonen.

## Voor

| Eigenschap | Waarde |
|---|---|
| Token in `credentials/trust-scan.env` | Forgejo-token id 26 `FREX_RUNNER` (site-admin `janpeter`) |
| Scopes | `read:activitypub, read:admin, write:misc, write:notification, write:organization, write:package, write:issue, write:repository` |
| Elders gevonden (zoektocht 30 sep, alleen paden) | nergens: `/etc`, `/opt`, `/srv`, `/home`, `/root` op max2 en scrum4me-server; Mac-config |

## Stappen en uitkomst (max2, ± 20:05–20:15 CEST)

| Stap | Resultaat |
|---|---|
| Staging-bestand `trust-scan.env.new` | `root:root 600`, 55 bytes, één regel `FORGEJO_TOKEN=…`, verschilt van het actieve bestand |
| Scan-CLI met het nieuwe token naar een wegwerpmap | exit 0, `ok: true`, 0 hard, 0 soft; alleen de bekende AANVAARD-meldingen |
| Inventaris oud vs. nieuw token | beide 22 repositories, 0 onleesbaar; inventaris (zonder tijdstempels) byte-identiek (sha256-prefix `875f6362bd3e89be`) |
| Activeren | oud bestand bewaard als `trust-scan.env.bak-frex-20260930` (`root:root 600`); nieuw bestand actief |
| `systemctl start forgejo-runner-trust.service` | Result `success`, exit 0 |
| Verdict | `measured_at` 1790784038 → 1790791099, `ok: true`, target `https://git.jp-visser.nl` |
| `forgejo-runner-cycle.service` | active; geen trustgate-wissel in de journal (bleef groen) |
| Volgende timerslag | 2026-10-01 00:02 CEST |

## Schrijfprobes met het nieuwe token (alleen niet-bestaande doelen)

| Aanroep | HTTP |
|---|---|
| `GET /repos/janpeter/scrum4me-server/branches/audit-probe-nonexistent-7f3a` | 404 (lezen mag, doel bestaat niet) |
| `DELETE` op dezelfde branch | **403** |
| `GET /admin/users/audit-probe-nonexistent-7f3a/orgs` | 404 |
| `DELETE /admin/users/audit-probe-nonexistent-7f3a` | **403** |
| `PATCH /user/settings` met `{}` | **403** |

## Na

| Eigenschap | Waarde |
|---|---|
| Token | id 39 `trust-scan-max2-2026-10`, aangemaakt 2026-09-30 |
| Scopes | `read:admin, read:repository` |

## Open (T-150)

- `FREX_RUNNER` (id 26) intrekken door JP, ná minstens één groene timerslag met het nieuwe token.
- Daarna `credentials/trust-scan.env.bak-frex-20260930` op max2 verwijderen: het bevat het oude token.
