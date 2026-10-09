# Rotatie `ops_readonly` — 2026-10-09 (ISS-51)

Uitgevoerd door scrum4me-server:claude, met akkoord van JP in de sessie. Aanleiding: het
wachtwoord was op 2026-10-01 gelekt in een agent-transcript op srv. Script
`rotate-env-credential` op commit `d99c62d` (sha256-prefix `a4a2bbf9db3e`, gelijk op srv en
max2; daarvoor stond `e3ed792` geïnstalleerd). **Geen waarden in dit document.**

Afwijking van A.2: het nieuwe wachtwoord is niet in de mac-Keychain aangemaakt, maar op srv met
`openssl rand -hex 32` in een 0600-bestand. Van daaruit ging het via een pipe naar max2 en de mac.

## Fase 0 — voorbereiden

| Controle | Uitkomst |
|---|---|
| Inventaris | `sudo grep -rlE` op srv en max2: live consumers srv `ops-dashboard/.env` + `.next/standalone/.env`, max2 `ops-dashboard/.env`, plus back-ups. Zie kaart B.2 |
| Consistentie | het oude wachtwoord (48 tekens, geen hex) is in alle drie de bestanden gelijk (sha256-vergelijking) |
| `pg_stat_activity` | 0 sessies van `ops_readonly` |
| Mislukte logins (7 d) | 0 |
| `probe --expect ok` | max2-env (192.168.0.154): geslaagd |
| compose | `config -q` ok als ops-agent op beide hosts; 1 replica ops-dashboard |
| `rewrite --dry-run` | srv 2 bestanden × 1 treffer, max2 1 × 1 |

## Fase 1 — flip

| Stap | Tijd (UTC) | Uitkomst |
|---|---|---|
| `rewrite` srv | 09:14:39 | stamp `20261009T091439_274392Z`, 2× ok; WARN mode 670 (`.env`, ACL) en 664 (`standalone/.env`) |
| `rewrite` max2 | 09:14:39 | stamp `20261009T091439_565161Z`, 1× ok |
| `alter-role` | **09:14:46** (`T_alter`) | ok |
| recreate max2 | direct erna | container-ID gewijzigd |
| recreate srv | ~1 min later | eerste poging als janpeter faalde (`compose/.env: permission denied`); als ops-agent geslaagd |
| mac | na afloop | door JP |

## Fase 2 — bewijzen

| Controle | Uitkomst |
|---|---|
| In-container login | `begin read only; select current_user` met `SCRUM4ME_DATABASE_URL`: `ok ops_readonly` op srv en max2 |
| Negatieve proef | `probe --expect reject` op de max2-`.bak`: geweigerd. `--expect ok` op de huidige env: geslaagd |
| Mislukte logins sinds `T_alter` | 1, de reject-probe zelf |
| Residu | `scan` met `new`: geen `LEK` op srv en max2. `huidig` alleen in de consumerbestanden. `ANDERS` = oude waarden in back-ups en transcripts, plus niet-wachtwoordtekst |

## Fase 4 — afronden

- Back-ups verwijderd (akkoord JP): srv 8× `.env.bak*`, max2 3× `.env.bak*`.
- max2 `/srv/_attic/2026-07-10/ops-dashboard.broken` verwijderd, met een aantekening in `MANIFEST.txt`.
- Transcript met het gelekte wachtwoord verwijderd (srv, sessie `eaa18dd8`).
- srv `ops-dashboard/.next/standalone/.env` was voor iedereen leesbaar (`other::r--`): nu `setfacl -m o::---`.
  Restrisico: de default-ACL van `.next/standalone` geeft `other::r-x`, dus een nieuwe build op
  de host maakt de kopie weer leesbaar.
- Kaart B.2 `ops_readonly` bijgewerkt.
