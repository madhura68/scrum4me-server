# Credential-rotatie (IDEA-221) — implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scrum4me_web_runtime` roteren zonder lek of noemenswaardige downtime, met een herbruikbaar runbook en het hulpscript `rotate-env-credential`.

**Architecture:** Eén python3-stdlib-script met vijf subcommando's (`rewrite`, `rollback`, `alter-role`, `probe`, `scan`) dat secrets alleen via stdin ontvangt. De mac regisseert: het wachtwoord komt uit de Keychain en gaat via een pipe over SSH naar de hosts. Het runbook legt de procedure vast (fasen 0–4) plus een kaart per credential.

**Tech Stack:** Python 3 (stdlib: `hashlib`, `hmac`, `base64`, `argparse`, `re`, `os`, `subprocess`, `tempfile`, `unittest`), Docker (`postgres:17`), macOS `security`, SSH.

**Spec:** `docs/superpowers/specs/2026-09-25-credential-rotation-design.md` (ook als product-doc aan IDEA-221 gekoppeld, revisie 1).

**Werkboom:** `~/Development/.worktrees/idea-221-credential-rotation`, branch `docs/idea-221-credential-rotation`.

## Global Constraints

- Een secret komt alleen binnen via stdin; nooit via argv, een env-var in argv, journal, log, issue, transcript of queue.
- Uitvoer van het script bevat nooit een secret of een hash-prefix ervan.
- Een nieuw wachtwoord moet `^[0-9a-f]{64}$` zijn.
- Het script gebruikt alleen de python-stdlib. Het draait op Ubuntu (srv, max2) en macOS.
- Geen secrets in Git, ook niet in fixtures: tests gebruiken vaste neppe hex-waarden.
- Productie: geen herstart van de host-Dockerdaemon, geen `docker system prune`. De echte rotatie (taak 6) gebeurt alleen op een rustig moment met een lege queue en met JP's GO op dat moment.

## Review Focus

1. **Een bestand met meerdere rollen in één DSN-regel of in één bestand** (bijv. `DATABASE_URL` en `MIGRATE_URL` met verschillende rollen): alleen `R` wijzigt. Test in taak 2.
2. **Een wachtwoord dat al URL-encoded tekens bevat (`%40`) of een rolnaam als prefix van een andere rol (`scrum4me` versus `scrum4me_web_runtime`)**: de match is exact op `://R:`. Test in taak 2.
3. **Een fout halverwege een batch** (bijvoorbeeld het derde bestand is read-only): de al herschreven bestanden worden automatisch teruggezet en de uitvoer noemt de stempel. Test in taak 2.
4. **Stdin met een CRLF, een lege regel of twee regels**: CRLF en één afsluitende newline worden geaccepteerd; al het andere wordt geweigerd, zonder de invoer te echoën. Test in taak 2.
5. **`probe` op een DSN met query-string (`?schema=public&connection_limit=5`) of zonder poort**: de query wordt genegeerd en de poort valt terug op 5432. Test in taak 3.

---

### Task 1: Praktijkproef — Keychain vullen zonder argv

**Doel:** vaststellen welke methode een Keychain-item vult zonder dat de waarde in de argv van enig proces staat. Het runbook (taak 5) neemt de bewezen methode over. Dit is een proef, geen code die blijft.

**Files:**
- Create: `docs/runbooks/evidence/2026-09-25-keychain-argv-probe.md` (alleen methode en uitkomst, geen waarden)

- [ ] **Step 1: Proef A, interactieve prompt.** Maak het testitem `s4m-db-probe/new` met een neppe waarde:

```bash
security add-generic-password -s s4m-db-probe -a new -w
```

Plak de waarde bij de prompt. Kijk in een tweede terminal tijdens de prompt met `ps -axww -o pid,command | grep '[s]ecurity add'` of de waarde zichtbaar is. Verwachting: de argv eindigt op `-w` zonder waarde.

- [ ] **Step 2: Proef B, stdin in plaats van een tty.**

```bash
openssl rand -hex 32 | security add-generic-password -U -s s4m-db-probe -a new2 -w
```

Controleer of het item de gegenereerde waarde bevat (vergelijk lengte en `security find-generic-password -s s4m-db-probe -a new2 -w | wc -c` = 65) of dat `security` weigert of hangt. Controleer daarnaast op dezelfde manier met `ps` of de waarde niet in argv verschijnt.

- [ ] **Step 3: Kies de methode.**
  - Werkt B, dan is dat de runbook-methode (genereren in een pipe, zonder klembord).
  - Werkt alleen A, dan wordt het runbook: `openssl rand -hex 32 | pbcopy`, daarna plakken bij de prompt, daarna `pbcopy </dev/null` om het klembord te wissen.

- [ ] **Step 4: Opruimen en vastleggen.** Verwijder beide testitems:

```bash
security delete-generic-password -s s4m-db-probe -a new
security delete-generic-password -s s4m-db-probe -a new2
```

Schrijf het evidence-bestand: de methode, de uitkomst van `ps` en de macOS-versie.

- [ ] **Step 5: Commit.** `git commit -m "docs(idea-221): keychain-argv-proef"`

**Acceptatie:** er is een bewezen methode waarbij `ps` de waarde niet toont. Is er geen, dan stop je en leg je het aan JP voor.

---

### Task 2: `rotate-env-credential` — kern, `rewrite` en `rollback`

**Files:**
- Create: `scripts/rotate-env-credential` (uitvoerbaar, `#!/usr/bin/env python3`)
- Create: `scripts/tests/test_rewrite.py`
- Create: `scripts/tests/_load.py` (laadt het script als module)

**Interfaces:**
- Produces (gebruikt door taak 3 en 4):
  - `read_secret(stream) -> str`: leest één regel van stdin en valideert `^[0-9a-f]{64}$`. Bij een fout volgt `SystemExit(2)` met de melding `invalid secret on stdin` (zonder de invoer).
  - `role_pattern(role: str) -> re.Pattern`: groepen `(prefix)(password)(suffix)`.
  - `validate_role(role: str) -> str`: `^[a-z_][a-z0-9_]*$`, anders `SystemExit(2)`.
  - `utc_stamp() -> str`: `YYYYmmddTHHMMSSZ`.
  - `main(argv: list[str], stdin=sys.stdin, out=sys.stdout, err=sys.stderr) -> int`.

**Kwetsbaar contract, daarom als code:**

```python
SECRET_RE = re.compile(r"\A[0-9a-f]{64}\Z")
ROLE_RE = re.compile(r"\A[a-z_][a-z0-9_]*\Z")

def role_pattern(role):
    # exact op '://<role>:' zodat 'scrum4me' niet matcht in 'scrum4me_web_runtime'
    return re.compile(r"(://" + re.escape(role) + r":)([^@\s/\"']+)(@)")

def read_secret(stream):
    data = stream.read()
    if data.endswith("\r\n"):
        data = data[:-2]
    elif data.endswith("\n"):
        data = data[:-1]
    if not SECRET_RE.match(data):
        raise SystemExit(2)  # melding via err, nooit de waarde
    return data
```

Het schrijfpad per bestand, in deze volgorde:

1. Voorvalidatie van **alle** bestanden: lezen, `os.stat` bewaren, treffers tellen. Heeft een bestand 0 treffers, dan exit 1 zonder iets te schrijven.
2. Per bestand:
   - back-up `F.bak-<stamp>` via `os.open(..., O_WRONLY|O_CREAT|O_EXCL, 0o600)`, gevolgd door `os.fchown` naar de eigenaar van F;
   - `tempfile.mkstemp(dir=dirname(F))`, dan `fchmod` naar de mode van F, `fchown` naar uid/gid van F, schrijven en `fsync`;
   - opnieuw `os.stat(F)`: wijken `st_mtime_ns`, `st_size` of `st_ino` af van stap 1, dan tempfile weg en een fout;
   - `os.replace(tmp, F)`, gevolgd door `fsync` van de map.
3. Faalt een bestand in stap 2, zet dan alle eerder in deze run herschreven bestanden terug vanuit hun back-up. Meld `FAIL <pad>: <reden>; teruggezet: N; stamp=<S>` en exit 1.
4. Uitvoerregels: `ok <pad> vervangen=<n> mode=<oct>` en `WARN <pad> mode <oct> ruimer dan 640`. Tot slot: `stamp=<S>`.

`--dry-run`: alleen stap 1, met per bestand `dry <pad> treffers=<n>`. Bij `--dry-run` leest het script geen secret van stdin.

`rollback --stamp S --file F…`: controleert eerst of alle `F.bak-S` bestaan (anders exit 1 zonder iets te doen). Daarna per bestand kopiëren naar een tempfile met de mode en eigenaar van het huidige F (bestaat F niet meer, dan eigenaar van de back-up en mode 600), gevolgd door `os.replace`.

- [ ] **Step 1: Schrijf de falende tests** in `scripts/tests/test_rewrite.py`. Werk met `tempfile.TemporaryDirectory`, `OLD = "a"*64`, `NEW = "b"*64`, `OTHER = "c"*64`:
  - `test_env_only_role_password_changes`: het bestand bevat `DATABASE_URL=postgresql://scrum4me_web_runtime:OLD@h:5432/db?schema=public` en `MIGRATE_URL=postgresql://scrum4me:OTHER@h/db`. Na `rewrite --role scrum4me_web_runtime` staat NEW in regel 1 en is regel 2 byte-identiek.
  - `test_json_and_toml`: een `.claude.json`-fixture (`"DATABASE_URL": "postgresql://R:OLD@h/db"`) en een TOML-fixture (`DATABASE_URL = "postgresql://R:OLD@h/db"`). Beide krijgen NEW; JSON blijft geldig (`json.loads`).
  - `test_prefix_role_not_matched`: met `--role scrum4me` blijft een regel met `://scrum4me_web_runtime:OLD@` onaangeroerd, en omdat er 0 treffers zijn volgt exit 1.
  - `test_mode_owner_preserved_and_backup_600`: F heeft mode 0o640; daarna heeft F 0o640 en `F.bak-*` 0o600, met dezelfde uid.
  - `test_zero_matches_refuses_all`: twee bestanden, waarvan het tweede zonder treffer. Exit 1, het eerste bestand is byte-identiek en er is geen `.bak`.
  - `test_midbatch_failure_rolls_back`: drie bestanden, waarbij de map van het derde read-only is (`os.chmod(dir, 0o500)`). Exit 1, bestanden 1 en 2 zijn byte-identiek aan het origineel en de uitvoer bevat `teruggezet: 2`.
  - `test_changed_during_write_refuses`: patch `os.replace` zodat het vlak ervoor F wijzigt, of patch `os.stat` voor de tweede aanroep. Exit 1 en F bevat de externe wijziging.
  - `test_stdin_variants`: `NEW\n` en `NEW\r\n` worden geaccepteerd. `""`, `"NEW\nNEW\n"`, `"B"*64` en `"b"*63` geven exit 2.
  - `test_no_leak`: voor elk scenario hierboven bevatten `out` en `err` noch NEW noch OLD (`assertNotIn`).
  - `test_dry_run_no_write_no_stdin`: `--dry-run` met stdin `io.StringIO("")` geeft exit 0, `treffers=1` en geen `.bak`.
  - `test_rollback_byte_identical`: rewrite gevolgd door `rollback --stamp S` levert byte-identieke bestanden op, met dezelfde mode.
  - `test_rollback_missing_backup_touches_nothing`.

- [ ] **Step 2:** `cd scripts && python3 -m unittest discover -s tests -v`. Verwachting: FAIL (module ontbreekt).
- [ ] **Step 3:** Implementeer het script volgens het contract hierboven (argparse met subparsers; `main` retourneert de exitcode).
- [ ] **Step 4:** Draai de tests opnieuw. Verwachting: alle tests PASS. Draai ze ook op srv en max2 (Linux, root-eigenaar en chown):

```bash
rsync -a scripts/ scrum4me-srv:/tmp/rec-test/ && ssh scrum4me-srv 'cd /tmp/rec-test && sudo python3 -m unittest discover -s tests -v; rm -rf /tmp/rec-test'
```

Doe hetzelfde op max2.

- [ ] **Step 5: Commit.** `git commit -m "feat(idea-221): rotate-env-credential rewrite/rollback"`

---

### Task 3: `alter-role` en `probe`

**Files:**
- Modify: `scripts/rotate-env-credential`
- Create: `scripts/tests/test_scram.py`
- Create: `scripts/tests/test_integration_pg.py` (wordt overgeslagen tenzij `REC_PG_INTEGRATION=1`)

**Interfaces:**
- Consumes: `read_secret`, `validate_role`, `role_pattern` (taak 2).
- Produces:
  - `scram_verifier(password: str, salt: bytes, iterations: int = 4096) -> str`.
  - `parse_dsn(line_match) -> dict(host, port, user, password, dbname)`.

**Kwetsbaar contract (formaat van Postgres), daarom als code:**

```python
def scram_verifier(password, salt, iterations=4096):
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = lambda b: base64.b64encode(b).decode()
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"
```

Hex-wachtwoorden zijn ASCII, dus SASLprep is een no-op.

**`alter-role`:**

- Opties: `--role R [--container scrum4me-postgres] [--db-user scrum4me] [--db-name scrum4me]`.
- Verloop: `read_secret`, `validate_role`, dan `salt = os.urandom(16)`.
- De SQL gaat via stdin (`input=`) naar:

```text
subprocess.run(["docker","exec","-i",C,"psql","-U",U,"-d",D,"-v","ON_ERROR_STOP=1","-tA"], input=sql, capture_output=True, text=True)
```

- De SQL:

```sql
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'R') THEN RAISE EXCEPTION 'role missing'; END IF; END $$;
ALTER ROLE "R" PASSWORD '<verifier>';
```

- Uitvoer: `ok alter-role R T_alter=<UTC ISO>`. Bij een fout: `FAIL alter-role R: <eerste regel van psql-stderr>` (die bevat de verifier niet; controleer in de test dat het ook niet zo is).

**`probe`:**

- Opties: `--role R --file F --expect ok|reject [--image postgres:17]`. Er is geen stdin nodig: het wachtwoord komt uit F.
- Verloop:
  - Neem de eerste treffer van `role_pattern` in F en ontleed de URL daaromheen (host, poort standaard 5432, dbname vóór `?`).
  - Schrijf `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE/PGCONNECT_TIMEOUT=5` naar `tempfile.mkstemp()` (mode 600) en verwijder dat bestand in `finally`.
  - Draai:

```text
docker run --rm --pull never --network host --env-file <tmp> <image> psql -tAc 'select 1'
```

- Beoordeling:
  - `ok`: returncode 0 en uitvoer `1`.
  - `reject`: returncode ≠ 0 en stderr bevat `password authentication failed`.
  - Elke andere uitkomst, zoals een netwerkfout, geeft `FAIL onverwacht: <categorie>` (`auth`, `netwerk`, `anders`) en exit 1. Een netwerkfout telt dus **niet** als geslaagde `reject`.

- [ ] **Step 1: Falende unit tests** (`test_scram.py`):
  - `test_scram_format_and_determinism`: voor wachtwoord `"a"*64` en salt `b"\x00"*16` matcht de uitvoer `^SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]{24}\$[A-Za-z0-9+/=]{44}:[A-Za-z0-9+/=]{44}$`, en twee aanroepen met dezelfde salt geven dezelfde uitvoer. Dat de verifier door Postgres wordt geaccepteerd, bewijst de integratietest in Step 4.
  - `test_parse_dsn_query_and_default_port`: `postgresql://R:x@10.0.0.1/db?schema=public&connection_limit=5` geeft host `10.0.0.1`, poort 5432 en db `db`.
  - `test_alter_role_sql_via_stdin_not_argv`: patch `subprocess.run` en controleer dat het secret én de verifier niet in `args` staan, maar wel in `input`.
  - `test_probe_env_file_removed_and_600`: patch `subprocess.run`, en controleer binnen de mock dat het tempbestand mode 0o600 heeft. Controleer daarna dat het weg is, ook als de mock een exceptie gooit.
  - `test_probe_network_error_is_not_reject`: gesimuleerde stderr `could not connect to server` bij `--expect reject` geeft exit 1.
- [ ] **Step 2:** Draai de tests. Verwachting: FAIL.
- [ ] **Step 3:** Implementeer.
- [ ] **Step 4: Integratietest op srv** (`test_integration_pg.py`, alleen met `REC_PG_INTEGRATION=1`):
  - `setUp`:

```text
docker run -d --rm --name rec-it -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=itpw -e POSTGRES_USER=scrum4me -e POSTGRES_DB=scrum4me postgres:17 -c log_statement=all
```

  Wacht vervolgens tot `pg_isready`, en maak dan `CREATE ROLE r_it LOGIN PASSWORD '<OLD>'` aan via `docker exec -i` (stdin). `itpw` en OLD zijn testwaarden.
  - Test: `alter-role --role r_it --container rec-it` met NEW op stdin geeft exit 0. Daarna geeft `probe --file <fixture met NEW, host 127.0.0.1:55432> --expect ok` exit 0, en `probe --file <fixture met OLD> --expect reject` exit 0.
  - Test: `docker logs rec-it` bevat NEW niet.
  - `tearDown`: `docker rm -f rec-it`.
  - Draaien met:

```bash
rsync -a scripts/ scrum4me-srv:/tmp/rec-test/ && ssh scrum4me-srv 'cd /tmp/rec-test && REC_PG_INTEGRATION=1 python3 -m unittest tests.test_integration_pg -v; rm -rf /tmp/rec-test'
```

  Verwachting: PASS. De container luistert alleen op 127.0.0.1 en is wegwerp; productie-Postgres wordt niet geraakt.
- [ ] **Step 5: Commit.** `git commit -m "feat(idea-221): alter-role (SCRAM via stdin) en probe"`

---

### Task 4: `scan`

**Files:**
- Modify: `scripts/rotate-env-credential`
- Create: `scripts/tests/test_scan.py`

**Interfaces:**
- Consumes: `read_secret`, `role_pattern` (met een ruimer wachtwoorddeel voor scan: `[^@\s]+`).
- Produces: CLI `scan --role R PATH…`. Het huidige wachtwoord komt van stdin.

**Gedrag:**

- Loopt recursief door de paden (symlinks niet volgen; binaire bestanden overslaan, dat wil zeggen bestanden met een NUL-byte in de eerste 8 KiB; ontoegankelijke paden melden als `SKIP <pad>: geen toegang`).
- Per treffer print het `<pad>:<regel> <klasse>`. De klasse is `huidig`, `placeholder/regex` (bevat een van `<>*[]^$` of een spatie) of `ANDERS`.
- Een pad dat eindigt op `.bak-<stamp>` krijgt het achtervoegsel ` (backup)` en telt niet mee voor de exitcode.
- De exitcode is 1 als er een `ANDERS`-treffer buiten back-ups is, en anders 0.

- [ ] **Step 1: Falende tests.**
  - Een boom met één bestand van elke klasse, een `.bak`-bestand met OLD en een binair bestand. Controleer de klassen, de exitcode 1 door `ANDERS`, en dat de uitvoer OLD en NEW niet bevat.
  - Een variant zonder `ANDERS` geeft exit 0.
- [ ] **Step 2:** Draai de tests. Verwachting: FAIL.
- [ ] **Step 3:** Implementeer.
- [ ] **Step 4:** Draai de tests. Verwachting: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(idea-221): scan op credential-residu"`

---

### Task 5: Runbook, kaarten en verwijzingen

**Files:**
- Create: `docs/runbooks/credential-rotation.md`
- Modify (Ops-dashboard-repo, eigen branch en commit): `docs/runbooks/s4m-queue-credential-rotation.md` (verwijzing bovenaan), `docs/runbooks/env-tokens.md` (verwijzing plus sectie "Rotatie")

**Inhoud van `credential-rotation.md`:**

1. **Principes.** Neem de harde regels over uit spec §3.1, plus: nooit via de queue, nooit in issues.
2. **Installatie van het script.**

```bash
scp scripts/rotate-env-credential <host>:/tmp/rec && ssh <host> 'sudo install -m 755 -o root -g root /tmp/rec /usr/local/sbin/rotate-env-credential && rm /tmp/rec'
```

   Leg daarbij de commit-SHA vast.
3. **Keychain.** De in taak 1 bewezen methode voor `new`. Voor `old`:

```bash
ssh scrum4me-srv 'sudo grep -m1 -oE "://scrum4me_web_runtime:[0-9a-f]+@" /srv/scrum4me/secrets/mcp-http.env' | sed -E 's#^://[^:]+:##; s#@$##' | <bewezen keychain-methode, account old>
```

   Controleer vooraf of het huidige wachtwoord hex is. Is het dat niet, pas dan de `grep`-klasse aan naar `[^@]+`. De waarde gaat alleen door pipes.
4. **Generieke procedure, fasen 0–4**, letterlijk volgens spec §4, met commandoblokken. De canary-query (via stdin):

```sql
SELECT coalesce(nullif(application_name,''),'-') AS app, host(client_addr) AS addr,
       count(*) FILTER (WHERE backend_start > :'t_alter') AS nieuw,
       count(*) FILTER (WHERE backend_start <= :'t_alter') AS oud
FROM pg_stat_activity WHERE usename = :'role' GROUP BY 1,2 ORDER BY 1,2;
```

   Aanroep:

```bash
ssh scrum4me-srv "docker exec -i scrum4me-postgres psql -U scrum4me -d scrum4me -v role=scrum4me_web_runtime -v t_alter='<T_alter>'" < canary.sql
```

   Verwachting: elke consumer van de kaart heeft `nieuw ≥ 1`. Rijen met `oud` lopen uit; die worden na 30 minuten opnieuw bekeken.
5. **Kaart `scrum4me_web_runtime`:**
   - De consumertabel uit spec §2.
   - De compose-servicenamen per env-bestand. Meet die in deze taak met:

```bash
ssh <host> 'cd /srv/scrum4me/compose && docker compose config --format json' | python3 -c '<print services met env_file>'
```

     Geef alleen servicenamen en paden weer, geen waarden.
   - De canary-verwachting per consumer (`application_name` of container-IP).
   - Het `rewrite`-commando per host, bijvoorbeeld:

```bash
security find-generic-password -s s4m-db-scrum4me_web_runtime -a new -w | ssh scrum4me-srv 'sudo rotate-env-credential rewrite --role scrum4me_web_runtime --file /srv/scrum4me/compose/worker-idea.env … --file /home/janpeter/.codex/config.toml'
```

   - De herlaadcommando's. Voor de host-MCP's: "sluit of herstart lopende Claude/Codex-sessies op die host; nieuwe sessies lezen de config opnieuw".
   - Het veld "laatste rotatie" en de journal-notitie van 24-09.
6. **Skeletkaarten** voor de credentials uit spec §3.3, elk met de bekende locaties uit IDEA-221 en de regel "bij eerste rotatie opnieuw meten".

- [ ] **Step 1:** Meet de compose-servicenamen per env-bestand op srv en max2. Zet ze in de kaart.
- [ ] **Step 2:** Schrijf het runbook.
- [ ] **Step 3: Argv-controle van het runbook.** Zoek naar commando's die een waarde als argument meegeven:

```bash
grep -nE "PGPASSWORD=|PASSWORD '|-w [^|]|--password" docs/runbooks/credential-rotation.md
```

   Verwachting: alleen treffers in de uitleg over wat verboden is.
- [ ] **Step 4:** Verwijzingen in Ops-dashboard op een eigen branch `docs/idea-221-rotation-pointer`, met een eigen commit.
- [ ] **Step 5: Commit** in deze repo: `git commit -m "docs(idea-221): credential-rotation runbook met kaarten"`

---

### Task 6: Echte rotatie van `scrum4me_web_runtime`

**Voorwaarde:** taken 1–5 zijn klaar en gemerged of gepusht, en JP geeft GO **op het moment zelf**. Deze taak wijzigt productie.

**Files:**
- Modify: `docs/runbooks/credential-rotation.md` (kaart: laatste rotatie, eventuele nieuwe consumers, geleerde lessen)
- Create: `docs/runbooks/evidence/2026-09-XX-rotation-scrum4me_web_runtime.md` (tijden, aantallen en uitkomsten; geen waarden)

- [ ] **Step 1: Fase 0.**
  - `check_queue_empty` en geen lopende jobs.
  - Meld de rotatie in de actieve sessies op de drie hosts.
  - Installeer het script op srv en max2.
  - `rewrite --dry-run` per host: de aantallen moeten gelijk zijn aan de kaart.
  - `pg_stat_activity` levert alleen bekende consumers op.
  - De Keychain bevat `old` en `new`.
- [ ] **Step 2: Fase 1**, achter elkaar: `rewrite` op srv, max2 en de mac; dan `alter-role` (noteer `T_alter`); dan herladen.
- [ ] **Step 3: Fase 2.** Canary, healthchecks, `probe --expect reject` op een `.bak` op srv en max2, `probe --expect ok` op de huidige bestanden, `prisma_migrate_precheck` en `scan`.
- [ ] **Step 4:** Is fase 2 rood en niet binnen 15 minuten te herstellen, voer dan fase 3 (rollback) uit en stop. Is fase 2 groen, ga dan naar fase 4, inclusief de bevestiging van de back-uplijst door JP en `chmod 600` op `Scrum4Me/.env`.
- [ ] **Step 5:** Werk de kaart bij en schrijf het evidence-bestand. Commit met `docs(idea-221): scrum4me_web_runtime geroteerd`.

**Acceptatie:** spec §5, punten 1–4.

---

## Uitvoeringsvolgorde en afhankelijkheden

- Taak 1 staat los van de rest en kan eerst of parallel.
- Taken 2 → 3 → 4 volgen op elkaar (dezelfde file).
- Taak 5 hangt af van 1–4.
- Taak 6 hangt af van alles en vraagt JP's GO op het moment zelf.
