---
last_updated: "2026-09-28"
idea: IDEA-221
---

# Credentials roteren — runbook

Hoe je een DB-wachtwoord of token vervangt op alle plekken waar het staat, zonder dat het
ergens lekt en met hooguit een korte onderbreking.

- **Deel A** is de procedure voor DB-wachtwoorden. Een rol heeft precies één wachtwoord, dus er
  is een kort faalvenster.
- **Deel B** bevat de kaarten van de DB-rollen: per rol waar hij staat, wie hem gebruikt en hoe
  je elke consumer herlaadt.
- **Deel C** gaat over tokens: Forgejo-PAT's, Scrum4Me-tokens, Claude- en Codex-credentials.
  Oud en nieuw kunnen daar tegelijk geldig zijn, dus er is geen faalvenster. Het principe uit A.1
  geldt onverkort.

Ontwerp: [`docs/superpowers/specs/2026-09-25-credential-rotation-design.md`](../superpowers/specs/2026-09-25-credential-rotation-design.md).
Hulpscript: [`scripts/rotate-env-credential`](../../scripts/rotate-env-credential).

**Waarden staan nooit in dit document**, alleen locaties, aantallen en commando's.

---

## A. Procedure

### A.1 Principes

1. **Een secret gaat nooit als argument mee.** Niet in argv, niet als `VAR=waarde commando`,
   niet in een `ssh host '…'`-string of een `sh -c '…'`-string. Die zijn allemaal zichtbaar in
   `ps`, en via `sudo` belanden ze in het journal. Dat laatste gebeurde op 2026-09-24 met
   `sudo sed`. Een secret gaat alleen via een **pipe** (stdin) of via een bestand met mode 0600.
2. **Een secret gaat nooit naar de queue, een issue, een commit, een log of een transcript.**
   Queue-berichten staan in platte tekst in de DB, en issues worden naar Forgejo gespiegeld.
   Laat een agent een secret dus ook nooit afdrukken, ook niet "even ter controle".
3. **Eerst meten, dan wijzigen.** Een kaart is een momentopname. Meet de inventaris bij elke
   rotatie opnieuw (fase 0).
4. **Elke wijziging heeft een back-up.** `rotate-env-credential rewrite` schrijft per bestand
   `<bestand>.bak-<stempel>` (mode 0600) en zet bij een fout halverwege zelf alles terug.
5. **Het oude wachtwoord blijft bewaard tot het bewijs groen is**, in de Keychain (`old`) en in
   de back-ups. Pas in fase 4 verdwijnt het.
6. **Dit geldt ook voor de wrappers die een secret doorgeven.** `env -i DATABASE_URL=… prog` en
   `runuser … env -i …` zetten het secret in argv; onder `runuser`/`sudo` logt pam die regel als
   journald `_CMDLINE` (ISS-41: het net geroteerde superuser-wachtwoord stond er 4× in). Geef
   secrets door via `export` in een schone subshell + `exec` (`exec_with_only_env` in
   `prisma-operator.sh`, `runuser -m`). Controleer na elke root-flow:
   `journalctl --since <start> _COMM=runuser -o json` bevat geen `postgresql://…:…@`. Rest-risico:
   Prisma's `schema-engine` krijgt de DSN zelf als `--datasource` in argv (zichtbaar in `ps`,
   niet in het journal); zie ISS-43 (hidepid).

### A.2 Gereedschap

**`rotate-env-credential`** (python3, alleen stdlib). Het script leest secrets alleen van stdin
en print ze nooit.

| Subcommando | Wat het doet | Secret op stdin |
|---|---|---|
| `rewrite --role R --file F… [--dry-run]` | vervangt het wachtwoord in `://R:<pw>@` in env-, JSON- en TOML-bestanden; behoudt mode, eigenaar en POSIX-ACL | nieuw (niet bij `--dry-run`) |
| `rollback --stamp S --file F…` | zet `F.bak-S` terug | — |
| `alter-role --role R` | zet het wachtwoord als SCRAM-verifier, dus Postgres ziet de leesbare waarde nooit | nieuw |
| `probe --role R --file F --expect ok\|reject` | logt in met de DSN uit F via een wegwerp-`postgres:17`-container | — |
| `scan --role R [--consumer F…] [PAD…]` | vindt achtergebleven kopieën en deelt ze in als `huidig`, `placeholder/regex`, `ANDERS` of `LEK` (het huidige secret buiten de `--consumer`-bestanden); doorzoekt ook de consumers zelf; exitcode 1 bij `ANDERS`/`LEK` buiten back-ups of bij een ontbrekend pad (`MIST`) | het wachtwoord dat als `huidig` moet gelden |

**Installeren of bijwerken op srv en max2.** Doe dit vanuit een checkout op de gewenste
commit; de mac gebruikt het script direct uit de checkout.

```bash
cd ~/Development/scrum4me-server
git rev-parse --short HEAD; shasum -a 256 scripts/rotate-env-credential
for h in scrum4me-srv max2; do
  scp scripts/rotate-env-credential "$h":/tmp/rec \
  && ssh "$h" 'sudo install -m 755 -o root -g root /tmp/rec /usr/local/sbin/rotate-env-credential && rm /tmp/rec && sha256sum /usr/local/sbin/rotate-env-credential'
done
```

De drie hashes moeten gelijk zijn. Noteer de commit in het evidence-bestand.

**Keychain op de mac.** Items heten `s4m-db-<rol>`, met account `new` of `old`.
`security add-generic-password … -w` leest van stdin, maar **vraagt de waarde twee keer**.
Eén regel maakt stilzwijgend géén item aan, terwijl de exitcode toch 0 is. Zie
[evidence/2026-09-25-keychain-argv-probe.md](evidence/2026-09-25-keychain-argv-probe.md).

```bash
# nieuw wachtwoord genereren, direct in de Keychain (geen variabele, geen argv)
openssl rand -hex 32 | awk '{print; print}' \
  | security add-generic-password -U -s s4m-db-<rol> -a new -w >/dev/null 2>&1
# controleren — verwacht: 64 hex-ok
security find-generic-password -s s4m-db-<rol> -a new -w \
  | awk '{print length($0), ($0 ~ /^[0-9a-f]{64}$/ ? "hex-ok" : "BAD")}'
```

### A.3 Fase 0: voorbereiden (verandert niets)

1. **Kies een rustig moment.**
   - `check_queue_empty` is leeg en er draait geen agent-job. Een recreate breekt lopende jobs
     af, en een MCP-herstart onderbreekt lopende sessies.
   - Meld in de actieve sessies op srv, max2 en de mac dat hun MCP straks herstart.
2. **Installeer het script** (A.2) en noteer de commit.
3. **Meet de inventaris opnieuw.** Vergelijk met de kaart (deel B).
   - Bestanden: `rewrite --dry-run` met de bestandslijst van de kaart. De aantallen per bestand
     moeten kloppen.
   - Sessies: de canary-query (A.6) zonder `T_alter`. Elke `application_name` en elk adres moet
     op de kaart staan. **Een onbekende consumer betekent stoppen**: zoek eerst zijn bestand.
   - Zoek ook breed naar nieuwe plekken (alleen namen):
     `sudo grep -rlE '<rol>:[^@]+@' /srv /etc /opt ~/.config ~/.claude.json ~/.codex 2>/dev/null`.
4. **Zet het oude wachtwoord in de Keychain als `old`.** Haal het op met een pipe uit één
   consumerbestand (het commando staat op de kaart) en controleer dat het hex is.
5. **Controleer de consistentie.** `scan` met `old` op stdin over alle consumerbestanden moet
   overal `huidig` geven. Een `ANDERS` hier betekent dat een consumer nu al een ander wachtwoord
   heeft. Uitzoeken vóór je verdergaat.
6. **Genereer het nieuwe wachtwoord** in de Keychain als `new` (A.2).
7. **Controleer compose**: `sudo -u ops-agent docker compose … config -q` slaagt op beide hosts,
   en het aantal replicas per service is bekend. Een `up --force-recreate` zet een met de hand
   geschaalde service terug naar het aantal in compose; geef het gemeten aantal mee als
   `--scale`. De commando's staan op de kaart.

### A.4 Fase 1: flip (achter elkaar, zonder pauze)

Sluit vóór stap 1 de Claude/Codex-sessies op srv en max2 en alle andere sessies op de mac,
behalve de sessie die de rotatie uitvoert. Claude Code schrijft `~/.claude.json` zelf bij, en
`rewrite` weigert een bestand dat tijdens het schrijven wijzigt. Gebeurt dat toch, dan zet
`rewrite` die hele host terug; herhaal dan alleen die host.

1. **Herschrijf de bestanden** op alle hosts met `rewrite` (`new` via een pipe). Noteer de
   `stamp=` per host. Dit heeft nog geen effect: draaiende processen houden hun env in het
   geheugen.
   **Stopregel:** ga pas naar stap 2 als elke host exitcode 0 gaf en een `ok`-regel per
   bestand. Faalde een host, dan heeft `rewrite` die host al teruggezet. Herhaal die host, of
   zet de geslaagde hosts terug met `rollback` en stop. `alter-role` met een half herschreven
   inventaris sluit consumers buiten.
2. **Voer `alter-role` uit** op srv en noteer `T_alter` uit de uitvoer. Vanaf nu falen nieuwe
   verbindingen met het oude wachtwoord.
3. **Herlaad direct alle consumers** (de commando's staan op de kaart). Bestaande
   DB-verbindingen blijven leven, want Postgres authenticeert alleen bij het verbinden.

### A.5 Fase 2: bewijzen

1. **Canary (A.6) met `T_alter`.** Elke consumer op de kaart heeft `nieuw ≥ 1`. Rijen met
   alleen `oud` zijn verbindingen van vóór de flip: kijk na ongeveer 30 minuten opnieuw en
   herlaad de consumer als ze dan nog bestaan.
   **Tel ook de mislukte logins** sinds `T_alter`:
   `docker logs --since <T_alter> scrum4me-postgres 2>&1 | grep -c "password authentication failed for user .<rol>"`.
   Een paar fouten tijdens het herladen is normaal. Blijven ze oplopen, dan draait er nog een
   consumer met het oude wachtwoord in het geheugen. Dat is vaak een host-MCP van een nog niet
   herstarte sessie: bestaande verbindingen blijven werken, maar de pool opent steeds nieuwe.
   Vind de bron met de verbindingsmetadata. Postgres stuurt de foutmelding leesbaar terug
   (`ssl=off`), dus
   `sudo tcpdump -nn -l -A -i any "tcp src port 5432" | grep -B5 "authentication failed"` toont
   het doeladres. Het wachtwoord komt in dit verkeer niet voor, want SCRAM verstuurt het niet.
2. **Healthchecks.** Die staan op de kaart.
3. **Negatieve proef.** `probe --expect reject` op de `.bak-<stamp>` van één bestand per host,
   en `probe --expect ok` op het huidige bestand. "Geweigerd" betekent een auth-weigering; een
   netwerkfout telt niet. `probe` draait op het **hostnetwerk**. Kies daarom een bestand
   waarvan de DSN-host vanaf de host bereikbaar is, dus een IP of `127.0.0.1` en geen
   compose-naam als `postgres`. De kaart noemt welk bestand. Draai dezelfde `probe --expect ok`
   al in fase 0, zodat een onbereikbare host niet pas na de flip opvalt.
4. **`prisma_migrate_precheck` is groen.**
5. **Residu.** `scan` met `new` op stdin, met de consumerbestanden als `--consumer`, plus `~/.claude/projects`,
   `~/.claude/file-history`, `~/.codex`, `~/.bash_history` en `~/.zsh_history` op elke host.
   Verwachting: exitcode 0. `ANDERS (backup)` is toegestaan tot fase 4. **`LEK` is rood:** dan
   staat het nieuwe wachtwoord in een transcript of history, en dan roteer je opnieuw. Een `ANDERS` in een
   transcript is het oude, nu dode wachtwoord: noteer het en ruim het op in fase 4.

### A.6 Canary-query

Draai de query op srv. Hij gaat via stdin, zodat er niets in argv komt:

```bash
cat <<'SQL' | ssh scrum4me-srv "docker exec -i scrum4me-postgres psql -U scrum4me -d scrum4me -X -v role=<rol> -v t_alter='<T_alter of 1970-01-01>'"
SELECT coalesce(nullif(application_name,''),'-') AS app, host(client_addr) AS addr,
       count(*) FILTER (WHERE backend_start >  :'t_alter'::timestamptz) AS nieuw,
       count(*) FILTER (WHERE backend_start <= :'t_alter'::timestamptz) AS oud
FROM pg_stat_activity WHERE usename = :'role' GROUP BY 1,2 ORDER BY 1,2;
SQL
```

Een container zonder `application_name` herken je aan zijn IP. Dat IP verandert bij een
recreate, dus haal de actuele koppeling op:

```bash
ssh <host> 'docker ps --format "{{.Names}}" | xargs docker inspect --format "{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"'
```

### A.7 Fase 3: rollback

Rol alleen terug als fase 2 rood is en niet binnen 15 minuten te herstellen. Loopt één
consumer achter, controleer dan eerst diens bestand en herlaad hem; dat is geen reden om terug
te rollen.

1. `rollback --stamp <S> --file …` op elke host, met dezelfde bestandslijst als bij `rewrite`.
2. `alter-role` met `old` via een pipe.
3. Herlaad alle consumers, zoals in fase 1 stap 3.
4. Controleer de canary met een nieuwe `T_alter`.

### A.8 Fase 4: afronden

1. **Back-ups weghalen.** Toon ze eerst: `ls <bestand>.bak-<S>` per host. Verwijder ze pas na
   JP's akkoord.
2. **Keychain opruimen:** `security delete-generic-password -s s4m-db-<rol> -a old`.
3. **Residu opruimen.** Transcripts en shell-snapshots met het oude wachtwoord kunnen blijven
   staan (het is dood), maar mogen ook weg. Toon het pad eerst en wis het pas na JP's akkoord.
4. **Werk de kaart bij**: de datum van de laatste rotatie, nieuwe of verdwenen consumers, en
   geleerde lessen.
5. **Schrijf een evidence-bestand** `docs/runbooks/evidence/<datum>-rotation-<rol>.md` met
   tijden, aantallen, stempels, de commit van het script en de uitkomst van elke stap in fase
   2. Nooit waarden.

---

## B. Kaarten

### B.1 `scrum4me_web_runtime`: volledig

**Wat de rol ontsluit:** de runtime-rol van de Scrum4Me-app op DB `scrum4me` (srv-Postgres
`scrum4me-postgres`, 192.168.0.154:5432). Web, workers, agent-containers, MCP-HTTP, Copilot en
de host-MCP's gebruiken hem. Het wachtwoord is hex64 en overal hetzelfde (gemeten 2026-09-25).

**Keychain:** `s4m-db-scrum4me_web_runtime/new` (mac) bevat het huidige wachtwoord.

**Laatste rotatie:** 2026-09-27 (T-86), `T_alter` 10:28:40Z. Het faalvenster duurde ~16 s,
en alle stappen van fase 2 waren groen. Het journal-lek van 2026-09-24 is daarmee dood.
Zie [evidence/2026-09-27-rotation-scrum4me_web_runtime.md](evidence/2026-09-27-rotation-scrum4me_web_runtime.md).

**Lessen uit die rotatie:**
- De host-MCP's (`s4m-mcp:<host>:claude`) blijven na de flip op hun oude verbinding. Hun pool
  gaf tot ~13 mislukte logins per minuut totdat de sessies herstart waren. Herstart de sessies
  daarom **direct** na stap 3 van fase 1, in hetzelfde venster.
- `scan` telt fixture-tekst zoals `…:OLD@` of `…:{OLD}@` in transcripts en in plannen als
  `ANDERS`. Een waarde die niet gelijk is aan het huidige wachtwoord kan na `alter-role` nooit
  meer inloggen, want een rol heeft precies één wachtwoord. Beoordeel `ANDERS` dus op herkomst,
  niet als lek; alleen `LEK` is rood.

#### Consumers

| # | Host | Bestand | Treffers | Herladen | Canary |
|---|---|---|---|---|---|
| 1 | srv | `/srv/scrum4me/compose/worker-idea.env` | 2 | compose-service `worker-idea` | `s4m-mcp:<container-id>` en `-` vanaf de IP's van `compose-worker-idea-*` |
| 2 | srv | `/srv/scrum4me/compose/worker-deploy.env` | 2 | `worker-deploy` | idem, `compose-worker-deploy-*` |
| 3 | srv | `/srv/scrum4me/compose/worker-docs.env` | 2 | `worker-docs` | idem, `compose-worker-docs-*` |
| 4 | srv | `/srv/scrum4me/compose/worker-codex.env` | 2 | `agent-codex` | idem, `scrum4me-agent-codex` |
| 5 | srv | `/srv/scrum4me/secrets/workers.env` | 3 | `scrum4me-workers` | `scrum4me-workers-push-listener`, `scrum4me-workers-queue-sse`, `-` |
| 6 | srv | `/srv/scrum4me/secrets/mcp-http.env` | 1 | `scrum4me-mcp-http` | `s4m-mcp:<container-id>` vanaf het IP van `scrum4me-mcp-http` |
| 7 | srv | `/srv/scrum4me/secrets/copilot.env` | 1 | `scrum4me-copilot` | vanaf het IP van `scrum4me-copilot` |
| 8 | srv | `/srv/scrum4me/repos/Scrum4Me/.env` | 2 | `sudo systemctl restart scrum4me-web` | `scrum4me-web`, `scrum4me-web-listen` vanaf `172.18.0.1` |
| 9 | srv | `/home/janpeter/.claude.json` | 1 | Claude-sessies op srv herstarten | `s4m-mcp:scrum4me-server:claude` |
| 10 | srv | `/home/janpeter/.codex/config.toml` | 1 | Codex-sessies op srv herstarten | `s4m-mcp:scrum4me-server:codex` (alleen als er een draait) |
| 11 | max2 | `/srv/scrum4me/compose/worker-idea.env` | 2 | compose-service `worker-idea` | vanaf `192.168.0.158` |
| 12 | max2 | `/srv/scrum4me/compose/worker-codex.env` | 2 | `agent-codex` | vanaf `192.168.0.158` |
| 13 | max2 | `/home/janpeter/.claude.json` | 2 | Claude-sessies op max2 herstarten | `s4m-mcp:max2:claude` |
| 14 | mac | `~/.claude.json` | 2 | Claude-sessies op de mac herstarten | `s4m-mcp:mac:claude` vanaf het tailnet-adres van de mac |
| 15 | mac | `~/.codex/config.toml` | 1 | Codex-sessies op de mac herstarten | `s4m-mcp:mac:codex` (alleen als er een draait) |

Totaal verwacht bij `--dry-run`: srv 17 treffers in 10 bestanden, max2 6 in 3, mac 3 in 2.

**Geen consumer** (gemeten 2026-09-25): `scrum4me-workers` op max2 (`secrets/workers.env` op
max2 gebruikt de rol `scrum4me`), `scrum4me-ops-dashboard` en de `scrum4me-postgres` op max2.

**Let op: ACL.** `Scrum4Me/.env` is `janpeter:janpeter`, met een ACL `user:ops-agent:rwx`.
`scrum4me-web` draait als `ops-agent` en leest het bestand via die ACL. De "670" in `ls` is
het ACL-masker; het bestand is niet world-readable (`other::---`). **Zet het niet op 600**:
dan wordt het masker `---` en kan de webapp het niet meer lezen. `rewrite` en `rollback`
behouden de ACL; dat is getest met `test_posix_acl_preserved`.

#### Bestandslijsten

```bash
SRV_FILES='--file /srv/scrum4me/compose/worker-idea.env --file /srv/scrum4me/compose/worker-deploy.env --file /srv/scrum4me/compose/worker-docs.env --file /srv/scrum4me/compose/worker-codex.env --file /srv/scrum4me/secrets/workers.env --file /srv/scrum4me/secrets/mcp-http.env --file /srv/scrum4me/secrets/copilot.env --file /srv/scrum4me/repos/Scrum4Me/.env --file /home/janpeter/.claude.json --file /home/janpeter/.codex/config.toml'
MAX2_FILES='--file /srv/scrum4me/compose/worker-idea.env --file /srv/scrum4me/compose/worker-codex.env --file /home/janpeter/.claude.json'
MAC_FILES=(--file ~/.claude.json --file ~/.codex/config.toml)   # zsh-array: zsh splitst een string niet
REC=~/Development/scrum4me-server/scripts/rotate-env-credential   # mac: uit de checkout
K='s4m-db-scrum4me_web_runtime'
```

`SRV_FILES` en `MAX2_FILES` bevatten alleen paden en gaan als één `ssh`-string naar de remote
bash, die ze wél splitst. `MAC_FILES` is een zsh-array; gebruik hem als `"${MAC_FILES[@]}"`.
`${SRV_FILES//--file/--consumer}` maakt er de `--consumer`-lijst voor `scan` van.
Getest op 2026-09-25: `rewrite --dry-run "${MAC_FILES[@]}"` geeft 2 + 1 treffers.

#### Fase 0

```bash
ssh scrum4me-srv "sudo rotate-env-credential rewrite --role scrum4me_web_runtime --dry-run $SRV_FILES"
ssh max2         "sudo rotate-env-credential rewrite --role scrum4me_web_runtime --dry-run $MAX2_FILES"
"$REC" rewrite --role scrum4me_web_runtime --dry-run "${MAC_FILES[@]}"

# oud wachtwoord → Keychain 'old' (alleen pipes); controle: 64 hex-ok
ssh scrum4me-srv 'sudo grep -m1 -oE "://scrum4me_web_runtime:[^@]+@" /srv/scrum4me/secrets/mcp-http.env' \
  | sed -E 's#^://[^:]+:##; s#@$##' | awk '{print; print}' \
  | security add-generic-password -U -s "$K" -a old -w >/dev/null 2>&1
security find-generic-password -s "$K" -a old -w | awk '{print length($0), ($0 ~ /^[0-9a-f]{64}$/ ? "hex-ok" : "BAD")}'

# consistentie: overal 'huidig' met old
security find-generic-password -s "$K" -a old -w | ssh scrum4me-srv "sudo rotate-env-credential scan --role scrum4me_web_runtime ${SRV_FILES//--file/--consumer}"
security find-generic-password -s "$K" -a old -w | ssh max2 "sudo rotate-env-credential scan --role scrum4me_web_runtime ${MAX2_FILES//--file/--consumer}"
security find-generic-password -s "$K" -a old -w | "$REC" scan --role scrum4me_web_runtime --consumer ~/.claude.json --consumer ~/.codex/config.toml

# probe vanaf het hostnetwerk: vóór de flip moet 'ok' al slagen
ssh scrum4me-srv 'sudo rotate-env-credential probe --role scrum4me_web_runtime --file /srv/scrum4me/repos/Scrum4Me/.env --expect ok'
ssh max2         'sudo rotate-env-credential probe --role scrum4me_web_runtime --file /srv/scrum4me/compose/worker-idea.env --expect ok'


# nieuw wachtwoord → Keychain 'new' (A.2), daarna controleren
openssl rand -hex 32 | awk '{print; print}' | security add-generic-password -U -s "$K" -a new -w >/dev/null 2>&1
security find-generic-password -s "$K" -a new -w | awk '{print length($0), ($0 ~ /^[0-9a-f]{64}$/ ? "hex-ok" : "BAD")}'

# replicas: srv heeft ze vast in compose (worker-idea 2, worker-deploy 2, worker-docs 1);
# max2 NIET — daar is worker-idea met de hand geschaald (2 op 2026-09-25). Een kale `up`
# zet hem terug naar 1. Meet N_max2 en geef hem in fase 1 mee als --scale.
ssh scrum4me-srv 'docker ps --format "{{.Names}}" | grep -E "worker-(idea|deploy|docs)" | sed -E "s/-[0-9]+$//" | sort | uniq -c'
ssh max2 'docker ps --format "{{.Names}}" | grep -c worker-idea'   # = N_max2

# compose leesbaar voor ops-agent
ssh scrum4me-srv 'cd /srv/scrum4me/compose && sudo -u ops-agent docker compose -p compose -f docker-compose.yml config -q && echo ok'
ssh max2 'cd /srv/scrum4me/compose && sudo -u ops-agent docker compose -p scrum4me -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.codex.yml config -q && echo ok'
```

#### Fase 1

```bash
security find-generic-password -s "$K" -a new -w | ssh scrum4me-srv "sudo rotate-env-credential rewrite --role scrum4me_web_runtime $SRV_FILES"
security find-generic-password -s "$K" -a new -w | ssh max2         "sudo rotate-env-credential rewrite --role scrum4me_web_runtime $MAX2_FILES"
security find-generic-password -s "$K" -a new -w | "$REC" rewrite --role scrum4me_web_runtime "${MAC_FILES[@]}"
#   → noteer stamp= per host. STOPREGEL: alle drie exit 0 met 'ok' per bestand, anders niet verder (A.4)

security find-generic-password -s "$K" -a new -w | ssh scrum4me-srv 'sudo rotate-env-credential alter-role --role scrum4me_web_runtime'
#   → noteer T_alter

ssh scrum4me-srv 'cd /srv/scrum4me/compose && sudo -u ops-agent docker compose -p compose -f docker-compose.yml up -d --force-recreate --no-deps worker-idea worker-deploy worker-docs agent-codex scrum4me-workers scrum4me-mcp-http scrum4me-copilot'
ssh scrum4me-srv 'sudo systemctl restart scrum4me-web'   # los: ook als compose faalt moet de web herstarten
ssh max2 'cd /srv/scrum4me/compose && sudo -u ops-agent docker compose -p scrum4me -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.codex.yml up -d --force-recreate --no-deps --scale worker-idea=<N_max2> worker-idea agent-codex'
# host-MCP's: sluit de lopende Claude/Codex-sessies op srv, max2 en de mac en start ze opnieuw
```

#### Fase 2: healthchecks

- **Web:** `ssh scrum4me-srv 'systemctl is-active scrum4me-web'` geeft `active`, en de publieke
  URL geeft HTTP 200.
- **Containers:** geen herstartlus. Controleer met
  `ssh <host> 'docker ps --format "{{.Names}} {{.Status}}" | grep -E "worker|agent-codex|workers|mcp-http|copilot"'`
  (status `Up`, waar een healthcheck bestaat `healthy`).
- **MCP:** een `health`-aanroep vanuit een nieuwe sessie op elke host.
- **Negatieve proef**, met `<S>` de stempel van die host:
  - `ssh scrum4me-srv 'sudo rotate-env-credential probe --role scrum4me_web_runtime --file /srv/scrum4me/repos/Scrum4Me/.env.bak-<S> --expect reject'`
  - `ssh scrum4me-srv 'sudo rotate-env-credential probe --role scrum4me_web_runtime --file /srv/scrum4me/repos/Scrum4Me/.env --expect ok'`
  - hetzelfde op max2 met `/srv/scrum4me/compose/worker-idea.env`.
  - **Niet** `compose/*.env` of `secrets/*.env` op srv: hun DSN-host is `postgres`, en die naam
    bestaat alleen binnen het compose-netwerk.
- **Residu:**

```bash
security find-generic-password -s "$K" -a new -w | ssh scrum4me-srv "sudo rotate-env-credential scan --role scrum4me_web_runtime ${SRV_FILES//--file/--consumer} /home/janpeter/.claude/projects /home/janpeter/.claude/file-history /home/janpeter/.codex /home/janpeter/.bash_history"
```

Doe hetzelfde op max2 en de mac, met hun eigen bestanden en home-mappen.

#### Rollback (A.7)

```bash
ssh scrum4me-srv "sudo rotate-env-credential rollback --stamp <S_srv> $SRV_FILES"
ssh max2         "sudo rotate-env-credential rollback --stamp <S_max2> $MAX2_FILES"
"$REC" rollback --stamp <S_mac> "${MAC_FILES[@]}"
security find-generic-password -s "$K" -a old -w | ssh scrum4me-srv 'sudo rotate-env-credential alter-role --role scrum4me_web_runtime'
# daarna dezelfde herlaadcommando's als in fase 1
```

#### Bekend residu

- **journal van srv, 2026-09-24:** het wachtwoord staat in de argv van een `sudo sed`-regel.
  Na de eerste rotatie is dat een dood wachtwoord. Het journal wordt niet gewist; deze regel
  documenteert het.
- **Transcripts** op de mac (scrum4me-mcp-subagents) bevatten een oudere, niet-hex waarde
  voor deze rol. Getest op 2026-09-27: die wordt geweigerd.
- De oude handmatige kopieën `secrets/workers.env.bak.20260926T080930Z` en
  `Scrum4Me/.env.bak.pre-docsaudit-20260707-234434` zijn op 2026-09-27 verwijderd. Handmatige
  kopieën volgen niet het `.bak-<stempel>`-patroon, dus `scan` telt ze als `ANDERS`. Zoek er
  in fase 0 naar.

---

### B.2 Skeletkaarten

Deze kaarten bevatten alleen wat bekend was bij IDEA-221 (gemeten 2026-09-25). **Meet ze
opnieuw bij de eerste rotatie** (fase 0) en werk ze dan uit tot het niveau van B.1.

#### `s4m_queue`

- **Ontsluit:** de queue-tabellen in DB `scrum4me`. Zie het oudere runbook
  `Ops-dashboard/docs/runbooks/s4m-queue-credential-rotation.md`. Dat runbook is voor
  inventaris en scope nog bruikbaar, maar de argv-stappen daarin (`psql -c "ALTER ROLE …"`,
  `PGPASSWORD=… psql`) zijn **verouderd**: gebruik A.4 en A.5.
- **Locaties:** `~/.zshenv` (mac), `~/.config/s4m-queue.env` (srv, max2),
  `~/restore-bootstrap/s4m-queue.env` (srv), `Scrum4Me/.env`.
- **Herladen:** CLI-aanroepen lezen de env per aanroep. Draaiende `s4m-queue watch`- en
  inbox-processen moet je opnieuw starten.

#### `scrum4me` (migrator/superuser) — measured during rotation ISS-38 (2026-09-27)

- **srv consumers (TCP, scram):**
  - `/etc/ops-agent/db-access/scrum4me-prisma.env` `MIGRATOR_DIRECT_URL` (prisma-operator.sh, policy-bundle-flow.sh, schema-lock.py);
  - `/root/.hub-watch-operator.env` `HUB_WATCH_HUB_DB_URL` + `HUB_WATCH_QUEUE_DB_URL`;
  - `/srv/scrum4me/secrets/ops-dashboard-migrate.env` `MIGRATE_DATABASE_URL` (host `postgres`, db `ops_dashboard`);
  - `/srv/scrum4me/compose/.env` `POSTGRES_PASSWORD` (initdb only; via `rewrite-key`).
- **max2:** no live consumer (no `scrum4me-postgres`; `compose/.env` and `secrets/ops-dashboard-migrate.env` are dead clones). Reachable over LAN `192.168.0.158` if Tailscale TCP/22 hangs.
- **mac:** no consumer. Ops-dashboard `SCRUM4ME_DATABASE_URL` runs as `ops_readonly`. Dev projects use a local Postgres (`~/Development/local-postgres`, `dev@127.0.0.1:5433`, `refresh.sh`); ISS-39.
- **Do not break:** backups, health collector and `alter-role` run via `docker exec` + local `trust`.
- **pg_hba (ISS-39, 2026-09-28):** `scrum4me` only via the local socket and from `172.18.0.1/32` (host tools via the published port; `migrate.sh` rewrites `postgres` → `127.0.0.1`), `reject` from everywhere else, above the catch-all. So a canary from a container on `compose_default` (source 172.18.0.x) gets `pg_hba.conf rejects connection`: test via `--network host` + `127.0.0.1`. A leaked superuser password is worthless outside srv.
- **`rewrite-key POSTGRES_PASSWORD` = a recreate on the next `compose up`.** Compose sees env drift on `postgres` and recreates the container (ISS-38: an unrelated flow did this 45 min after the flip, with ~3 s of DB outage). Do the recreate yourself in fase 1, in a quiet window: `docker compose -f /srv/scrum4me/compose/docker-compose.yml up -d --no-deps postgres`, compare `docker ps` IDs before/after (only `scrum4me-postgres` may change), wait for `pg_isready`, then prove it (done this way in ISS-41, 2026-09-28: ready in ~3 s). Long-running LISTEN clients (e.g. `s4m-queue watch`) drop and must re-arm.
- **MCP flows copy `compose/.env`** (incl. `POSTGRES_PASSWORD` and `DOCS_AUDIT_*_TOKEN`) to `/home/ops-agent/mcp-env-backups/` on every run. After a rotation, scan there too; older copies hold dead values.
- **Old password ≠ 64-hex:** `read_secret` (scan/rewrite/alter-role) accepts only `SECRET_RE` (64 hex). For a legacy password, use your own in-process scan; the old password goes only to `rewrite-key` (`TOKEN_RE`). New password: `openssl rand -hex 32`.
- **Canaries (read-only):**
  - command_key `prisma_migrate_status` via `/agent/v1/exec`;
  - per DSN: `begin read only; select current_user` (migrate env via `--network compose_default`, the rest via `--network host`);
  - reject: old password via TCP → `password authentication failed`;
  - then postgres log since `T_alter`: no unexpected `password authentication failed`.
- **Residue:** redact in place with a same-length placeholder (keeps tar, sqlite and jsonl valid). Also check Docker volumes (`worker-docs` transcripts under `.claude/projects`), `~/.codex/logs_2.sqlite`, VS Code `User/History`, Beekeeper logs, and the journal (`_CMDLINE`, see ISS-41).

#### `ops_dashboard_mac`

- **Locaties:** mac-production-secrets. Na T-76 ook ops-dashboard op srv en max2 (hergebruik,
  JP-besluit 2026-09-25).

#### `ops_readonly`, `scrum4me_app`

- `scrum4me_app`: het wachtwoord staat niet op srv. Locaties nog onbekend.
- `ops_readonly`: locaties nog onbekend.

#### `scrum4me_dispatch`, `s4m_dispatch_projector`

- Beide NOLOGIN tot de uitrol van IDEA-213. Er is dan nog niets te roteren. Maak de kaart bij
  die uitrol.

#### Tokens

Tokens staan in deel C. Dispatch-sleutels (IDEA-213) krijgen een kaart bij hun uitrol.

---

## C. Tokens

Metingen en proeven: [evidence/2026-09-27-token-probes.md](evidence/2026-09-27-token-probes.md).

### C.1 Wat anders is dan bij een wachtwoord

- **Oud en nieuw zijn tegelijk geldig.** Maak eerst de nieuwe token aan, zet alle consumers
  om, bewijs dat ze werken, en trek pas daarna de oude in. Er is dus geen faalvenster en geen
  haast.
- **Dezelfde sleutel kan op verschillende plekken een andere token bevatten.** Op 2026-09-27
  waren er bijvoorbeeld 7 verschillende `FORGEJO_TOKEN`-waarden. Roteer daarom **per token**,
  niet per sleutelnaam. `rewrite-key` vervangt alleen de plekken waar de waarde gelijk is aan de
  oude token.
- **Zoek elke token op bij zijn uitgever.** Forgejo: `access_token`, via `token_last_eight`.
  Scrum4Me: `api_tokens`, via `sha256(token)`. Zo weet je welke rij je intrekt. Doe de
  vergelijking in-process en print nooit tekens, hashes of prefixen van een token.

### C.2 Gereedschap

| Subcommando | Wat het doet | stdin |
|---|---|---|
| `rewrite-key --key K --file F… [--dry-run]` | vervangt de waarde van `K` in env- (`K=`, `export K=`, quotes), JSON- (`"K": "…"`) en TOML-bestanden (`K = "…"`), **alleen waar die gelijk is aan de oude token**; exact op de sleutelnaam | regel 1 oud, regel 2 nieuw (bij `--dry-run` alleen oud) |
| `rewrite-key --whole-file --file F…` | idem, voor een bestand dat alleen de token bevat (bijv. `forgejo-tag.token`) | idem |
| `classes --key K PAD…` / `classes --whole-file PAD…` | groepeert de waarden als `waarde-A/B/…` met een willekeurige salt per run; **labels gelden alleen binnen één run** | — |
| `rollback`, `scan` | zoals in deel A | |

`rewrite-key` heeft dezelfde garanties als `rewrite`: back-up, behoud van mode, eigenaar en ACL,
en terugzetten van de hele batch bij elke fout of onderbreking.

**Keychain op de mac:** `s4m-tok-<naam>`, met account `new` of `old`. Twee regels via stdin maak je
zonder variabele:

```bash
{ security find-generic-password -s s4m-tok-<naam> -a old -w; security find-generic-password -s s4m-tok-<naam> -a new -w; } \
  | ssh <host> 'sudo rotate-env-credential rewrite-key --key <K> --file …'
```

**Een token uit een consumerbestand naar de Keychain halen** (alleen pipes):

```bash
ssh <host> 'sudo grep -m1 -oE "^(export +)?<K>=[\"'"'"']?[^\"'"'"' ]+" <bestand>' | sed -E 's/^(export +)?<K>=["'"'"']?//' \
  | awk '{print; print}' | security add-generic-password -U -s s4m-tok-<naam> -a old -w >/dev/null 2>&1
```

**Een token uit de UI van een uitgever** (Scrum4Me, Anthropic-console): kopieer hem en zet hem
direct in de Keychain. Wis daarna het klembord.

```bash
pbpaste | awk '{print; print}' | security add-generic-password -U -s s4m-tok-<naam> -a new -w >/dev/null 2>&1; pbcopy </dev/null
```

### C.3 Procedure

**Fase 0: inventaris (verandert niets).**
1. Zoek de token bij zijn uitgever op (C.4 en verder) en noteer id, naam, scope en eigenaar.
2. Zoek alle consumers. Zoek breed op de sleutelnaam, ook in build-kopieën zoals
   `.next/standalone/.env`, in `auth.json`/`.claude.json`/`config.toml` en in systemd-env-
   bestanden. Draai daarna per host `classes` om te zien welke plekken **deze** token hebben.
   Een label geldt alleen binnen één run. Vergelijk over hosts heen via de uitgever
   (`token_last_eight` of `sha256`), in-process.
3. Zet de oude token in de Keychain (`old`). `rewrite-key --dry-run` per host met `old` moet
   exact de consumers van de kaart geven.
4. Kies een moment waarop de consumer niets doet: geen lopende job op die container.

**Fase 1: nieuwe token.** Maak hem aan bij de uitgever, met **dezelfde scope** en een naam met de
datum (bijv. `CODEX_FORGEJO-2026-09-27`). Zet hem direct in de Keychain (`new`) en controleer
met een API-aanroep dat hij werkt en bij het juiste account hoort.

**Fase 2: omzetten.** `rewrite-key` per host met oud en nieuw via stdin, noteer `stamp=`, en
herlaad de consumers (kaart). Nieuwe processen lezen de nieuwe token; de oude token werkt nog,
dus er valt niets om.

**Fase 3: bewijzen.**
- De consumer draait met de nieuwe token. Controleer dat zonder de waarde te zien:
  ```bash
  { security find-generic-password -s s4m-tok-<naam> -a new -w; } | ssh <host> 'P=$(docker inspect -f "{{.State.Pid}}" <container>); T=$(sudo mktemp); sudo sh -c "tr \"\\0\" \"\\n\" < /proc/$P/environ > $T"; sudo rotate-env-credential rewrite-key --key <K> --dry-run --file $T; sudo rm -f $T'
  ```
  Dit geeft `treffers=1`. Bij de oude token weigert hetzelfde commando met "0 treffers".
- De functie werkt: de canary op de kaart, en geen auth-fouten in de log van de consumer.
- De uitgever meldt dat de nieuwe token gebruikt is: Forgejo `updated_unix`, of het laatste
  gebruik in de UI.

**Fase 4: oude token intrekken en opruimen.**
1. Trek de oude token in bij de uitgever (kaart).
2. Bewijs dat hij geweigerd wordt: een API-aanroep met `old` geeft 401.
3. Met JP's akkoord: verwijder de back-ups `.bak-<stamp>` en het Keychain-item `old`. Het item
   `new` blijft als het huidige.
4. Werk de kaart bij en schrijf een evidence-bestand.

**Rollback:** tot fase 4 is de oude token nog geldig. `rollback --stamp S` plus herladen zet
alles terug zonder dat er iets uitvalt.

---

### C.4 Kaart: Forgejo-PAT's

**Uitgever:** Forgejo 15 op srv (container `scrum4me-forgejo`, DB `forgejo` in `scrum4me-postgres`).

**Aanmaken:** bewezen op 2026-09-27. Dit werkt voor elk account, ook een bot; de waarde komt
alleen op stdout.

```bash
ssh scrum4me-srv 'sudo docker exec -u git scrum4me-forgejo forgejo admin user generate-access-token -u <account> -t <naam-met-datum> --scopes <scopes> --raw' \
  | awk '{print; print}' | security add-generic-password -U -s s4m-tok-<naam> -a new -w >/dev/null 2>&1
```

**Controleren of de token werkt** (geeft status en login):

```bash
security find-generic-password -s s4m-tok-<naam> -a <new|old> -w | python3 -c 'import sys,json,urllib.request as u,urllib.error as e
t=sys.stdin.readline().strip()
try: r=u.urlopen(u.Request("https://git.jp-visser.nl/api/v1/user",headers={"Authorization":"token "+t}),timeout=10); print(r.status, json.load(r)["login"])
except e.HTTPError as x: print(x.code)'
```

Een 403 betekent dat de token geldig is maar geen `read:user`-scope heeft. Een 401 betekent
ongeldig of ingetrokken.

**Intrekken:** bewezen op 2026-09-27; direct 401, zonder vertraging door de cache.
- De API (`DELETE /users/{u}/tokens/{id}`) vraagt basic-auth, dus het wachtwoord van dat
  account. Dat is geen optie voor bots.
- Trek daarom in via de DB, op **id**. Controleer vooraf dat id en naam kloppen:

```bash
echo "DELETE FROM access_token WHERE id = <id> AND name = '<naam>' RETURNING id, name;" \
  | ssh scrum4me-srv 'docker exec -i scrum4me-postgres psql -U scrum4me -d forgejo -tA -v ON_ERROR_STOP=1'
```

Voor eigen tokens van janpeter kan het ook in de UI: Instellingen → Toepassingen.

**Tokens en consumers** (gemeten op 2026-09-27):

| Forgejo-id, account, naam | Scope | Consumers | Herladen |
|---|---|---|---|
| 36 s4m-codex-reviewer `CODEX_FORGEJO-2026-09-27` (voorheen 11 `CODEX_FORGEJO`) | write: activitypub, misc, notification, organization, package, issue, repository, user | srv + max2 `compose/worker-codex.env` | recreate `agent-codex` (srv `-p compose`; max2 `-p scrum4me` met de codex-override) |
| 6 janpeter `FORGEJO_TOKEN_SERVER` | write:repository | srv + max2 `compose/worker-idea.env` | recreate `worker-idea` (max2 met `--scale`, zie B.1) |
| 13 janpeter `worker-deploy-proread` | read:repository | srv `compose/worker-deploy.env` | recreate `worker-deploy` |
| 7 janpeter `janpeter-shell` | write: admin, repository, user | srv `secrets/workers.env` (max2: vervallen op 2026-09-27 15:33) | recreate `scrum4me-workers` |
| 21 janpeter `ISSUE_TOKEN2` | all | srv `repos/Scrum4Me/.env` | `systemctl restart scrum4me-web` |
| 2 janpeter `Sync-forgejo-github` | write:organization, write:repository, read:user | srv `/etc/forgejo-mirror/forgejo.env`; gebruikt door `forgejo-mirror-sync.sh` voor de API (curl-config via stdin) en door de tags-fallback (`GIT_ASKPASS`, alleen in de omgeving van het git-proces). Niet opgeslagen in de bare clones onder `/srv/scrum4me/repos/mirrors/` (map leeg op 2026-09-30; oudere clones krijgen bij de volgende fallback `remote set-url` zonder userinfo) | geen: `forgejo-mirror-sync.service` leest per run |
| 29 mcp-release `ops-agent-deploy-tag` | write:repository | srv `/etc/ops-agent/forgejo-tag.token` (`--whole-file`) | geen: gelezen per deploy |
| 39 janpeter `trust-scan-max2-2026-10` (vervangt 26 `FREX_RUNNER`, ingetrokken 2026-09-30) | read: admin, repository | max2 `/opt/forgejo-runner/credentials/trust-scan.env` | geen: `forgejo-runner-trust.service` leest per run; na vervangen één handmatige `systemctl start forgejo-runner-trust.service` |
| 24 janpeter `s4m-queue-2026-08-29` | write: activitypub, admin, misc, notification, organization, package, issue, repository; read:user | mac `~/.zshenv` | nieuwe shell of sessie |

**Overige PAT's en hun consumers** (gemeten 2026-09-27: in-process gezocht op `token_last_eight`
in `/srv`, `/etc`, `/opt`, `/home` van srv en max2 en in `~/Development`/`~/.config` op de mac,
plus de namen van de Forgejo Actions-secrets):

| id, account, naam | Consumer |
|---|---|
| 1 janpeter `SCRUM4ME_FORGEJO` | tweede sleutel in `compose/worker-idea.env` (srv + max2) en `compose/worker-codex.env` (max2); `~/.forgejo-pat.tmp` (srv) |
| 8 janpeter `mac-Forgejo` (all) | mac `~/Development/MotherlessScrapper/.env` |
| 10 janpeter `ops-agent-ro` | srv `/home/ops-agent/.git-credentials` |
| 12 janpeter `scrum4me-copilot-token` | vermoedelijk Actions-secret `digiplein/SUBMODULE_TOKEN` (zelfde aanmaakdatum) |
| 37 janpeter `DOCS_AUDIT_READ-2026-09-27` (read:repository; voorheen 14 `DOCS_AUDIT_READ_TOKEN`) | srv `compose/.env` → `worker-docs` (child krijgt hem als `FORGEJO_TOKEN`). max2: sleutel verwijderd op 2026-09-27 (compose gebruikte hem niet) |
| 15 janpeter `DOCS_AUDIT_PUSH_TOKEN` | srv `compose/.env` (runner pusht; de agent krijgt hem niet) |
| 19 janpeter `MEDIA-ORG` | vermoedelijk Actions-secret `media-organizer/SUBMODULE_TOKEN` |
| 22/23 janpeter `idea187-scrum4me-mcp-package-write/read` | Actions-secrets `scrum4me-mcp/PACKAGE_WRITE_TOKEN` / `PACKAGE_READ_TOKEN` |
| 27 janpeter `PACKAGE_WRITE_TOKEN` | Actions-secret `ops-dashboard/PACKAGE_WRITE_TOKEN` |
| 30 janpeter `max2-ops-agent-2026-09` | max2 `/etc/ops-agent/git-credentials` |
| 31 janpeter `jp-cli-2026-09` | `~/.forgejo-pat` (srv + max2) |

**Ingetrokken op 2026-09-27** (JP-akkoord; via DB-delete, met als voorwaarde "niet gebruikt sinds
de meting"):

- 17 `SCRUM4ME_MAX2` (all, laatst gebruikt 07-23)
- 18 `PACKEGES` (07-31)
- 20 `ISSUE_TOKEN` (08-17)
- 16 `m23b-smoke` (s4us-smoke-bot, 08-18)
- 25 `JP_FORGEJO` (all, 09-09; stond in `~/.bash_history` op max2, en die waarde geeft nu 401)
- 28 `TEMP_OPS` (09-20)

Daarna staan er 21 PAT's.

**Residu met werkende tokens:** oude handmatige kopieën (`compose/worker-*.env.bak.*`,
`compose/.env.bak*`, `/home/ops-agent/mcp-env-backups/`, `~/.forgejo-pat.tmp`) en de
docs-worker-logs. Ruim ze op na JP's akkoord, en roteer de tokens die in de logs staan.

**Docs-worker-lek (ISS-37), afgehandeld op 2026-09-27:** de agent draaide soms een env-dump,
en `run-one-job` schreef die ongefilterd naar de run-log; de worker-log-ingest kopieerde hem
naar `ops_dashboard."WorkerEvent"`. Sinds scrum4me-docker PR #88 (`dd889a6`) maskeert
`run-one-job` de waarden van secret-achtige variabelen in de run-log (`lib/log-redact.ts`).
Token 14 is geroteerd naar 37 (alleen `read:repository`) en ingetrokken (401). Geredigeerd:
21 run-logs (ook `.log.gz`), 25 `WorkerEvent`-rijen, twee `compose/.env`-backups. **Niet**
geredigeerd (de waarde is ingetrokken): de nachtelijke `pg_dumpall`-dumps en restic-snapshots
(retentie), `/root/t1775-backup-*/pg_dumpall.sql.gz`, zes kopieën in
`/home/ops-agent/mcp-env-backups/` en 27 agent-transcripts in het home-volume van
`worker-docs` (`~/.claude/projects/`). Let op: de masking dekt alleen de run-log, niet die
transcripts.

**Laatste rotatie:** `worker-codex`, 2026-09-27 (T-107): id 11 → 36, zonder faalvenster. Zie
[evidence/2026-09-27-rotation-forgejo-pat-worker-codex.md](evidence/2026-09-27-rotation-forgejo-pat-worker-codex.md).
Keychain: `s4m-tok-forgejo-codex/new`.

**Een PAT uit een consumerbestand naar de Keychain halen:** gebruik het vaste patroon (40 hex).
De generieke regex uit C.2 is lastig te quoten binnen `zsh -c` en `ssh`.

```bash
ssh <host> 'sudo grep -m1 -oE "^FORGEJO_TOKEN=[0-9a-f]{40}$" <bestand>' | cut -d= -f2 \
  | awk '{print; print}' | security add-generic-password -U -s s4m-tok-<naam> -a old -w >/dev/null 2>&1
```

### C.5 Kaart: Scrum4Me API-tokens

**Uitgever:** scrum4me-workers-UI `/api-tokens` (alleen admin), tabel `api_tokens`.
- De token wordt één keer getoond.
- Soorten: `IMPLEMENTATION`, `PLANNING`, `WORKERS_UI`, `COPILOT` (verplicht met product-scope).
- Een vervaldatum is optioneel.
- Per gebruiker mogen **maximaal 10 tokens actief** zijn. Trek oude tokens tijdig in, zodat er
  ruimte blijft voor de overlap.

**Aanmaken:** in de UI, met dezelfde soort en scope en een label met de datum. Zet hem daarna
met `pbpaste` in de Keychain (C.2).

**Controleren en koppelen** via de hash, zonder de waarde te tonen:

```bash
security find-generic-password -s s4m-tok-<naam> -a <new|old> -w \
  | python3 -c 'import sys,hashlib;print("SELECT id,label,kind,coalesce(revoked_at::text,$$actief$$) FROM api_tokens WHERE token_hash=$$"+hashlib.sha256(sys.stdin.readline().strip().encode()).hexdigest()+"$$;")' \
  | ssh scrum4me-srv 'docker exec -i scrum4me-postgres psql -U scrum4me -d scrum4me -tA'
```

**Intrekken:** met de knop in de UI (`revoked_at`). Bewijs: bovenstaande query geeft een datum
in plaats van `actief`, en een MCP-aanroep met de oude token wordt geweigerd.

| Token (label, soort) | Consumers | Herladen |
|---|---|---|
| "Srum4Me server" (IMPLEMENTATION) | srv + max2 `compose/worker-idea.env` en `compose/worker-codex.env`; max2 `~/.claude.json` | recreate `worker-idea` en `agent-codex`; Claude-sessie op max2 herstarten |
| "worker-deploy" (IMPLEMENTATION) | srv `compose/worker-docs.env`, `compose/worker-deploy.env` | recreate `worker-docs` en `worker-deploy`. **Mee-roteren:** op 2026-09-27 zijn 6 tekens ervan in een transcript gekomen. |
| "scrum4me-server" (IMPLEMENTATION) | srv `~/.claude.json`, `~/.codex/config.toml` | sessies op srv herstarten |
| "S4M_MCP_MAC" (IMPLEMENTATION) | mac `~/.zshenv`, `~/.claude.json`, `~/.codex/config.toml` | nieuwe shell en sessies |
| **geen `api_tokens`-rij** | srv `repos/Scrum4Me/.env`; srv + max2 `ops-dashboard/.env`; srv `ops-dashboard/.next/standalone/.env` | eerst uitzoeken waarvoor deze `SCRUM4ME_TOKEN` dient. Hij authenticeert niet als API-token. |

Actief zonder gevonden consumer: "voor mcp-tester", "Janpeter", "agent-harness-local-llm-max2",
en de COPILOT-tokens voor digiplein en mediaorganizer (consumers buiten deze inventaris).

### C.6 Kaart: Claude

**`CLAUDE_CODE_OAUTH_TOKEN`** (een abonnementstoken; mag alleen model-aanroepen doen)
- Er zijn 2 waarden: srv `compose/worker-docs.env`, `worker-idea.env` en `worker-deploy.env`
  hebben er één, max2 `compose/worker-idea.env` heeft een andere.
- **Aanmaken:** `claude setup-token` op de mac. Die opent de browser en toont de token in de
  terminal. Kopieer hem, zet hem met `pbpaste` in de Keychain, en wis daarna het klembord en de
  terminal-scrollback.
- **Omzetten:** `rewrite-key --key CLAUDE_CODE_OAUTH_TOKEN` en de workers recreaten.
- **Intrekken: niet bewezen.** Volgens de docs maak je een nieuwe en herstart je, maar hoe je
  de oude intrekt staat er niet. JP controleert dat in de instellingen van claude.ai en vult
  het hier aan. Tot dan blijft de oude geldig tot hij verloopt.

**`ANTHROPIC_API_KEY`**
- Eén waarde, in srv `secrets/copilot.env`, srv + max2 `ops-dashboard/.env`, en srv
  `ops-dashboard/.next/standalone/.env` (een build-kopie).
- In sommige worker-env's staat de sleutel leeg. Een gevulde `ANTHROPIC_API_KEY` wint in
  `claude -p` altijd van de OAuth-token.
- **Aanmaken en intrekken:** Anthropic Console → API Keys (maken; oude uitschakelen of
  verwijderen, direct effectief).
- **Herladen:** recreate `scrum4me-copilot` en `scrum4me-ops-dashboard`.

**Interactieve login**
- srv/max2: `~/.claude/.credentials.json` (access- en refresh-token, vernieuwt zichzelf).
- mac: Keychain "Claude Code-credentials".
- **Vervangen:** `/logout` en daarna `/login` in een Claude-sessie op die host.
- **Alles intrekken:** sessies beëindigen in claude.ai.

### C.7 Kaart: ChatGPT / Codex

- **Eén ChatGPT-account, vijf eigen sessies:** srv `~/.codex/auth.json`, srv
  `/srv/scrum4me/worker-codex-home/auth.json`, max2 idem (beide), mac `~/.codex/auth.json`.
  Alle vijf hebben `auth_mode=chatgpt` en een eigen refresh-token.
- **Opnieuw inloggen per plek:**
  ```bash
  CODEX_HOME=/srv/scrum4me/worker-codex-home codex login --device-auth
  ```
  JP opent de getoonde URL en code in de browser. Voor `~/.codex` laat je `CODEX_HOME` weg.
  Controleer met `codex login status`. Herstart daarna `agent-codex` of de Codex-sessie.
- **Intrekken:** `codex logout` per plek verwijdert de lokale sessie. Alle sessies tegelijk
  intrekken gaat via het ChatGPT-account ("overal uitloggen"); daarna moeten alle vijf plekken
  opnieuw inloggen.
- `--with-api-key` en `--with-access-token` lezen van stdin, voor als er ooit een API-sleutel komt.
