---
status: draft
idea: IDEA-221
product: scrum4me-server (cmsx8zbdh0002hk7rcgxxr00k)
last_updated: "2026-09-25"
---

# Credentials veilig roteren — ontwerp (IDEA-221)

## 1. Doel in JP's woorden

> Per credential een runbook dat zegt waar het staat, wie het gebruikt en hoe je het roteert
> zonder downtime of lek.

Aanleiding: wachtwoorden van DB-rollen staan verspreid over bestanden op drie hosts en rotatie
gebeurt ad hoc. Op 2026-09-24 belandde het wachtwoord van `scrum4me_web_runtime` in het journal
van `scrum4me-server` via de argv van `sudo sed`. Dat wachtwoord is nog niet geroteerd.

**Eerst bruikbare resultaat.** Een generiek rotatierunbook plus een klein hulpscript, bewezen
met de echte rotatie van `scrum4me_web_runtime`. Die rotatie ruimt meteen het lek van 24-09 op.

**Hoe het resultaat zich toont.** De rotatie is uitgevoerd. Alle 15 consumers verbinden met het
nieuwe wachtwoord, het oude wachtwoord wordt geweigerd, `prisma_migrate_precheck` is groen, en
geen enkele stap zette een secret in argv, journal, log, issue of transcript.

**Niet-doelen.**

- Een orchestrator die één rol in één commando over alle hosts roteert (optie C). Pas
  overwegen na deze eerste praktijkproef.
- De rotatie van andere rollen of tokens. Die krijgen alleen een skeletkaart.
- Wijzigingen aan `pg_hba.conf`, de `trust`-regels of docker-groepslidmaatschap.
- Smallere rollen per consumer (IDEA-222) en de MCP-broker (IDEA-220).

## 2. Gemeten uitgangssituatie (2026-09-25)

Alle metingen hieronder toonden alleen namen, nooit waarden.

### Consumers van `scrum4me_web_runtime`

| # | Host | Bestand | Eigenaar/mode | Geladen door | Herladen |
|---|---|---|---|---|---|
| 1 | srv | `/srv/scrum4me/compose/worker-idea.env` | ops-agent 600 | compose `env_file` | `docker compose up -d --force-recreate <svc>` |
| 2 | srv | `/srv/scrum4me/compose/worker-deploy.env` | ops-agent 600 | idem | idem |
| 3 | srv | `/srv/scrum4me/compose/worker-docs.env` | ops-agent 600 | idem | idem |
| 4 | srv | `/srv/scrum4me/compose/worker-codex.env` | ops-agent 600 | idem | idem |
| 5 | srv | `/srv/scrum4me/secrets/workers.env` | ops-agent 600 | idem | idem |
| 6 | srv | `/srv/scrum4me/secrets/mcp-http.env` | ops-agent 600 | idem | idem |
| 7 | srv | `/srv/scrum4me/secrets/copilot.env` | ops-agent 600 | idem | idem |
| 8 | srv | `/srv/scrum4me/repos/Scrum4Me/.env` | janpeter 670 + ACL `ops-agent` | `scrum4me-web.service` | `sudo systemctl restart scrum4me-web` |
| 9 | srv | `~/.claude.json` | janpeter | host-MCP (Claude) | nieuwe sessie of MCP-reconnect |
| 10 | srv | `~/.codex/config.toml` | janpeter | host-MCP (Codex) | idem |
| 11 | max2 | `/srv/scrum4me/compose/worker-idea.env` | ops-agent 600 | compose `env_file` | `docker compose up -d --force-recreate <svc>` |
| 12 | max2 | `/srv/scrum4me/compose/worker-codex.env` | ops-agent 600 | idem | idem |
| 13 | max2 | `~/.claude.json` | janpeter | host-MCP (Claude) | nieuwe sessie of MCP-reconnect |
| 14 | mac | `~/.claude.json` | janpeter | host-MCP (Claude) | idem |
| 15 | mac | `~/.codex/config.toml` | janpeter | host-MCP (Codex) | idem |

Bronnen van deze tabel:

- `grep -rlE 'scrum4me_web_runtime:[^@]+@'` over `/srv/scrum4me`, `/etc`, `/opt`, `~/.config`,
  `~/restore-bootstrap`, `~/.claude.json` en `~/.codex/config.toml`.
- `env_file`-regels in `/srv/scrum4me/compose/docker-compose.yml`.
- `pg_stat_activity`. Die liet de host-MCP's zien (`s4m-mcp:{mac,max2,scrum4me-server}:claude`),
  die de eerste bestandsgrep miste.

Overige metingen:

- De max2-workers verbinden met `192.168.0.154:5432`; dat is srv. De `scrum4me-postgres` op
  max2 staat los van deze rol.
- `log_statement = none` op de srv-Postgres.
- Het bestaande runbook `Ops-dashboard/docs/runbooks/s4m-queue-credential-rotation.md` zet het
  wachtwoord in argv (`psql -c "ALTER ROLE … PASSWORD '<nieuw>'"`, `PGPASSWORD='<oud>' psql`).
  Dit ontwerp vervangt die stappen.

**Regel.** De inventaris is een momentopname. Fase 0 van elke rotatie meet hem opnieuw, via
bestandsgrep én `pg_stat_activity`. Een consumer die alleen in `pg_stat_activity` opduikt, blokkeert
de rotatie totdat zijn bestand gevonden is.

## 3. Onderdelen

### 3.1 `scripts/rotate-env-credential`

Python 3, alleen stdlib, één bestand. Het wordt geïnstalleerd als
`/usr/local/sbin/rotate-env-credential` (root 755) op srv en max2. Op de mac draait het
rechtstreeks uit de repo-checkout, als janpeter.

**Harde regels.**

- Een secret komt alleen binnen via **stdin**: één regel, afsluitende newline toegestaan.
- Uitvoer bevat nooit een secret, ook geen hash-prefix. Toegestaan zijn paden, aantallen, modes,
  stempels en `ok`/`FAIL`.
- Het nieuwe wachtwoord moet `^[0-9a-f]{64}$` zijn. Daarmee is het URL-veilig zonder
  percent-encoding. Anders volgt een weigering.
- Exitcode 0 alleen bij volledig succes. Bij elke fout in een batch blijft de rest onaangeroerd.

**Subcommando's.**

| Commando | Doet | Weigert als |
|---|---|---|
| `rewrite --role R --file F… [--dry-run]` | Vervangt in elke regel van F alleen het wachtwoorddeel van `://R:<pw>@`. Werkt in elk tekstformaat (env, JSON, TOML). Per bestand, in deze volgorde: back-up `F.bak-<UTC-stempel>` (mode 600, zelfde eigenaar); tijdelijk bestand in dezelfde map met dezelfde eigenaar en mode; fsync; controleren dat F sinds het inlezen niet gewijzigd is (mtime en grootte); atomaire rename. Meldt per bestand het aantal vervangingen en waarschuwt bij een mode ruimer dan 640. | een bestand 0 treffers heeft (`--dry-run` meldt dat alleen); F tijdens het schrijven wijzigde; het wachtwoord ongeldig is |
| `rollback --stamp S --file F…` | Zet `F.bak-S` atomair terug op F. | een back-up ontbreekt |
| `alter-role --role R [--container scrum4me-postgres]` | Berekent een SCRAM-SHA-256-verifier (4096 iteraties, willekeurige salt) en stuurt `ALTER ROLE "R" PASSWORD '<verifier>'` via stdin naar `docker exec -i <container> psql -U scrum4me -d scrum4me -v ON_ERROR_STOP=1`. Postgres ziet het leesbare wachtwoord nooit. | R niet bestaat of `psql` een fout geeft |
| `probe --role R --file F [--expect ok\|reject]` | Haalt de DSN van R uit F. Schrijft `PGPASSWORD`, `PGHOST`, `PGPORT`, `PGUSER` en `PGDATABASE` naar een tijdelijk bestand (mode 600, verwijderd in `finally`). Draait `docker run --rm --pull never --network host --env-file <tmp> postgres:17 psql -tAc 'select 1'`. Beoordeelt het resultaat tegen `--expect`. | de uitkomst niet overeenkomt met `--expect` |
| `scan --role R PATH…` | Doorzoekt paden recursief naar `R:<x>@`. Classificeert elke treffer tegen het wachtwoord op stdin als `huidig`, `placeholder/regex` (bevat `< > * [ ^ $` of spaties) of `ANDERS`. Print alleen pad, regel en klasse. | — (exit 1 als er een `ANDERS`-treffer is) |

`probe` draait op de host die het bestand heeft, zodat ook het netwerkpad van die host bewezen
wordt: LAN vanaf max2, tailnet vanaf de mac. Op de mac vereist dat een draaiende Docker. Is die
er niet, dan is de probe vanaf de mac optioneel en volstaat de MCP-`health`-canary.

### 3.2 Keychain op de mac

- Het nieuwe wachtwoord wordt op de mac gegenereerd en in de Keychain opgeslagen als generic
  password met service `s4m-db-<rol>` en account `new`.
- Het oude wachtwoord gaat vóór de flip naar het item met account `old`, gelezen uit een
  srv-back-up via `ssh … sudo cat` in een pipe. Het blijft daar tot fase 4.
- **Te bewijzen in het eerste increment:** hoe je een item vult zonder dat de waarde in argv
  staat. `security add-generic-password … -w` als laatste argument zonder waarde vraagt
  interactief om het wachtwoord. Het is niet bewezen dat die prompt stdin accepteert.
- Toegestaan zijn alleen methoden waarbij `ps` de waarde niet kan tonen: de interactieve prompt
  (plakken vanuit het klembord) of een aanpak in python of Swift via de Security-API.
- Uitlezen gaat via `security find-generic-password -s s4m-db-<rol> -a new -w` in een pipe. Dat
  is veilig, want de waarde gaat naar stdout en niet naar argv.

**Transport:**

```bash
security find-generic-password -s s4m-db-<rol> -a new -w | ssh <host> sudo rotate-env-credential …
```

### 3.3 Runbook `docs/runbooks/credential-rotation.md`

Het runbook heeft drie delen:

1. **Principes.** Geen secrets in argv, journal, issues, logs, transcripts of de queue. Back-up
   vóór elke wijziging. Eerst meten, dan wijzigen.
2. **Generieke procedure**, in fasen 0–4 (§4) met een afvinklijst.
3. **Kaarten per credential.** Elke kaart bevat: rol en wat die ontsluit; consumers met
   herlaadcommando (de tabel uit §2); de canary-verwachting per consumer (`application_name`
   of `client_addr`); de volledige commandoblokken; de datum van de laatste rotatie.
   - **`scrum4me_web_runtime`**: volledig, bewezen met de eerste rotatie.
   - **Skeletkaarten** met alleen de bekende locaties uit IDEA-221: `s4m_queue`,
     `ops_dashboard_mac`, `scrum4me` (migrator), `ops_readonly`, `scrum4me_app`,
     `scrum4me_dispatch`/`s4m_dispatch_projector` (NOLOGIN), `SCRUM4ME_TOKEN`, `FORGEJO_TOKEN`,
     `forgejo-tag.token` en de dispatch-sleutels. Elke skeletkaart vermeldt dat ze bij de
     eerste rotatie van die credential opnieuw gemeten en aangevuld moet worden.

Verwijzingen in de Ops-dashboard-repo:

- `s4m-queue-credential-rotation.md` krijgt bovenaan een verwijzing naar dit runbook, met de
  mededeling dat de argv-stappen verouderd zijn.
- `env-tokens.md` krijgt een verwijzing naar de kaarten.

Die twee wijzigingen gaan als losse commit in de Ops-dashboard-repo.

## 4. Procedure

### Fase 0 — voorbereiden (niet-destructief)

1. **Rustig moment.** Wacht tot `check_queue_empty` leeg is en geen agent-job een claim heeft
   of draait. Recreate en MCP-herstart breken lopende jobs en sessies af; dit is JP's keuze van
   2026-09-25. Meld in lopende sessies op de drie hosts dat hun MCP straks herstart.
2. **Inventaris opnieuw meten** (§2-regel). Draai `rewrite --dry-run` per host en vergelijk de
   aantallen met de kaart. Een verschil betekent stoppen en de kaart bijwerken.
3. **Wachtwoorden in de Keychain.** Het oude gaat naar `old`, het nieuwe wordt gegenereerd en
   komt in `new` (§3.2).
4. **Scripts installeren** op srv en max2 vanaf de repo-commit. Leg de commit-SHA vast.

Tot hier is er niets gewijzigd.

### Fase 1 — flip (zo kort mogelijk achter elkaar)

1. **Bestanden herschrijven** op srv, max2 en de mac met `rewrite` (wachtwoord uit Keychain
   `new` via stdin). Dit heeft nog geen effect, want draaiende processen houden hun env in het
   geheugen. Noteer de stempel.
2. **`alter-role`** op srv. Noteer `T_alter`.
3. **Direct herladen:**
   - `docker compose up -d --force-recreate` voor de services van 1–7 op srv en 11–12 op max2;
   - `systemctl restart scrum4me-web`;
   - de host-MCP's opnieuw starten op srv, max2 en de mac.

Het venster waarin nieuwe verbindingen falen, loopt van stap 2 tot stap 3. Bestaande
verbindingen blijven leven, want Postgres authenticeert alleen bij het verbinden.

Deze volgorde (eerst bestanden, dan `ALTER ROLE`) wijkt bewust af van de volgorde in IDEA-221
(eerst `ALTER ROLE`, dan de consumers). Zo is het faalvenster alleen de herlaadtijd, niet de
hele distributietijd.

### Fase 2 — bewijzen

1. **Canary.** Voor elke consumer in de kaart bestaat een sessie van de rol met
   `backend_start > T_alter`. Die wordt gematcht op `application_name`, of op `client_addr`
   voor consumers zonder naam. De query gaat via stdin naar `docker exec -i … psql`.
2. **Healthchecks.**
   - Web: HTTP 200 op de publieke URL.
   - Workers: containers `healthy`.
   - MCP: `health` vanaf elke host.
3. **Negatieve proef.** `probe --expect reject` op de back-up van één srv-bestand en één
   max2-bestand, en `probe --expect ok` op dezelfde huidige bestanden.
4. **`prisma_migrate_precheck` groen.**
5. **Residu.** `scan` over alle 15 paden, `~/.claude/projects`, `~/.claude/file-history`,
   `~/.codex`, `~/.bash_history` en `~/.zsh_history` op alle drie de hosts, met het wachtwoord
   uit `new` op stdin. Verwachting: geen `ANDERS`-treffers buiten de `.bak-*`-bestanden.

### Fase 3 — rollback (alleen als fase 2 rood is en niet binnen 15 minuten te herstellen)

1. `rollback --stamp S` op alle hosts.
2. `alter-role` met het wachtwoord uit Keychain `old`.
3. Hetzelfde herladen als in fase 1, stap 3.

Loopt één consumer achter, controleer dan eerst diens bestand. Dat is geen reden om terug te
rollen.

### Fase 4 — afronden

1. Verwijder de `.bak-<S>`-bestanden. Toon de lijst eerst en laat JP bevestigen.
2. Verwijder het Keychain-item `old`.
3. ~~Zet `Scrum4Me/.env` op mode 600.~~ **Vervallen (2026-09-25, T-85):** `scrum4me-web` draait
   als `ops-agent` en leest `.env` via een POSIX-ACL (`user:ops-agent:rwx`). De "670" is het
   ACL-masker; `other::---`, dus het bestand is niet world-readable. `chmod 600` zou het masker op
   `---` zetten en de webapp breken. `rewrite` en `rollback` behouden de ACL.
4. Werk de kaart bij met de datum van de laatste rotatie en eventuele nieuwe consumers.
5. De journal-regel van 2026-09-24 bevat nu een dood wachtwoord. Die blijft staan en wordt als
   zodanig vastgelegd op de kaart. Het journal wordt niet gewist.

## 5. Acceptatie

1. `scrum4me_web_runtime` is geroteerd volgens §4, en alle stappen in fase 2 zijn groen.
2. Tijdens de rotatie verscheen geen secret in argv. Dat blijkt uit de tests (§6) en uit de
   commando's in het runbook: overal pipe of stdin, nergens een waarde als argument.
3. Het runbook bevat de volledige kaart voor `scrum4me_web_runtime` en skeletkaarten voor de
   overige credentials.
4. Beide Ops-dashboard-runbooks verwijzen naar het nieuwe runbook.

## 6. Verificatie van het script

`python3 -m unittest` in `scripts/tests/`, zonder netwerk:

- `rewrite` vervangt alleen het wachtwoorddeel, in env-, JSON- en TOML-fixtures. Andere rollen
  op dezelfde regel of in hetzelfde bestand blijven ongemoeid.
- Eigenaar en mode blijven behouden. De back-up bestaat en heeft mode 600.
- Het script weigert bij 0 treffers, bij een ongeldig wachtwoord en bij een bestand dat tussen
  lezen en schrijven wijzigde.
- **Geen lek:** stdout, stderr en elk logbestand bevatten het testwachtwoord niet, ook niet
  bij fouten.
- `rollback` herstelt byte-identiek.

Een integratietest tegen een wegwerp-Postgres-container (`docker run --rm postgres:17`):

- `alter-role` zet een verifier waarmee `probe --expect ok` slaagt.
- Het oude wachtwoord geeft bij `probe --expect reject` een weigering.
- Het Postgres-log van die container bevat het leesbare wachtwoord niet, ook niet met
  `log_statement=all`.

## 7. Risico's

| Risico | Maatregel |
|---|---|
| Een consumer ontbreekt in de inventaris | Fase 0 meet via bestandsgrep én `pg_stat_activity`; een onbekende consumer blokkeert de rotatie. De canary in fase 2 toont een missende herlading. |
| Claude Code overschrijft `~/.claude.json` tijdens `rewrite` | Controle op wijziging vóór de rename. Een race wordt dan een weigering en daarna een herhaling, en geen stil verlies. Kan een draaiende sessie de oude waarde later terugschrijven? Dat controleert de residu-`scan` in fase 2. |
| Een recreate breekt een lopende job af | Rustig moment met een lege queue (fase 0.1). |
| Het Keychain-item gaat verloren | Het oude wachtwoord staat tot fase 4 in `old` én in de back-ups; het nieuwe staat na fase 1 in alle bestanden. |
| `docker run postgres` downloadt een image | `postgres:17` staat lokaal op srv én max2 (gemeten 2026-09-25); `probe` gebruikt `--pull never`. |
