---
status: draft
review: "ronde 1, 2 en 3 NO-GO (mac:codex), alle bevindingen verwerkt; deze versie is nog niet herbeoordeeld; zie §12"
issues: "scrum4me-server ISS-5 (heropend), max2 ISS-15, max2 ISS-16"
product: scrum4me-server (cmsx8zbdh0002hk7rcgxxr00k)
last_updated: "2026-09-28"
---

# Losse compose-kopieën structureel voorkomen — ontwerp en plan increment 1

## 1. Doel in JP's woorden

> Een structurele oplossing voor een probleem dat op scrum4me-server en max2 optreedt. Dit
> gebeurt nu elke dag.

Aanleiding: `compose-collision-check` stuurt elke nacht een melding naar `mac:jp` over
compose-bestanden die een draaiende stack kunnen stoppen. Opruimen hielp niet: na de
opruiming van ISS-5 op 25 september kwam er elke dag een kopie bij.

**Eerst bruikbare resultaat.** Beide hosts zijn schoon volgens dezelfde scanner, en de
oorzaken zijn weggenomen: compose-wijzigingen gaan via git in plaats van via een kopie
ernaast, en When2Watch heeft één runnable compose-bestand.

**Hoe het resultaat zich toont.**

- De geïnstalleerde scanner geeft op beide hosts exitcode 0 en noemt op beide dezelfde
  scanner-hash.
- Veertien nachten achter elkaar komt er geen collision-melding binnen bij `mac:jp`, terwijl
  er in die periode op elke host minstens één compose-wijziging is gedaan. Die wijziging is
  zichtbaar als commit in `git log`, niet als `.bak`.
- Blijft er toch een bevinding staan, dan komt daar één melding per week over, niet één per
  nacht.

**Niet-doelen.**

- Een beheerde edit-route via PR en uitrol (optie 5). Die kan meeliften met stap G.
- Automatische quarantaine (onderdeel C). Alleen als de voorwaarde in §6 optreedt.
- `.env`-backups en ander credential-residu. Dat is het domein van ISS-38 en het
  credential-rotatierunbook.
- De dagelijkse herhaling van de `ops-agent config drift`-melding. Hetzelfde recept past
  daar, maar het is een eigen besluit.
- Retentie van When2Watch-images en -releasemappen.
- Compose-projecten hernoemen of `name:`-directives wijzigen.
- Uitzonderingen in de scanner voor `.bak` of `releases/`.

## 2. Gemeten uitgangssituatie (2026-09-28)

Volledig meetbewijs: [2026-09-28-compose-collision-meting.md](../../runbooks/evidence/2026-09-28-compose-collision-meting.md).
De metingen waren read-only en toonden alleen namen en aantallen.

| | scrum4me-server | max2 |
|---|---|---|
| Scanner | versie van 10 sep, `faf0176619b4…` | versie van 10 juli, `37b942accb72…` |
| Nachtelijke melding | 4 destructief | 1 destructief |
| Werkelijk, volgens de actuele scanner | 5 losse kopieën naast een live `.env` | 22 destructief |
| Losse kopieën onder `/srv` | 6 | 30 |
| Live compose-map onder git | nee | nee |
| Letterlijke secret-vormige waarden in live bestanden | 0 | 0 |
| Idem in kopieën | 0 los, 4 in de tar van 25 sep | 8 |
| Codex en Claude geïnstalleerd | ja | ja |
| Codex laatst gebruikt | 28 sep | 14 sep |
| `~/.codex/AGENTS.md` | aanwezig | ontbreekt |

Op scrum4me-server liep het aantal destructieve bevindingen in drie nachten op van 2 naar 3
naar 4.

## 3. Oorzaken

1. **Geen historie zonder kopie.** `/srv/scrum4me/compose` (beide hosts) en
   `/srv/scrum4me/forgejo` staan niet onder versiebeheer. Wie wil kunnen terugdraaien, maakt
   een kopie ernaast. Die kopie erft het project en de `.env` van de live stack.
2. **De regel bereikt de sessies niet.** "Snapshot als tar, nooit los" staat in runbook
   `ops-agent-host-config-discipline.md` §9 in scrum4me-docker. De instructies die
   hostsessies laden, noemen hem niet. De veilige route vraagt bovendien `sudo`, want
   `/srv/_attic` is van root.
3. **When2Watch-releases zijn elk een compleet project.** Elke release draagt
   `name: when2watch` en een `.env`-symlink. Dat is het ontwerp van de deployroute.
4. **De detector herhaalt en loopt uiteen.** Hij stuurt elke nacht het volledige rapport, ook
   zonder verandering. PR #178 wijzigde alleen de kopie in Ops-dashboard; niets bewaakt dat
   de kopie in scrum4me-docker gelijk blijft.

## 4. Ontwerp

### A. Detector: één bron, meldt bij verandering

Canoniek blijft Ops-dashboard `deploy/ops-agent/check-compose-collision.sh`.

| # | Wijziging | Waarom |
|---|---|---|
| A1 | scrum4me-docker krijgt een byte-identieke kopie, met een bronvermelding (`scripts/check-compose-collision.sh.source`: repo, commit, sha256) en een CI-toets op die sha256 | max2 ziet dan ook losse kopieën; een wijziging aan de kopie zonder de bron valt in CI |
| A2 | De push krijgt `--idempotency-key "compose-collision:<host>:<weekjaar-week>:<hash>"`. Weekjaar en week komen uit `date -u +%G-W%V`. De hash is sha256 over de gesorteerde destructieve bevindingen | Ongewijzigde bevindingen geven binnen een week geen tweede bericht; een wijziging geeft direct een nieuw bericht; een nieuwe week geeft een herinnering |
| A3 | De ernst kijkt of de status `running(` bevát, niet of hij ermee begint | `exited(1), running(4)` is nu ten onrechte een waarschuwing |
| A4 | Elke run noemt de scanner-hash (eerste 12 tekens) in de eerste logregel, ook bij een schone uitkomst. Het rapport noemt hem in de kop, samen met de bevindingen-hash | Uiteenlopen van de hosts is te zien in het journal en in de meldingen |

**A2.** Er is geen statusbestand nodig: de queue bewaakt de uniciteit van de sleutel,
ongeacht de status van het eerdere bericht. Het weekjaar hoort in de sleutel; alleen het
weeknummer zou na een jaar dezelfde sleutel geven voor een bevinding die er nog staat.
Waarschuwingen tellen niet mee in de hash; alleen destructieve bevindingen alarmeren, net
als nu.

**A4.** De huidige scanner stopt bij een schone uitkomst vóór de rapportopbouw. De hash moet
dus vóór die uitgang gelogd worden. De bron van de hash, in deze volgorde:

1. sha256 van het scriptbestand zelf, als `BASH_SOURCE[0]` een leesbaar bestand is. Dit is
   de geïnstalleerde vorm.
2. De waarde van `COMPOSE_COLLISION_SCANNER_SHA`, als die gezet is. Dit is de droogloop over
   SSH, waarbij het script via stdin komt en er geen bestand is om te hashen.
3. Anders `onbekend`.

De scanner blijft read-only.

**Droogloop over SSH.** De beheerder berekent de hash lokaal en geeft hem mee:

```bash
H=$(shasum -a 256 deploy/ops-agent/check-compose-collision.sh | cut -d' ' -f1)
ssh max2 "sudo COMPOSE_COLLISION_SCANNER_SHA=$H DRIFT_NO_NOTIFY=1 bash -s -- max2 /srv" \
  < deploy/ops-agent/check-compose-collision.sh
```

Zolang A4 niet is uitgerold, drukt de scanner de hash niet af. Het bewijs van een droogloop
bestaat dan uit de lokaal berekende hash plus de uitvoer.

### B. Versiebeheer ter plekke en een regel die de sessies bereikt

**B1. Git in de live compose-mappen.** Een lokale repo per map, zonder remote.

| Host | Map | In git |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose` | `docker-compose.yml` |
| scrum4me-server | `/srv/scrum4me/forgejo` | `docker-compose.yml`, `runner-config.yaml` |
| max2 | `/srv/scrum4me/compose` | `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.codex.yml` |

In deze mappen staan `.env`-bestanden en, in de forgejo-map, bestanden die op sleutelparen
lijken. Vier lagen houden die buiten git. Geen ervan is een garantie.

| Laag | Wat hij doet | Wat hij niet doet |
|---|---|---|
| `.gitignore` als allowlist | Alles is genegeerd, behalve de bestanden uit de tabel en `.gitignore` zelf. `git add <naam>` van een ander bestand weigert | Houdt `git add -f` niet tegen |
| Stage-afspraak | Stagen gaat alleen met `git add <bestandsnaam>` van een allowlist-bestand. Nooit `-f`, `-A` of `.`. Vóór de commit leest de editor `git diff --cached` | Is een afspraak, geen techniek |
| `pre-commit`-hook | Weigert een commit met een pad buiten de allowlist, en een commit waarin de gestagede inhoud een letterlijke secret-vormige waarde heeft (dezelfde patroontoets als in het meetbewijs) | Draait pas bij de commit. `git add` heeft de blob dan al in `.git/objects` geschreven, en een geweigerde commit haalt hem niet weg. De patroontoets is geen volledige scan |
| `.git` op mode 700 | Alleen `janpeter` en root lezen de objecten | Agents draaien zelf als `janpeter` |

**Herstel als er toch iets verkeerds is gestaged.** Het recept herstelt alleen de index.
Het wijzigt geen werkbestand, dus ook geen live `.env`. Beproefd in een tijdelijke repo:
[2026-09-28-compose-git-herstelproef.md](../../runbooks/evidence/2026-09-28-compose-git-herstelproef.md).

1. Leg de sha256 van het werkbestand vast.
2. Leg de blob-ID vast: `git ls-files -s -- <pad>` moet precies één regel geven met stage 0;
   de blob-ID is het tweede veld. Geeft het nul of meer regels: stop en vraag JP.
3. Herstel de index: `git restore --staged -- <pad>`. Dit ene commando dekt beide gevallen.
   Een nieuw, geforceerd toegevoegd pad verdwijnt uit de index; een bestand dat git al volgt
   krijgt de index van HEAD terug.
4. Controleer dat de sha256 van het werkbestand gelijk is aan die uit stap 1.
5. Ruim op met `git gc --prune=now`, alleen als er geen andere schrijver in de repo bezig is.
6. Controleer dat `git cat-file -e <blob-ID>` faalt.
7. Vindt git de blob nog: stop. Bepaal welke ref of index hem vasthoudt en vraag JP. Ga niet
   door met gewone commits.

Behandel een echte waarde in alle gevallen als gezien door wie `.git` kon lezen.

Staat er daarna nog een letterlijke waarde in een compose-bestand, dan is dat een gewone
wijziging volgens de hostregel: terug naar de laatste commit met `git restore -- <bestand>`,
of de waarde naar de `.env` en `${VARIABELE}` in het compose-bestand, gevalideerd met
`docker compose -f <bestand> config -q`. De editor kiest en weegt mee of de wijziging al op
de draaiende stack is toegepast.

Het recept geldt voor een repo met minstens één commit; de installatie maakt die. Zonder
commit faalt `git restore --staged` en is `git rm --cached -- <pad>` het juiste commando.

Verder:

- Identiteit staat in de repo zelf (`git config user.name`), niet globaal.
- Git draait als `janpeter`. Root gebruikt `sudo -u janpeter git …`, anders weigert git op
  eigenaarschap.
- De eerste commit bevat alleen de allowlist. Vóór die commit wordt elk bestand getoetst met
  de patroontoets en gelezen.
- Hook en installatie komen uit deze repo: `scripts/compose-git-init` en
  `scripts/compose-git-pre-commit`, met tests in `scripts/tests/`.

**B2. De regel in de instructies die hostsessies laden.** Op beide hosts zijn Claude en
Codex geïnstalleerd. Dezelfde korte sectie komt in elk bestand uit de tabel.

| Host | Bestand | Bereikt |
|---|---|---|
| beide | `/home/janpeter/claude/CLAUDE.md` | Claude en Codex gestart in die map (`AGENTS.md` is er een symlink naar) |
| beide | `~/.claude/rules/compose-wijzigen.md` (nieuw) | Claude, ongeacht de werkmap |
| scrum4me-server | `~/.codex/AGENTS.md` (bestaat) | Codex, ongeacht de werkmap |
| max2 | `~/.codex/AGENTS.md` (nieuw) | Codex, ongeacht de werkmap |

```markdown
## Compose-bestanden wijzigen

- Maak nooit een kopie van een compose-bestand naast het origineel (`cp … .bak`). Zo'n kopie
  erft het project en de `.env` van de live stack; `docker compose -f <kopie> down` stopt
  productie (incident 2026-07-09, ISS-5).
- De live compose-mappen staan onder git. Begin met `git status`. Staat er een wijziging die
  niet van jou is: stop, toon `git status` en `git diff --stat`, en vraag JP. Commit
  andermans wijziging niet.
- Werkwijze: wijzig; valideer met `docker compose -f <bestand> config -q`; stage met
  `git add <bestandsnaam>`, nooit met `-f`, `-A` of `.`; lees `git diff --cached`; commit met
  het waarom. Terugdraaien: `git checkout <commit> -- <bestand>`.
- In een compose-bestand hoort geen letterlijk wachtwoord, token of URL met credentials.
  Gebruik `${VARIABELE}` en zet de waarde in de `.env`.
- Draai git daar als `janpeter`, niet als root.
- Toch een momentopname buiten git nodig? Een tarball onder `/srv/_attic/<datum>/` met
  MANIFEST, mode 600. Nooit een los bestand.
```

Een vuile werkboom is het enige signaal dat een andere sessie met hetzelfde bestand bezig
is. Daarom stopt de regel daar, in plaats van andermans wijziging mee te committen.

**B3. Eenmalige opruiming.** De bestaande losse kopieën gaan als tarball naar
`/srv/_attic/2026-09-28/`, volgens het inpakrecept in E. Tar, MANIFEST en SHA256SUMS krijgen
mode 600 (root), omdat een deel van de kopieën letterlijke secret-vormige waarden bevat. De
tar van 25 september krijgt alsnog mode 600.

### C. Vangnet: automatische quarantaine (voorwaardelijk)

Niet in increment 1. Zie §6 voor de voorwaarde en de schets.

### D. When2Watch: één runnable compose per project

- **D2. Procedure, eerst.** `deploy/README.md` van When2Watch krijgt twee stappen. Na het
  omzetten van `current`: pak `compose.yaml` van de vorige release in. Bij terugdraaien: pak
  hem eerst uit in de doelrelease. De terugdraaistappen in
  `docs/runbooks/idea-219-r1-cutover.md` en `docs/runbooks/idea-219-r2-cutover.md` starten
  een oude release vanuit zijn releasemap (`fb7a690`, `8b87838`); die krijgen dezelfde
  uitpakstap.
- **D1. Eenmalig, daarna.** In de 15 releases die niet `current` zijn, gaat `compose.yaml` in
  `release-compose.tar` in dezelfde releasemap, volgens het inpakrecept in E. Die naam valt
  buiten de zoekpatronen van de scanner. De release waar `current` naar wijst en de
  draaiende stack blijven onaangeroerd; het geregistreerde configbestand verandert niet.

D2 gaat vóór D1. Anders verwijzen de herstelstappen een tijd lang naar een bestand dat er
niet meer staat.

De dagelijkse cron hangt niet af van een oude release: `deploy/when2watch-sync.sh` doet
alleen `docker exec when2watch-web-1`.

Tijdens een deploy hebben twee releases kort een los `compose.yaml`. Dat is aanvaard: de
scanner draait eenmaal per nacht.

### E. Inpakrecept (gedeeld door B3 en D1)

Runbook §9 in scrum4me-docker toont `tar … && rm -rf` zonder de tar terug te lezen. Dit
recept leest hem wel terug.

**Onderhoudsvenster.** Tijdens de opruiming loopt er geen deploy en schrijft niemand anders
in de betrokken mappen. JP bevestigt dat vooraf. Het recept vraagt geen nieuwe component.

1. **Lijst vastleggen.** Eén lijst met het volledige pad en de sha256 van elk bronbestand.
   Geen globs. De lijst is wat JP goedkeurt.
2. **Opnieuw toetsen vlak vóór de uitvoering.** Lees `docker compose ls --all` en, voor
   When2Watch, `readlink current`. Staat een geregistreerd configbestand of een bestand
   onder `current` op de lijst, of wijkt een sha256 af van de lijst: stop.
3. **Tar maken** met `--format=posix --numeric-owner`, mode 600.
4. **Teruglezen.** Pak de tar uit in een map van `mktemp -d` en vergelijk de sha256 van elk
   uitgepakt bestand met de lijst.
5. **Verwijderen.** Pas daarna, precies de paden van de lijst, één voor één. Direct vóór
   elk bestand: bereken de sha256 opnieuw en vergelijk hem met de lijst, en lees
   `docker compose ls --all` en `readlink current` opnieuw. Wijkt er iets af, of is het pad
   inmiddels een geregistreerd configbestand of een bestand onder `current`: stop, en
   verwijder ook de rest niet.
6. **Natoets.** De sha256 van de live configbestanden is gelijk aan vóór receptstap 1, en
   `docker compose ls --all` toont dezelfde projecten, statussen en configbestanden.

Receptstap 4 is tegelijk de proef van het uitpakken: hij voert de extractie uit die de
terugdraaiprocedure voorschrijft.

## 5. Increment 1 — uitwerking

Volgorde: eerst opruimen (het gevaar weg), dan de oorzaken, dan de detector. De opruiming
hangt niet af van de scanner-PR's; de droogloop levert de actuele scanner over SSH aan.

### Stap 1 — Opruiming scrum4me-server (B3)

- **Doel:** geen losse compose-kopie meer naast een live `.env`.
- **Raakt:** 5 bestanden in `/srv/scrum4me/forgejo` en `/srv/scrum4me/compose`; de kopie in
  `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/` wordt ter plekke een tarball;
  `chmod 600` op de drie bestanden in `/srv/_attic/2026-09-25/`.
- **Acceptatie:** het inpakrecept is volledig doorlopen; de tar bevat precies de bestanden
  van de lijst.
- **Verificatie:**
  `sudo DRIFT_NO_NOTIFY=1 /srv/scrum4me/ops-agent-drift/check-compose-collision.sh 154 /srv`
  geeft exitcode 0.

### Stap 2 — When2Watch-procedure (D2)

- **Doel:** de herstelstappen kloppen vóórdat er een `compose.yaml` verdwijnt.
- **Raakt:** in When2Watch `deploy/README.md`, `docs/runbooks/idea-219-r1-cutover.md` en
  `docs/runbooks/idea-219-r2-cutover.md`.
- **Acceptatie:** elke stap die een oude release start, noemt eerst het uitpakken van
  `release-compose.tar`. De PR is gemerged.

### Stap 3 — Opruiming max2 (B3 en D1)

- **Doel:** als stap 1, plus één runnable compose voor When2Watch.
- **Afhankelijk van:** stap 2 gemerged.
- **Raakt:** 30 losse kopieën (24 in `/srv/scrum4me/compose`, 2 in `/srv/immich`, 2 in
  `/srv/apps/media-organizer/repo/deploy`, 1 in `/srv/apps/tei`, 1 in
  `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16`) en `compose.yaml` in 15
  When2Watch-releases.
- **Acceptatie:** het inpakrecept is volledig doorlopen, per releasemap en voor de losse
  kopieën; `when2watch-web-1` en `when2watch-db-1` zijn healthy; de publieke health geeft
  200; `compose.yaml` staat alleen nog in de release waar `current` naar wijst.
- **Verificatie:** de droogloop over SSH uit onderdeel A geeft 0 destructief. De lokaal
  berekende hash van de scanner staat bij het bewijs.

### Stap 4 — Git ter plekke (B1)

- **Doel:** historie en terugdraaien zonder kopie.
- **Raakt:** in deze repo `scripts/compose-git-init`, `scripts/compose-git-pre-commit` en
  `scripts/tests/test_compose_git.py`; op de hosts de drie mappen uit B1 (`.git/`,
  `.gitignore`, `.git/hooks/pre-commit`).
- **Acceptatie, in een tijdelijke repo zonder echte secrets.** Proefwaarden zijn korter dan
  20 tekens; de secret-scan van deze repo weigert langere:
  1. `git add <naam>` van een bestand buiten de allowlist weigert.
  2. Een commit met een geforceerd gestaged pad buiten de allowlist wordt geweigerd.
  3. Een commit van een allowlist-bestand met een letterlijke proefwaarde onder
     `POSTGRES_PASSWORD` wordt geweigerd.
  4. Een commit met alleen geïnterpoleerde waarden slaagt.
  5. Het herstelrecept is doorlopen voor punt 2 (nieuw pad) en voor punt 3 (gevolgd
     bestand). In beide gevallen is het werkbestand daarna byte-gelijk aan vóór het herstel
     en faalt `git cat-file -e` op de vastgelegde blob-ID. Bij punt 3 is de index weer
     gelijk aan HEAD en staat het bestand nog in `git ls-files`.
- **Acceptatie, op de hosts:** `git ls-files` toont precies de allowlist;
  `git status --porcelain` is leeg; `.git` heeft mode 700; de hook is byte-gelijk aan de
  bron; de eerste commit bevat de live bestanden ongewijzigd.
- **Verificatie:** `docker compose -f <bestand> config -q` slaagt; de scanner blijft op 0;
  de eerstvolgende run van `ops-agent-drift` en van de deploy-flows wijkt niet af van de
  vorige. De hookproeven draaien niet in een live map.

### Stap 5 — Hostregel (B2)

- **Doel:** elke hostsessie kent de regel, ongeacht de werkmap.
- **Raakt:** de bestanden uit B2 op beide hosts.
- **Acceptatie:** de sectie staat woordelijk gelijk in alle genoemde bestanden.
- **Verificatie (praktijkproef, vier sessies):** per host een verse Claude-sessie en een
  verse Codex-sessie, gestart buiten `/home/janpeter/claude`.
  1. *Geladen.* De sessie krijgt de vraag wat de regel is voor het wijzigen van een
     compose-bestand. Ze noemt uit zichzelf: geen kopie ernaast, en git.
  2. *Gevolgd.* De sessie wijzigt een poort in een proef-compose-bestand in een tijdelijke
     map met een git-repo. Na afloop is er een commit en geen kopie.
- **Poort:** de observatie van stap 9 begint pas als alle vier de sessies op beide punten
  slagen. Slaagt een sessie niet op punt 1, dan is de laadroute voor dat sessietype fout en
  wordt die eerst hersteld.

### Stap 6 — Scanner in Ops-dashboard (A2, A3, A4)

- **Doel:** melden bij verandering, juiste ernst, zelf-identificerende uitvoer.
- **Raakt:** `deploy/ops-agent/check-compose-collision.sh`; nieuw
  `test/compose-collision-check.test.ts` naar het patroon van
  `test/repo-ownership-check.test.ts` (script uitvoeren in een tijdelijke map, met een
  nagebootste `docker` en `s4m-queue` op het PATH).
- **Acceptatie:**
  1. Twee runs met dezelfde bevindingen geven dezelfde sleutel.
  2. Eén extra losse kopie geeft een andere sleutel.
  3. Een andere week geeft een andere sleutel; dezelfde week in een ander weekjaar ook.
  4. Een resolvende kopie bij status `exited(1), running(4)` telt als destructief; bij
     status `exited(1)` blijft het een waarschuwing.
  5. Een schone root geeft exitcode 0, geen push, en wél de scanner-hash in de log.
  6. Uitgevoerd als bestand noemt de scanner de sha256 van dat bestand.
  7. Uitgevoerd via stdin noemt de scanner de waarde van `COMPOSE_COLLISION_SCANNER_SHA`, en
     zonder die variabele `onbekend`.
- **Verificatie:** de tests zijn eerst rood zonder de wijziging en daarna groen. De
  nagebootste `docker` bewijst alleen de logica van het script; het gedrag van Compose zelf
  is bewezen met de drooglopen op de hosts.

### Stap 7 — Scanner in scrum4me-docker (A1)

- **Doel:** max2 draait dezelfde scanner.
- **Afhankelijk van:** stap 6 gemerged.
- **Raakt:** `scripts/check-compose-collision.sh` (vervangen), nieuw
  `scripts/check-compose-collision.sh.source`, een sha256-toets in `.forgejo/workflows/ci.yml`,
  en runbook `ops-agent-host-config-discipline.md` §9 (het inpakrecept met teruglezen, en een
  verwijzing naar git ter plekke en naar de plek van de hostregel).
- **Acceptatie:** de kopie is byte-gelijk aan de gemergede versie uit stap 6; de CI-toets is
  rood als de kopie wijzigt zonder de bronvermelding.

### Stap 8 — Uitrol van de scanner

- **Doel:** beide hosts draaien de nieuwe versie.
- **Raakt:** scrum4me-server via `deploy/ops-agent/scripts/apply-drift-runtime.sh` (de merge
  alleen werkt de runtime-kopie niet bij); max2 via de pull van
  `/srv/scrum4me/repos/scrum4me-docker`.
- **Acceptatie:** `sha256sum` van het bestand uit `ExecStart` is op beide hosts gelijk aan de
  bron in Ops-dashboard.
- **Verificatie:** de geïnstalleerde scanner geeft op beide hosts exitcode 0 en logt dezelfde
  scanner-hash.

### Stap 9 — Observatie

- **Afhankelijk van:** de poort van stap 5.
- **Observatie:** veertien nachten. Afsluiten van ISS-5, ISS-15 en ISS-16 met resolutie als
  het resultaat uit §1 zichtbaar is.

## 6. Increment 2 — automatische quarantaine (voorwaardelijk)

**Voorwaarde.** Nadat de poort van stap 5 is gehaald, verschijnt binnen veertien dagen
opnieuw een losse compose-kopie naast een live configbestand. Dan is aangetoond dat een
geladen regel niet volstaat.

**Schets.** Een apart script met eigen timer, vóór de nachtelijke scan. Het verplaatst een
bestand alleen als alles hieronder geldt:

1. Het staat in dezelfde map als een configbestand dat `docker compose ls` noemt.
2. De naam is de naam van dat configbestand plus een suffix.
3. Git volgt het bestand niet.
4. De ctime is ouder dan een uur. De mtime is onbruikbaar, want `cp -p` bewaart die van het
   origineel.

Het bestand gaat volgens het inpakrecept naar `/srv/_attic/<datum>/`, met het
terugzetcommando in het MANIFEST. Eén melding per quarantaine. Het script kent een droogloop.

Dit is een geautomatiseerde verplaatsing op productie en vraagt een staand akkoord van JP.

## 7. Beslissingen voor JP

| # | Beslissing | Voorstel |
|---|---|---|
| 1 | Akkoord op de eenmalige opruiming op beide hosts (stap 1 en 3) | Ja; je keurt de lijst uit het inpakrecept goed en bevestigt het onderhoudsvenster |
| 2 | Akkoord op git in de drie live mappen en op de hostregel (stap 4 en 5) | Ja |
| 3 | Bewaartermijn van de quarantaine-tars met letterlijke secret-vormige waarden | 90 dagen, daarna verwijderen |
| 4 | Ritme van de herinnering | Wekelijks |
| 5 | Onderdeel C nu bouwen of voorwaardelijk houden | Voorwaardelijk; de reviewer noemt dat proportioneel |
| 6 | Vierde reviewronde door `mac:codex` op deze versie | Ja; de verwerking van ronde 3 is niet herbeoordeeld |
| 7 | Indeling bij materialisatie | Eén PBI onder scrum4me-server, gekoppeld aan ISS-5; stap 2 als story onder When2Watch |
| 8 | B1 houden, of vervangen door een momentopname-helper die een tarball in `/srv/_attic` zet | Houden. Alle drie de rondes raakten de omgang met secrets in B1. Een helper heeft daar minder oppervlak, maar geeft geen diff-historie en vraagt `sudo` |

## 8. Risico's

| Risico | Gevolg | Maatregel |
|---|---|---|
| Een secret belandt in git | Blob leesbaar voor `janpeter` en root | De vier lagen uit B1, het herstelrecept, en de proeven in stap 4 |
| De regel wordt niet geladen in een sessietype | Kopieën blijven komen | De poort in stap 5; onderdeel C als vangnet |
| Twee sessies wijzigen tegelijk hetzelfde bestand | Een wijziging gaat verloren | De regel stopt bij een vuile werkboom |
| A2 onderdrukt een blijvend gevaar | Bevinding raakt uit beeld | Wekelijkse herinnering; de issues blijven open tot de host veertien nachten schoon is |
| Een ops-agent-flow verwacht een schone map | Flow faalt op `.git` of `.gitignore` | Verificatie in stap 4 |
| `current` verschuift of een bronbestand wijzigt tijdens de opruiming | De actieve release verliest zijn `compose.yaml`, of er verdwijnt inhoud die niet in de tar zit | Onderhoudsvenster, en de hertoets per bestand in receptstap 5 van onderdeel E |
| Terugdraaien van When2Watch kost een extra stap | Vertraging onder druk | De procedure staat er vóór de opruiming (stap 2) |
| max2 heeft geen backup van `/srv/scrum4me/compose` | Lokale git-historie verdwijnt bij schijfverlies | Aanvaard in increment 1; een remote hoort bij optie 5 |

## 9. Overwogen en afgewezen

- **`.bak` of `releases/` uitsluiten in de scanner.** Runbook §9 wijst dit af. Zo'n
  uitsluiting hield eerder 21 runnable kopieën twee maanden onzichtbaar.
- **De live `.env` uit de compose-map halen**, zodat geen enkele kopie kan interpoleren.
  Raakt elk geautomatiseerd pad en elke handmatige aanroep.
- **Een wrapper om `docker compose`** die niet-geregistreerde bestanden weigert. Elk
  automatiseringspad loopt er dan doorheen.
- **Eén vast compose-bestand voor When2Watch buiten `releases/`.** Verandert het
  geregistreerde configpad en het pad van de bind-mount van `db`. Of Compose daardoor
  containers opnieuw aanmaakt is niet gemeten en vraagt eerst een repetitie. Kan later, samen
  met het geplande deployscript.
- **Issues aanmaken vanuit de scanner.** De queue-CLI heeft daar geen commando voor.
- **Andermans ongecommitte wijziging eerst committen.** Stond in de eerste versie van de
  hostregel. Het mengt twee wijzigingen en verbergt dat een andere sessie bezig is.

## 10. Wijziging ten opzichte van het eerste advies

Het eerste advies noemde versiebeheer en automatische quarantaine samen, met als reden dat
een gedocumenteerde regel geen dag standhield. De meting nuanceert dat: de regel stond in een
runbook in een andere repo en niet in de instructies die hostsessies laden. Er is dus nog
geen bewijs dat een geladen regel faalt. Daarom is quarantaine nu voorwaardelijk.

Twee dingen zijn erbij gekomen. Onderdeel B geldt ook voor max2, dat 24 losse kopieën in de
live compose-map heeft. En de scanner heeft een rangschikkingsdefect (A3), gevonden door hem
voor het eerst op max2 te draaien.

## 11. Reviewfocus voor de deltareview

1. B1: laat het herstelrecept elk werkbestand ongemoeid, en dekt de proef wat het recept
   belooft?
2. Heeft de verwerking van ronde 3 iets stukgemaakt dat eerder als opgelost gold?

## 12. Review record

| Ronde | Reviewer | Commit | Oordeel | Bevindingen |
|---|---|---|---|---|
| 1 | `mac:codex` | `9a1a253` | NO-GO | 0 BLOCKER, 4 MAJOR, 1 MINOR |
| 2 (delta) | `mac:codex` | `c6bef0f` | NO-GO | 0 BLOCKER, 2 MAJOR, 0 MINOR |
| 3 (delta) | `mac:codex` | `7f75cb9` | NO-GO | 1 BLOCKER, 0 MAJOR, 1 MINOR |

De versie na ronde 3 is niet herbeoordeeld. Een vierde ronde is een beslissing van JP.

### Ronde 1

Verzoek `7a9bbffd-843d-43f4-abd2-5a021d462e24`, antwoord
`7bf728f5-71ad-4172-ac99-550361b0068d`. Alle vijf bevindingen zijn nagemeten en juist
bevonden.

| # | Ernst | Bevinding | Verwerking |
|---|---|---|---|
| 1 | MAJOR | De regel bereikt Codex op max2 niet buiten `/home/janpeter/claude`; de proef toont niet dat de regel geladen is | Overgenomen. Nagemeten: Codex is op beide hosts geïnstalleerd en `~/.codex/AGENTS.md` ontbreekt op max2. B2 voegt dat bestand toe. Stap 5 toetst eerst of de regel geladen is en is een poort vóór de observatie |
| 2 | MAJOR | D1 komt vóór de aangepaste herstelprocedure; D1 mist de tarcontrole vóór het verwijderen | Overgenomen. D2 is stap 2 en gaat vóór D1. Onderdeel E is één inpakrecept met teruglezen, voor B3 en D1 |
| 3 | MAJOR | De hook kan een blob niet uit `.git/objects` weren; hij laat een secret in een toegelaten bestand door | Overgenomen. B1 beschrijft vier lagen met hun grenzen, een stage-afspraak, een inhoudstoets in de hook en een herstelrecept. De hostregel commit andermans wijziging niet meer |
| 4 | MAJOR | A4 werkt niet bij een droogloop via stdin en niet bij een schone uitgang | Overgenomen. A4 logt de hash op elke uitgang en kent drie hashbronnen. Stap 6 toetst beide uitvoeringsvormen |
| 5 | MINOR | De sleutel legt het ISO-weekjaar niet vast | Overgenomen. A2 pint `date -u +%G-W%V`; stap 6 toetst de jaargrens |

**Eén deelvoorstel is niet overgenomen.** De reviewer stelde bij bevinding 2 een proef voor
met `docker compose config -q` op een uitgepakte oude release in een tijdelijke map.
Receptstap 4 in onderdeel E voert de extractie al uit en bewijst dat het teruggezette bestand
byte-gelijk is aan het origineel. Een proef in een tijdelijke map toetst daarbovenop vooral
de proefopstelling, want de `.env`-symlinks staan daar niet.

### Ronde 2 (delta)

Verzoek `a59a3f9d-99c0-4bc4-96e0-8092e661b004`, antwoord
`ad1c7421-ed67-4724-8dcc-5a6342d08288`.

De reviewer beoordeelde de bevindingen 1, 3, 4 en 5 uit ronde 1 als opgelost en bevinding 2
als deels opgelost. Hij onderschreef de afwijzing van het deelvoorstel. Beide nieuwe
bevindingen gaan over tekst die in ronde 1 is toegevoegd.

| # | Ernst | Bevinding | Verwerking |
|---|---|---|---|
| 1 | MAJOR | Het inpakrecept toetst alleen vooraf. Verschuift `current` of wijzigt een bronbestand daarna, dan verwijdert het recept een actief bestand of inhoud die niet in de tar zit | Overgenomen. Onderdeel E vraagt een onderhoudsvenster, en receptstap 5 toetst per bestand opnieuw vlak vóór het verwijderen |
| 2 | MAJOR | Het herstelrecept gebruikt `git rm --cached` ook voor een bestand dat git al volgt, en zet daarmee het verwijderen van het live bestand klaar. De blob-ID wordt niet vooraf vastgelegd en er is geen stoppad | Overgenomen. B1 onderscheidt een nieuw pad van een gevolgd bestand, legt de blob-ID eerst vast, en stopt als de blob blijft bestaan. Stap 4 stuurt beide gevallen door het herstelrecept. In ronde 3 vervangen door één commando voor beide gevallen |

### Ronde 3 (delta)

Verzoek `5de71ced-e9fc-4dcd-b292-adbcbf2e00dc`, antwoord
`1f2688c7-f58e-4faa-a3fe-429a6b9517f5`.

De reviewer beoordeelde bevinding 1 uit ronde 2 (inpakrecept) als opgelost op ontwerpniveau
en bevinding 2 (herstelrecept) als deels opgelost. A2, A4, B2 en de volgorde van D2 en D1
bleven correct.

| # | Ernst | Bevinding | Verwerking |
|---|---|---|---|
| 1 | BLOCKER | Het herstelrecept schrijft voor beide gevallen voor om de letterlijke waarde in het werkbestand te vervangen. Bij een geforceerd gestagede live `.env` breekt dat de credential | Overgenomen, en kleiner opgelost dan voorgesteld. Het recept herstelt alleen de index met één commando en wijzigt geen werkbestand. Een letterlijke waarde in een compose-bestand is een gewone wijziging buiten het recept. Het recept is eerst beproefd |
| 2 | MINOR | `git ls-files -s` geeft meer dan alleen de blob-ID, en bij een unmerged pad meerdere regels | Overgenomen. Receptstap 2 eist precies één regel met stage 0 en neemt het tweede veld |

**Afwijking van het voorstel bij bevinding 1.** De reviewer stelde twee volledig gescheiden
herstelpaden voor. De proef laat zien dat `git restore --staged` beide gevallen dekt zonder
het werkbestand te raken. Eén pad is kleiner en laat minder ruimte voor de fout die in ronde
2 en 3 is gevonden.

**Terugkerend patroon.** De bevindingen in ronde 2 en 3 zaten in procedures die zonder proef
waren opgeschreven. Beslissing 8 in §7 legt de vraag bij JP of B1 de moeite waard blijft.
