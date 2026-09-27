# Rotatie `scrum4me_web_runtime` — 2026-09-27 (T-86, IDEA-221)

Uitgevoerd door mac:claude, met GO van JP op het moment zelf. Script
`rotate-env-credential` op commit `9832e4b` (sha256-prefix `baedd4a82990f3d9`, gelijk op mac,
srv en max2). **Geen waarden in dit document.**

## Fase 0 — voorbereiden

| Controle | Uitkomst |
|---|---|
| Queue | `check_queue_empty`: 0 jobs. Actieve sessies scrum4me-server:claude en max2:claude vooraf gewaarschuwd via een queue-`info` |
| `rewrite --dry-run` | srv 17 treffers in 10 bestanden, max2 6 in 3, mac 3 in 2: gelijk aan de kaart |
| `pg_stat_activity` | alleen bekende consumers (srv-containers, host `172.18.0.1`, max2 `.158`, mac tailnet) |
| Keychain `old` | hex64. `scan` met `old`: overal `huidig` (srv 17, max2 6, mac 3) |
| Keychain `new` | hex64, verschilt van `old` (vergeleken via een pipe) |
| `probe --expect ok` | srv `Scrum4Me/.env` (127.0.0.1) ok, max2 `worker-idea.env` (192.168.0.154) ok |
| compose | `config -q` ok als ops-agent op beide hosts. Replicas srv: idea 2, deploy 2, docs 1; `N_max2=2` |

## Fase 1 — flip

| Stap | Tijd (UTC) | Uitkomst |
|---|---|---|
| start | 10:28:38 | |
| `rewrite` srv | 10:28:39 | stamp `20260927T102839_527883Z`, 10× ok; WARN mode 670 op `Scrum4Me/.env` (ACL-masker, verwacht) |
| `rewrite` max2 | 10:28:40 | stamp `20260927T102840_214648Z`, 3× ok |
| `rewrite` mac | 10:28:40 | stamp `20260927T102840_345444Z`, 2× ok |
| `alter-role` | **10:28:40** (`T_alter`) | ok |
| recreate srv (7 services) + restart web | tot 10:28:5x | compose rc 0, web `active` |
| recreate max2 (`--scale worker-idea=2`) | 10:28:56 | compose rc 0 |

## Fase 2 — bewijzen

| Controle | Uitkomst |
|---|---|
| Canary | `nieuw ≥ 1` voor alle srv-containers, `scrum4me-web`/`-listen`, `mcp-http` en de max2-containers. De host-MCP's `s4m-mcp:{mac,max2,scrum4me-server}:claude` waren eerst nog `oud` en na JP's herstart (~10:42) `nieuw`. `copilot` verbindt pas bij gebruik; geen DB-fouten in zijn log |
| Containers | alle `running`, restarts 0 |
| Web | HTTP 200; ACL `user:ops-agent:rwx` op `Scrum4Me/.env` behouden |
| Negatieve proef | `probe --expect reject` op de `.bak` op srv (127.0.0.1) en max2 (LAN): geweigerd. `--expect ok` op de huidige bestanden: geslaagd |
| `prisma_migrate_precheck` | policy-hash, identity en policy-precheck: ok (rc 0) |
| Residu | geen `LEK` op srv, max2 of mac. `ANDERS` = het nu dode oude wachtwoord, fixture-tekst (`OLD`, `{OLD}`) en een oudere niet-hex waarde in mac-transcripts, die met `probe --expect reject` is geweigerd |
| Mislukte logins | 5 tijdens het herladen (10:28:50–54, oud web-proces). Daarna tot ~13 per minuut van de nog niet herstarte host-MCP's; de laatste om 10:42:02, daarna 0 (90 s tcpdump bevestigt dat) |

## Fase 4 — afronden

Back-ups (15, stempels hierboven), twee oudere handmatige kopieën op srv en het
Keychain-item `old`: verwijderen na JP's akkoord (zie hieronder).

## Opmerkingen

- Tijdens het residu-onderzoek toonde mac:claude de eerste 3 tekens van de oudere, al dode
  niet-hex waarde. Die waarde wordt geweigerd, dus er is geen risico. Voor de volgende keer:
  toon bij classificatie alleen de lengte en de vorm, geen prefix.
