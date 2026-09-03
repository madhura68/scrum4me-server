# Exitcodecontract van `forgejo-runner one-job --wait` (Runner 12.10.1)

Gemeten op 2 september 2026 tegen de **gepinde** image
`code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533`
(`forgejo-runner version v12.10.1`), lokaal in Docker Desktop met
`--platform linux/amd64`. De hosts zijn linux/amd64 (`images.json`, Task 2).
Iedere meting is een losse `docker run --rm --entrypoint forgejo-runner …`;
niets hiervan raakt een host of de productie-Forgejo (alle probes gebruiken
`https://voorbeeld.invalid` en een dummy-token van veertig nullen/hexcijfers).

## Wat §8 stap B en §7.9 vragen

| Eis | Uitkomst | Bewijs |
|---|---|---|
| `one-job` kent `--wait` | **ja** — regel 14 van de helptekst: `-w, --wait  waits until task has been assigned` | `one-job-help.txt` |
| de binary accepteert de gerenderde config zonder legacy `.runner`, met exact één connection, absoluut `token_url` en connection-labels | **ja** — de config wordt volledig geparsed en gevalideerd; de enige klacht zonder tokenbestand is dat `file:/run/forgejo-runner-credentials/forgejo-token` niet bestaat (meting d) | meting b en d |
| een ongeldige config geeft non-zero | **ja**, exit 1 | meting c, d, e |
| exact één `server.connections`-verbinding is een harde `one-job`-randvoorwaarde (§4) | **ja, afgedwongen door de binary zelf**: `one-job is only supported with a single connection, but 2 connections are configured`, exit 1 | meting e |

## Metingen

| # | Situatie | Exit | Laatste regel |
|---|---|---|---|
| a | `one-job --help` | 0 | helptekst bevat `-w, --wait` |
| b | gerenderde config, `--config /c.yml one-job --help` | 0 | `Run only one job` |
| c | config met twee connections zonder `uuid` | 1 | `invalid configuration: … connection "a" is invalid: `uuid` is empty` |
| d | gerenderde config, tokenbestand ontbreekt, `--wait` | 1 | `cannot read secret "file:/run/forgejo-runner-credentials/forgejo-token": … no such file or directory` |
| e | twee **complete** connections (uuid + token_url), `--wait` | 1 | `one-job is only supported with a single connection, but 2 connections are configured` |
| f | één connection, geen bereikbaar Docker-endpoint, `--wait` | 1 | `daemon Docker Engine socket not found and docker_host config was invalid` |
| g | één connection, werkend Docker-endpoint, bron onbereikbaar, `--wait` | 1 | `fail to invoke Declare … unavailable: dial tcp: lookup voorbeeld.invalid … no such host` |

Meting c bewijst minder dan het plan suggereerde: de fout gaat over een lege
`uuid`, niet over het aantal connections. Daarom is meting e toegevoegd; die
bewijst de eenconnection-eis wél.

Ook gemeten: een tokenwaarde met koppeltekens of een newline wordt al bij het
parsen geweigerd (`token contains invalid characters`, exit 1). Het echte
tokenbestand moet dus exact de tokenwaarde bevatten zonder afsluitende newline.

## Gevolgen voor de cyclecontroller (§7.9)

1. **Non-zero bij `--wait` is een runner-, config- of initialisatiefout.** Alle
   zeven metingen zijn consistent met het brongebonden contract uit §7.9: een
   normaal afgeronde job — groen of rood — geeft exit 0 en alleen falen vóór of
   buiten de job geeft non-zero. De groene en rode testjob zelf worden in stap E
   op `max2` bewezen; dat kan hier niet, want daarvoor is een echte registratie
   nodig.
2. **Bij een onbereikbare bron pollt `one-job --wait` niet door; hij exit met 1
   op `Declare`** (meting g). De controller start een child pas na twee geldige
   readinessprobes en groene gates, dus deze situatie is een race tussen
   readiness en start. Treedt hij toch op, dan volgt de reguliere route:
   `child_exit` non-zero → `SCRUBBING` → `QUARANTINED`, en die toestand
   herstelt zonder handmatige reset zodra twee READY-probes en groene gates er
   weer zijn (`test_cycle_eventloop` en `test_cycle_fence`). Fail-closed, zoals
   bedoeld.
3. **Meting f** laat zien dat `container.docker_host: "-"` werkt zoals §7.5 wil:
   zonder bereikbaar `DOCKER_HOST` start de runner niet en mount hij geen
   socket. In de Compose-stack levert `DOCKER_HOST=tcp://dind:2375` dat
   endpoint; de gezondheid ervan is de DinD-healthcheck.

## Wat hier bewust niet is gemeten

- Een echte registratie of jobuitvoering: dat vereist een token en een
  runnerrecord en hoort bij stap C/E op `max2`.
- Gedrag bij een bron die *tijdens* het wachten wegvalt (`--wait` al gestart,
  daarna DNS/5xx). De controller leunt daarvoor niet op de exitcode maar op zijn
  eigen readinessprobes en de fence (§7.7); stap E moet dit op de host
  observeren.

## Reproduceren

```bash
IMG=code.forgejo.org/forgejo/runner@sha256:3d49075f9115054ae2485d8cea2819296a904dfd4f00017285168028615d8533
docker run --rm --platform linux/amd64 --entrypoint forgejo-runner "$IMG" one-job --help
bash forgejo-runner/scripts/render-config.sh --uuid 00000000-0000-4000-8000-000000000000 \
  --labels forgejo-runner/labels.txt --policy forgejo-runner/runner-config.policy.yml \
  --out /tmp/validate-config.yml --url https://voorbeeld.invalid
docker run --rm --platform linux/amd64 --entrypoint forgejo-runner \
  -v /tmp/validate-config.yml:/c.yml:ro "$IMG" --config /c.yml one-job --wait ; echo "exit=$?"
```
