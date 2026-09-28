---
status: draft
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

- Een droogloop van de scanner geeft op beide hosts exitcode 0, met dezelfde scanner-hash in
  de uitvoer.
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
| A2 | De push krijgt `--idempotency-key "compose-collision:<host>:<ISO-week>:<hash>"`. De hash is sha256 over de gesorteerde destructieve bevindingen | Ongewijzigde bevindingen geven binnen een week geen tweede bericht; een wijziging geeft direct een nieuw bericht; een nieuwe week geeft een herinnering |
| A3 | De ernst kijkt of de status `running(` bevát, niet of hij ermee begint | `exited(1), running(4)` is nu ten onrechte een waarschuwing |
| A4 | De kop van het rapport noemt de scanner-hash (eerste 12 tekens) en de bevindingen-hash | Uiteenlopen van de hosts is dan in de meldingen zelf te zien |

A2 heeft geen statusbestand nodig: de queue bewaakt de uniciteit van de sleutel, ongeacht de
status van het eerdere bericht. Waarschuwingen tellen niet mee in de hash; alleen
destructieve bevindingen alarmeren, net als nu.

De scanner blijft read-only.

### B. Versiebeheer ter plekke en een regel die de sessies bereikt

**B1. Git in de live compose-mappen.** Een lokale repo per map, zonder remote.

| Host | Map | In git |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose` | `docker-compose.yml` |
| scrum4me-server | `/srv/scrum4me/forgejo` | `docker-compose.yml`, `runner-config.yaml` |
| max2 | `/srv/scrum4me/compose` | `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.codex.yml` |

- `.gitignore` is een allowlist: alles genegeerd, behalve de bestanden uit de tabel en
  `.gitignore` zelf. In deze mappen staan `.env`-bestanden en, in de forgejo-map, bestanden
  die op sleutelparen lijken.
- Een `pre-commit`-hook weigert elk pad buiten de allowlist. Reden: een blob in
  `.git/objects` is leesbaar voor iedereen op de host, ook als het bronbestand mode 600 had.
- `.git` krijgt mode 700.
- Identiteit staat in de repo zelf (`git config user.name`), niet globaal.
- Git draait als `janpeter`. Root gebruikt `sudo -u janpeter git …`, anders weigert git op
  eigenaarschap.

**B2. De regel in de instructies die hostsessies laden.** Dezelfde korte sectie komt in elk
instructiebestand dat op de host bestaat:

| Host | Bestanden |
|---|---|
| scrum4me-server | `/home/janpeter/claude/CLAUDE.md`, `~/.claude/rules/compose-wijzigen.md`, `~/.codex/AGENTS.md` |
| max2 | `/home/janpeter/claude/CLAUDE.md`, `~/.claude/rules/compose-wijzigen.md` |

`AGENTS.md` in `/home/janpeter/claude` is op beide hosts een symlink naar `CLAUDE.md`.

```markdown
## Compose-bestanden wijzigen

- Maak nooit een kopie van een compose-bestand naast het origineel (`cp … .bak`). Zo'n kopie
  erft het project en de `.env` van de live stack; `docker compose -f <kopie> down` stopt
  productie (incident 2026-07-09, ISS-5).
- De live compose-mappen staan onder git. Werkwijze: `git status`; commit eerst wat er nog
  ongecommit staat; wijzig; valideer met `docker compose -f <bestand> config -q`; commit met
  het waarom. Terugdraaien: `git checkout <commit> -- <bestand>`.
- Draai git daar als `janpeter`, niet als root.
- Toch een momentopname buiten git nodig? Een tarball onder `/srv/_attic/<datum>/` met
  MANIFEST, mode 600. Nooit een los bestand.
```

**B3. Eenmalige opruiming.** De bestaande losse kopieën gaan als tarball naar
`/srv/_attic/2026-09-28/`, volgens het recept van ISS-5: tar maken, uitpakken in een
tijdelijke map, checksums vergelijken, en pas daarna de originelen verwijderen. Verschil met
ISS-5: tar, MANIFEST en SHA256SUMS krijgen mode 600 (root), omdat een deel van de kopieën
letterlijke secret-vormige waarden bevat. De tar van 25 september krijgt alsnog mode 600.

### C. Vangnet: automatische quarantaine (voorwaardelijk)

Niet in increment 1. Zie §6 voor de voorwaarde en de schets.

### D. When2Watch: één runnable compose per project

- **D1. Eenmalig.** In de 15 releases die niet `current` zijn, gaat `compose.yaml` in
  `release-compose.tar` in dezelfde releasemap. Het losse bestand verdwijnt. Die naam valt
  buiten de zoekpatronen van de scanner. De release `5dd8b3f` en de draaiende stack blijven
  onaangeroerd; het geregistreerde configbestand verandert niet.
- **D2. Procedure.** `deploy/README.md` van When2Watch krijgt twee stappen. Na het omzetten
  van `current`: pak `compose.yaml` van de vorige release in. Bij terugdraaien: pak hem eerst
  uit in de doelrelease. De terugdraaistappen in `docs/runbooks/idea-219-r1-cutover.md` en
  `docs/runbooks/idea-219-r2-cutover.md` starten een oude release vanuit zijn releasemap
  (`fb7a690`, `8b87838`); die krijgen dezelfde uitpakstap.

De dagelijkse cron hangt niet af van een oude release: `deploy/when2watch-sync.sh` doet
alleen `docker exec when2watch-web-1`.

Tijdens een deploy hebben twee releases kort een los `compose.yaml`. Dat is aanvaard: de
scanner draait eenmaal per nacht.

## 5. Increment 1 — uitwerking

Volgorde: eerst opruimen (het gevaar weg), dan de oorzaken, dan de detector. De opruiming
hangt niet af van de scanner-PR's; de droogloop kan de actuele scanner over SSH aanleveren.

### Stap 1 — Opruiming scrum4me-server (B3)

- **Doel:** geen losse compose-kopie meer naast een live `.env`.
- **Raakt:** 5 bestanden in `/srv/scrum4me/forgejo` en `/srv/scrum4me/compose`; de kopie in
  `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16/` wordt ter plekke een tarball (runbook
  §9); `chmod 600` op de drie bestanden in `/srv/_attic/2026-09-25/`.
- **Acceptatie:** sha256 van de live compose-bestanden is voor en na gelijk;
  `docker compose ls` toont dezelfde projecten, statussen en configbestanden; de tar bevat
  precies de bestanden uit het MANIFEST.
- **Verificatie:**
  `sudo DRIFT_NO_NOTIFY=1 /srv/scrum4me/ops-agent-drift/check-compose-collision.sh 154 /srv`
  geeft exitcode 0.

### Stap 2 — Opruiming max2 (B3 en D1)

- **Doel:** als stap 1, plus één runnable compose voor When2Watch.
- **Raakt:** 30 losse kopieën (24 in `/srv/scrum4me/compose`, 2 in `/srv/immich`, 2 in
  `/srv/apps/media-organizer/repo/deploy`, 1 in `/srv/apps/tei`, 1 in
  `/srv/scrum4me/backups/forgejo-pre-v15-2026-05-16`) en `compose.yaml` in 15
  When2Watch-releases.
- **Acceptatie:** als stap 1; daarnaast zijn `when2watch-web-1` en `when2watch-db-1` healthy,
  geeft de publieke health 200, en staat `compose.yaml` alleen nog in `releases/5dd8b3f`.
- **Verificatie:** droogloop van de actuele scanner geeft 0 destructief:
  `ssh max2 'sudo DRIFT_NO_NOTIFY=1 bash -s -- max2 /srv' < deploy/ops-agent/check-compose-collision.sh`.

### Stap 3 — Git ter plekke (B1)

- **Doel:** historie en terugdraaien zonder kopie.
- **Raakt:** de drie mappen uit B1: `.git/`, `.gitignore`, `.git/hooks/pre-commit`.
- **Acceptatie:** `git ls-files` toont precies de allowlist; `git status --porcelain` is leeg;
  de eerste commit bevat de live bestanden ongewijzigd (sha256 gelijk aan vóór de stap).
- **Verificatie:**
  - Negatieve proef: een leeg proefbestand `hook-proof.env` toevoegen met `git add -f` en
    committen moet falen. Daarna het proefbestand verwijderen.
  - `docker compose -f <bestand> config -q` slaagt; de droogloop van de scanner blijft 0.
  - De eerstvolgende run van `ops-agent-drift` en van de deploy-flows wijkt niet af van de
    vorige.

### Stap 4 — Hostregel (B2)

- **Doel:** elke hostsessie kent de regel, ongeacht de werkmap.
- **Raakt:** de instructiebestanden uit B2 op beide hosts.
- **Acceptatie:** de sectie staat woordelijk gelijk in alle genoemde bestanden.
- **Verificatie (praktijkproef):** een verse Claude-sessie en een verse Codex-sessie op de
  host, gestart buiten `/home/janpeter/claude`, krijgen de opdracht een poort te wijzigen in
  een proef-compose-bestand in een tijdelijke map met een git-repo. Bewijs: de mapinhoud na
  afloop. Geslaagd als er een commit is en geen kopie. Dit bewijst dat de regel geladen
  wordt; of hij standhoudt, blijkt in stap 8.

### Stap 5 — Scanner in Ops-dashboard (A2, A3, A4)

- **Doel:** melden bij verandering, juiste ernst, zelf-identificerend rapport.
- **Raakt:** `deploy/ops-agent/check-compose-collision.sh`; nieuw
  `test/compose-collision-check.test.ts` naar het patroon van
  `test/repo-ownership-check.test.ts` (script uitvoeren in een tijdelijke map, met een
  nagebootste `docker` en `s4m-queue` op het PATH).
- **Acceptatie:**
  1. Twee runs met dezelfde bevindingen geven dezelfde sleutel.
  2. Eén extra losse kopie geeft een andere sleutel.
  3. Een andere ISO-week geeft een andere sleutel.
  4. Een resolvende kopie bij status `exited(1), running(4)` telt als destructief.
  5. Een schone root geeft exitcode 0 en geen push.
  6. De kop noemt de sha256 van het script zelf.
- **Verificatie:** de tests zijn eerst rood zonder de wijziging en daarna groen. De
  nagebootste `docker` bewijst alleen de logica van het script; het gedrag van Compose zelf
  is bewezen met de drooglopen op de hosts.

### Stap 6 — Scanner in scrum4me-docker (A1)

- **Doel:** max2 draait dezelfde scanner.
- **Raakt:** `scripts/check-compose-collision.sh` (vervangen), nieuw
  `scripts/check-compose-collision.sh.source`, een sha256-toets in `.forgejo/workflows/ci.yml`,
  en runbook `ops-agent-host-config-discipline.md` §9 (verwijzing naar git ter plekke en naar
  de plek van de hostregel).
- **Acceptatie:** de kopie is byte-gelijk aan de gemergede versie uit stap 5; de CI-toets is
  rood als de kopie wijzigt zonder de bronvermelding.
- **Afhankelijk van:** stap 5 gemerged.

### Stap 7 — Uitrol van de scanner

- **Doel:** beide hosts draaien de nieuwe versie.
- **Raakt:** scrum4me-server via `deploy/ops-agent/scripts/apply-drift-runtime.sh` (de merge
  alleen werkt de runtime-kopie niet bij); max2 via de pull van
  `/srv/scrum4me/repos/scrum4me-docker`.
- **Acceptatie:** `sha256sum` van het bestand uit `ExecStart` is op beide hosts gelijk aan de
  bron in Ops-dashboard.
- **Verificatie:** droogloop op beide hosts geeft exitcode 0 en noemt dezelfde scanner-hash.

### Stap 8 — When2Watch-procedure (D2) en observatie

- **Raakt:** in When2Watch `deploy/README.md`, `docs/runbooks/idea-219-r1-cutover.md` en
  `docs/runbooks/idea-219-r2-cutover.md`.
- **Observatie:** veertien nachten. Afsluiten van ISS-5, ISS-15 en ISS-16 met resolutie als
  het resultaat uit §1 zichtbaar is.

## 6. Increment 2 — automatische quarantaine (voorwaardelijk)

**Voorwaarde.** Na stap 4 verschijnt binnen veertien dagen opnieuw een losse compose-kopie
naast een live configbestand. Dan is aangetoond dat een regel niet volstaat.

**Schets.** Een apart script met eigen timer, vóór de nachtelijke scan. Het verplaatst een
bestand alleen als alles hieronder geldt:

1. Het staat in dezelfde map als een configbestand dat `docker compose ls` noemt.
2. De naam is de naam van dat configbestand plus een suffix.
3. Git volgt het bestand niet.
4. De ctime is ouder dan een uur. De mtime is onbruikbaar, want `cp -p` bewaart die van het
   origineel.

Het bestand gaat als tarball naar `/srv/_attic/<datum>/`, mode 600, met MANIFEST en het
terugzetcommando. Eén melding per quarantaine. Het script kent een droogloop.

Dit is een geautomatiseerde verplaatsing op productie en vraagt een staand akkoord van JP.

## 7. Beslissingen voor JP

| # | Beslissing | Voorstel |
|---|---|---|
| 1 | Akkoord op de eenmalige opruiming op beide hosts (stap 1 en 2) | Ja; het is hetzelfde recept als ISS-5 |
| 2 | Akkoord op git in de drie live mappen en op de hostregel (stap 3 en 4) | Ja |
| 3 | Bewaartermijn van de quarantaine-tars met letterlijke secret-vormige waarden | 90 dagen, daarna verwijderen |
| 4 | Ritme van de herinnering | Wekelijks |
| 5 | Onderdeel C nu bouwen of voorwaardelijk houden | Voorwaardelijk |
| 6 | Review vóór materialisatie | Eén gewone review door `mac:codex`; A en B1 raken een veiligheidscheck en productiemappen |
| 7 | Indeling bij materialisatie | Eén PBI onder scrum4me-server, gekoppeld aan ISS-5; stap 8 als story onder When2Watch |

## 8. Risico's

| Risico | Gevolg | Maatregel |
|---|---|---|
| Een secret belandt in git | Blob leesbaar voor iedereen op de host | Allowlist, `pre-commit`-hook, `.git` op 700, negatieve proef in stap 3 |
| De regel wordt niet geladen in een sessietype | Kopieën blijven komen | Praktijkproef in stap 4; observatie in stap 8; onderdeel C als vangnet |
| A2 onderdrukt een blijvend gevaar | Bevinding raakt uit beeld | Wekelijkse herinnering; de issues blijven open tot de host veertien nachten schoon is |
| Een ops-agent-flow verwacht een schone map | Flow faalt op `.git` of `.gitignore` | Verificatie in stap 3 |
| Terugdraaien van When2Watch kost een extra stap | Vertraging onder druk | Procedure in de README (D2) |
| max2 heeft geen backup van `/srv/scrum4me/compose` | Lokale git-historie verdwijnt bij schijfverlies | Aanvaard in increment 1; een remote hoort bij optie 5 |
| Een wijziging door een flow blijft ongecommit | Historie mist het waarom | De regel laat de volgende editor eerst committen |

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

## 10. Wijziging ten opzichte van het eerste advies

Het eerste advies noemde versiebeheer en automatische quarantaine samen, met als reden dat
een gedocumenteerde regel geen dag standhield. De meting nuanceert dat: de regel stond in een
runbook in een andere repo en niet in de instructies die hostsessies laden. Er is dus nog
geen bewijs dat een geladen regel faalt. Daarom is quarantaine nu voorwaardelijk.

Twee dingen zijn erbij gekomen. Onderdeel B geldt ook voor max2, dat 24 losse kopieën in de
live compose-map heeft. En de scanner heeft een rangschikkingsdefect (A3), gevonden door hem
voor het eerst op max2 te draaien.

## 11. Reviewfocus

1. A2: kan een bevinding die blijft staan langer dan een week uit beeld raken?
2. A3: geeft de nieuwe statustoets een vals alarm bij een project dat alleen `exited` is?
3. B1: sluit de allowlist met de hook elk pad naar een secret in `.git/objects` af?
4. B3 en D1: kan een stap de draaiende stack raken, of een bestand verwijderen vóór de tar is
   geverifieerd?
5. D1: breekt nog een andere procedure dan de twee cutover-runbooks op het ontbreken van
   `compose.yaml` in een oude release?
