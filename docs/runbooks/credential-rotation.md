---
last_updated: "2026-09-25"
idea: IDEA-221
---

# Credentials roteren — runbook

Hoe je een DB-wachtwoord of token vervangt op alle plekken waar het staat, zonder dat het
ergens lekt en met hooguit een korte onderbreking. Deel A is de procedure en die geldt voor
elke credential. Deel B bevat de **kaarten**: per credential waar hij staat, wie hem gebruikt
en hoe je elke consumer herlaadt.

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
- **`/srv/scrum4me/secrets/workers.env.bak.20260926T080930Z`:** handmatige kopie van
  2026-09-26 met het wachtwoord van vóór T-86, nu dood. Niet het `.bak-<stempel>`-patroon.
- **Transcripts** op de mac (scrum4me-mcp-subagents) bevatten een oudere, niet-hex waarde
  voor deze rol. Getest op 2026-09-27: die wordt geweigerd.
- **`/srv/scrum4me/repos/Scrum4Me/.env.bak.pre-docsaudit-20260707-234434`:** een oude
  handmatige back-up met dezelfde ACL. `scan` noemt hem niet als back-up, omdat hij niet het
  `.bak-<stempel>`-patroon volgt. Beoordeel hem in fase 0 en verwijder hem na JP's akkoord.

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

#### `scrum4me` (migrator/superuser)

- **Locaties:** `/etc/ops-agent/db-access/scrum4me-prisma.env`. Daarnaast de resterende
  consumers tot ISS-1 dicht is, waaronder **`/srv/scrum4me/secrets/workers.env` op max2**
  (3 treffers, gemeten 2026-09-25).
- **Let op:** deze rol wordt gebruikt voor `alter-role` (`--db-user scrum4me`), via de
  `trust`-regel binnen de container. Het roteren van `scrum4me` raakt dat pad niet.

#### `ops_dashboard_mac`

- **Locaties:** mac-production-secrets. Na T-76 ook ops-dashboard op srv en max2 (hergebruik,
  JP-besluit 2026-09-25).

#### `ops_readonly`, `scrum4me_app`

- `scrum4me_app`: het wachtwoord staat niet op srv. Locaties nog onbekend.
- `ops_readonly`: locaties nog onbekend.

#### `scrum4me_dispatch`, `s4m_dispatch_projector`

- Beide NOLOGIN tot de uitrol van IDEA-213. Er is dan nog niets te roteren. Maak de kaart bij
  die uitrol.

#### Tokens: `SCRUM4ME_TOKEN`, `FORGEJO_TOKEN`, `forgejo-tag.token`, dispatch-sleutels

- Dit zijn geen DB-rollen. `alter-role` en `probe` zijn niet van toepassing, en `rewrite`
  alleen als het token in een `://user:<token>@`-URL staat. Leg bij de eerste rotatie vast
  hoe je het token bij de uitgever intrekt en opnieuw uitgeeft: Scrum4Me-UI, Forgejo-UI of
  API. Verwijzingen: `FORGEJO_TOKEN` in `~/.zshenv` (mac), `forgejo-tag.token` (ISS-28),
  dispatch-sleutels (IDEA-213).
