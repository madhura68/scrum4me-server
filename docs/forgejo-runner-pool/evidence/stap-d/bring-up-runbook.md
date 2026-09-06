# Bring-up-runbook — stap D + kern van stap E (max2)

**Status:** handmatige procedure voor de operator (JP). Deze tekst is geschreven
als onderdeel van Taak 14 van
`docs/forgejo-runner-pool/implementatieplan-controller-entrypoint.md`; de
schrijver heeft **niets hiervan op max2 uitgevoerd** — geen SSH, geen deploy,
geen commando. Alles hieronder moet nog gedaan en bewezen worden.
**Datum van schrijven:** 6 september 2026.
**Reikwijdte:** `docs/forgejo-runner-pool/migratieontwerp.md` §8 stap D +
kern van stap E, zoals afgebakend in
`docs/forgejo-runner-pool/controller-entrypoint-ontwerp.md` §1–§2 (dunne
bring-up; géén assignment-nulbewijs, géén volledige poolproef — dat is stap F).
**Doelhost:** `max2` (`ssh janpeter@max2`), tweede runner
`max2-forgejo-runner-02` (migratieontwerp §5).

## 0. Wat deze runbook wel en niet dekt

Wel: het activeren van de cyclecontroller op max2 (stap D) en de kern van stap
E — één bewust groene en één bewust rode testjob, een groene scrub, een schone
`SIGTERM`-stop, en het endpoint-/isolatiebewijs uit §7.5. Niet: het pauzeren
van de bestaande runner met een volledig Forgejo-side nulbewijs voor
assigned/running jobs, de paralleltest en de reboottest (dat is stap F,
`migratieontwerp.md` §8), en niet het live per-cyclus draaien van de trustgate
(de controller leest in deze slice een bij deploy geproduceerd verdict, §6.3
van het ontwerp — dat is een bewuste, tijdelijke beperking, geen bug).

**Geen secrets in dit bestand of in Git.** Het `FORGEJO_TOKEN` in stap 2 is een
shell-omgevingsvariabele die je zelf zet uit je eigen sessie/wachtwoordmanager;
hij wordt nergens door dit bundel-bestand of door de controller weggeschreven.
Het runnertoken van de forgejo-runner-registratie is een ander, langlevend
credential dat al vóór stap D moet bestaan als
`/opt/forgejo-runner/credentials/forgejo-token`, mode `0600` — zie §1.

## 1. Vooraf — wat al klaar moet zijn

Deze runbook herhaalt de generieke uitrolstappen uit `forgejo-runner/README.md`
niet; die gelden ongewijzigd. Vink af vóór je verdergaat:

- [ ] Stap A, B en C zijn afgerond (`migratieontwerp.md` §8): preflight groen
      op max2, gedeelde bundel gevalideerd, `max2-forgejo-runner-02`
      geregistreerd in de bestaande **global** scope met de canonieke labels.
- [ ] De bundel staat op de **gepinde commit-SHA** onder `/opt/forgejo-runner/`
      op max2 (README §Uitrollen stap 2–3: kopie + `BUNDLE_COMMIT`). Controleer:
      ```sh
      ssh janpeter@max2
      cat /opt/forgejo-runner/BUNDLE_COMMIT
      ```
      en vergelijk met de SHA die je bedoelt uit te rollen.
- [ ] `runner-config.yml` is gerenderd voor **déze** host (README §Uitrollen
      stap 4, UUID van `max2-forgejo-runner-02` uit stap C):
      ```sh
      bash scripts/render-config.sh --uuid <max2-runner-uuid> \
        --labels labels.txt --policy runner-config.policy.yml \
        --out runner-config.yml
      ```
- [ ] Het runnertoken staat als `/opt/forgejo-runner/credentials/forgejo-token`,
      mode `0600`, eigendom van de effectieve runner-UID:GID, zonder afsluitende
      newline (README §Uitrollen stap 5). Dit bestand komt **nooit** uit Git.
- [ ] `.env` bestaat naast `compose.yaml` (`cp .env.example .env`, geen
      wijziging nodig — bevat alleen imagepins en caps, geen secrets).
- [ ] `bash scripts/preflight.sh --facts … --caps … --images allowed-job-images.txt`
      geeft exit 0 op max2 (§7.8-headroomgate). Faalt hij, dan is dat een
      NO-GO — ga dan niet verder met deze runbook (CLAUDE.md-hardstop: caps
      zijn gelijk op beide hosts, niet versoepelen).
- [ ] `forgejo-runner-cycle.service` is nog **niet** enabled/gestart (dat doet
      stap 5 hieronder pas, ná het trust-verdict en `controller.toml`).

Vanaf hier gaan alle commando's ervan uit dat je op max2 bent, in
`/opt/forgejo-runner`, tenzij anders vermeld.

## 2. Publiceer het trust-verdict (deploy-wrapper, ontwerp §6.3)

De controller draait de trustgate in deze slice **niet zelf** (dat zou een
geauthenticeerde credential in de controller vereisen — expliciet uitgesteld,
ontwerp §2). In plaats daarvan produceert de **operator** bij elke deploy een
gebonden verdict dat de controller alleen leest. `FORGEJO_TOKEN` hieronder is
jóuw persoonlijke Forgejo-API-token met leesrechten op repo's/collaborators/
teams — **niet** het runnerregistratietoken uit §1.

```sh
cd /opt/forgejo-runner
export FORGEJO_TOKEN='<je eigen Forgejo-token, alleen in deze shell-sessie>'
scripts/publish-trust-verdict.sh \
  --cli-py scripts/trust_scope_cli.py \
  --labels /opt/forgejo-runner/labels.txt \
  --allowlist /opt/forgejo-runner/trusted-actions-scope.yml \
  --target https://git.jp-visser.nl \
  --out /opt/forgejo-runner/trust-verdict.json
unset FORGEJO_TOKEN
```

**Waarom exact deze paden voor `--labels`/`--allowlist`:** de wrapper hasht
die twee bestanden (`sha256`) en schrijft de hash in het verdict; de
controller valideert later diezelfde binding tegen de bestanden op
`controller.toml`'s `[trust].labels_file`/`allowlist_file` (§8-schema). Gebruik
dus letterlijk de **gedeployde** paden, niet je checkout op je eigen laptop —
anders matcht `labels_sha256`/`allowlist_sha256` nooit en blijft de gate rood.

Exitcodes van de wrapper: `0` = gepubliceerd (controleer het `ok`-veld — een
inhoudelijke trustafwijking geeft `ok:false` met een reden, dat is een
terechte rode gate, geen scriptfout); `3` = de meting zelf mislukte
(ontbrekend/ongeldig token, onleesbare inventaris, niet-goedgekeurde
allowlist) — de wrapper **invalideert dan het actieve verdict fail-closed**
(`ok:false`) zodat een oud groen verdict niet stilzwijgend blijft gelden; `2`
= gebruiksfout (verkeerde argumenten).

Verifieer:

```sh
cat /opt/forgejo-runner/trust-verdict.json
```

Verwacht: `"ok":true`, een `measured_at` die overeenkomt met "nu" (unix
epoch), en de twee sha256-velden gevuld. Dit bestand bevat geen token en mag
in de evidence-map (stap 8).

## 3. Vul `controller.toml` in en valideer zonder te starten

```sh
cd /opt/forgejo-runner
cp controller.toml.example controller.toml
```

Voor max2 zijn de voorbeeldwaarden inhoudelijk al correct: `base_url`, alle
`/opt/forgejo-runner/...`-paden en de cadans-/timeoutwaarden gelden **gelijk
op beide hosts** (migratieontwerp §5 maakt alleen UUID, token en DinD-volume
per host uniek — dat zit al in `runner-config.yml`/credentials, niet in
`controller.toml`). Controleer in elk geval deze regels tegen wat je in
stap 1–2 daadwerkelijk hebt gebruikt vóór je verdergaat:

| Sleutel | Verwachte waarde op max2 |
|---|---|
| `[forgejo] base_url` | `https://git.jp-visser.nl` |
| `[dind] compose_file` | `/opt/forgejo-runner/compose.yaml` |
| `[dind] project` | `forgejo-runner` (moet gelijk zijn aan het impliciete Compose-projectnaam — zie waarschuwing hieronder) |
| `[dind] marker_path` | `/opt/forgejo-runner/state/cycle-op.marker` (wordt automatisch aangemaakt; geen losse `mkdir` nodig) |
| `[runner] allowed_images_file` | `/opt/forgejo-runner/allowed-job-images.txt` |
| `[trust] verdict_path` | `/opt/forgejo-runner/trust-verdict.json` (het bestand uit stap 2) |
| `[trust] labels_file` / `allowlist_file` | exact dezelfde paden die je in stap 2 aan `--labels`/`--allowlist` gaf |

**Waarschuwing over het Compose-projectnaam.** De controller roept overal
`docker compose -f <compose_file> -p <project>` aan (dus met een expliciete
`-p forgejo-runner`). Als jij in stap 5 handmatig `docker compose up -d dind`
draait **zonder** `-p`, valt Compose terug op de mapnaam van de working
directory als impliciet projectnaam. Zolang de bundel exact op
`/opt/forgejo-runner/` staat is dat toevallig ook `forgejo-runner` — laat het
zo; verplaats de bundel niet naar een andere mapnaam zonder ook
`controller.toml`'s `[dind] project` en je handmatige `-p` gelijk te trekken,
anders start de controller een eigen, ongerelateerde DinD naast die van de
operator.

Valideer de invulling zonder de loop te starten:

```sh
python3 scripts/cycle_runtime.py --config controller.toml --check
echo "exit=$?"
```

Verwacht `exit=0` en geen traceback. Een ontbrekende sleutel geeft een nette
`config-fout: controller.toml mist <sectie>.<sleutel>` op stderr met exit `2` —
dat is dan een echte omissie in `controller.toml`, geen bug in dit bundel.

## 4. Sanity: bevestig entrypoint + resulterende argv (ontwerp §6.2)

Dit is geen formaliteit. `compose.yaml`'s `runner`-service heeft **geen**
`entrypoint:`-sleutel, en de gepinde image heeft `Entrypoint=null` — dat
betekent dat de `command:` **letterlijk** de argv bepaalt, en Docker resolveert
het eerste element via `$PATH` in de container. De gepinde image heeft
`Cmd=["/bin/forgejo-runner"]` (zie `evidence/stap-a/scrum4me-server/images.json`),
maar die wordt **genegeerd** zodra `compose.yaml` een eigen `command:` geeft.

Daarom moet `command:` in de `runner`-service van `compose.yaml` het **volledige
binary-pad** bevatten: `["/bin/forgejo-runner", "one-job", "--wait"]`.
Een bare `["one-job", "--wait"]` laat Docker rechtstreeks een executable `one-job`
via `$PATH` zoeken (er is geen shell tussen), wat faalt omdat `one-job`
niet in `$PATH` bestaat — exit 127, nog voordat forgejo-runner start.

Dit is nu **correct toegepast** in `compose.yaml`. Bevestig de sanity met:

```sh
RUNNER_IMAGE="$(. ./.env; echo "$RUNNER_IMAGE")"
docker inspect --format 'Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}}' "$RUNNER_IMAGE"
```

Verwacht: `Entrypoint=null Cmd=["/bin/forgejo-runner"]`.

Bewijs vervolgens de **resulterende** argv met een losse, onschadelijke
aanroep (raakt geen DinD, netwerk of config, dus veilig om los te draaien):

```sh
docker run --rm "$RUNNER_IMAGE" /bin/forgejo-runner one-job --wait
echo "exit=$?"
```

Verwacht: `Error: one-job is only supported with a single connection, but
0 connections are configured`, exit `1`. Dat bewijst dat forgejo-runner
zelf wél `one-job --wait` accepteert zodra het binary daadwerkelijk wordt
aangeroepen.

Dezelfde controle draait geautomatiseerd in de suite:
`tests/test_compose_runner_exec.bats` rendert het échte `command:` via
`docker compose config` en voert het uit tegen de gepinde image uit
`.env.example` (skipt zonder docker-daemon). De statische
`test_compose_contract.bats` grept alleen de YAML en ving dit niet.

**Waarom het binary-pad verplicht is:**
- De image heeft geen `Entrypoint`, dus Docker resolveert het eerste element van
  `command` via `$PATH` in de container.
- Er bestaat geen bestand genaamd `one-job` in `$PATH` (alleen `/bin/forgejo-runner`).
- Zonder het volledige pad `/bin/forgejo-runner` zou Docker de container starten
  met `exec: "one-job": executable file not found in $PATH`, exit 127 — vóórdat
  de container ook maar één line forgejo-runner-code uitvoert.
- Met het pad: `docker run --rm "$RUNNER_IMAGE" /bin/forgejo-runner one-job --wait`
  slaagt, en `/bin/forgejo-runner` handelt vervolgens `one-job --wait` af (of geeft
  een inhoudelijke foutmelding als het config is).

**Dit is dus de correcte, werkende invulling.** Leg de output van beide `docker
inspect`/`docker run`-commando's vast (stap 8, `evidence/stap-d/docker-inspect-runner-image.txt`),
zodat je kunt bewijzen dat je deze sanity hebt uitgevoerd.

## 5. DinD omhoog, controller-unit starten, runner online bevestigen (stap D)

```sh
cd /opt/forgejo-runner
docker compose up -d dind
docker compose ps                       # dind: Up (healthy) — wacht op de 30s-startperiode + 6 retries (compose.yaml healthcheck)
```

Start de controller pas als `dind` `healthy` is:

```sh
sudo systemctl daemon-reload            # als de unit nieuw is op deze host
sudo systemctl enable --now forgejo-runner-cycle.service
sudo systemctl status forgejo-runner-cycle.service --no-pager
sudo journalctl -u forgejo-runner-cycle.service -f
```

Verwachte logvolgorde (ontwerp §5/§5.1/§6.1): `SOURCE_WAIT` bij koude start →
na twee bevestigde `READY`-probes (≥ 5 s uiteen, elke 30 s-cadans) én groene
gates (`trust-verdict` groen uit stap 2, DinD gezond) → een scrub (`cyclus:
scrub ok=True`, want `clean_proven` is bij programmastart altijd `False`) →
`cyclus: runner gestart`. Dat laatste startte
`docker compose --profile cycle run --rm runner`; de container verschijnt kort
in `docker compose ps --profile cycle`.

Bevestig in de Forgejo-beheerinterface (Site Administration → Actions →
Runners) dat **`max2-forgejo-runner-02`** online staat en idle wacht op één
job (`one-job --wait`). Wijzig of herstart hierbij geen enkele bestaande
productie-hostservice (CLAUDE.md-hardstop) — dit raakt alleen de nieuwe
DinD/runner/controller-stack.

## 6. Smoke: één groene + één rode job, scrub, terug naar `WAITING` (kern stap E)

Beide runners delen dezelfde labels (§7.4/§7.7 migratieontwerp); om te
garanderen dat de smoke-jobs daadwerkelijk op max2 landen, pauzeer je
tijdelijk de bestaande `scrum4me-server`-runner in de Forgejo-beheerinterface
(Runners → Pause) totdat hij idle is, en hervat hem na de twee smoke-jobs.
Dit is een lichte, omkeerbare voorzorg voor déze test — het volledige
Forgejo-side nulbewijs voor assigned/running jobs en de paralleltest horen bij
stap F en vallen buiten deze runbook (ontwerp §2 "niet-doelen").

Gebruik een losse, uitsluitend-voor-deze-test bedoelde workflow (nieuw repo of
een bestaand testrepo met Actions aan en het gedeelde label in de allowlist),
`workflow_dispatch` zodat jij bepaalt wanneer hij vuurt:

```yaml
# .forgejo/workflows/smoke-green.yml
on: [workflow_dispatch]
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: echo "smoke groen"; exit 0
```

```yaml
# .forgejo/workflows/smoke-red.yml
on: [workflow_dispatch]
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: echo "smoke rood"; exit 1
```

Voor **elke** run, in deze volgorde:

1. Vuur de workflow af (Forgejo UI: Actions → workflow → Run workflow).
2. Volg `sudo journalctl -u forgejo-runner-cycle.service -f`: de zichtbare
   toestand blijft `WAITING` tijdens de job (de dunne slice bevestigt
   `job_accepted` nog niet, ontwerp §7.3) tot de runnercontainer eindigt; dan
   `cyclus: runner exit rc=0` → `cyclus: scrub ok=True` → terug naar
   `WAITING`.
3. Controleer in de Forgejo-UI de **terminale workflowstatus**: groen voor de
   eerste run, rood voor de tweede. Beide moeten in de journal `runner exit
   rc=0` en `scrub ok=True` laten zien — het runnerproces zelf slaagt in
   beide gevallen (`one-job --wait` rondt de job af, ongeacht of de job zélf
   slaagt); alleen het Forgejo-side workflowresultaat verschilt (ontwerp §7.3,
   migratieontwerp §8 stap E).
4. Bevestig dat de runner ná de scrub weer **online/idle** in Forgejo staat
   vóór je de volgende job start.

Als een van beide runs een andere `runner exit rc`, een `scrub ok=False`, of
een controller die naar `QUARANTINED`-gedrag lijkt te gaan laat zien: stop,
leg de journal vast, en behandel dat als een blokkerende bevinding — niet als
iets om te forceren voorbij scrub-falen (`clean_proven` blijft dan bewust
`False` tot een geslaagde scrub, ontwerp §5.2/§6.1 stap 8).

Hervat de bestaande `scrum4me-server`-runner in Forgejo zodra beide smokejobs
klaar zijn.

## 7. Nette stop (`SIGTERM` via `systemctl`)

De unit heeft `KillSignal=SIGTERM` en `TimeoutStopSec=300`; `systemctl stop`
ís dus de `SIGTERM`-route uit ontwerp §9 — er is geen aparte `kill -TERM` voor
nodig.

```sh
sudo systemctl stop forgejo-runner-cycle.service
sudo systemctl status forgejo-runner-cycle.service --no-pager
sudo systemctl show forgejo-runner-cycle.service -p ExecMainStatus -p Result
sudo journalctl -u forgejo-runner-cycle.service -n 80 --no-pager
```

Verwacht: `ExecMainStatus=0`, `Result=success`. Doe dit met **geen** actieve
job (schone stop, `§9` eerste tak); als er toevallig net een job liep, wacht
dan op `child_stop_grace` (≈ 200 s) en controleer daarna dezelfde velden.

Bevestig géén achtergebleven toestand:

```sh
docker compose ps --profile cycle runner        # verwacht: leeg, geen runnercontainer
ls -la /opt/forgejo-runner/state/cycle-op.marker 2>&1   # verwacht: "No such file or directory"
```

Een aanwezige marker na een schone stop wijst op een onderbroken pull/scrub
(ontwerp §6.4) — dat is een diagnostisch signaal, geen losstaande fout: de
**volgende** start herstelt hem automatisch (DinD-herstart + volledige scrub
vóór een nieuwe launch), maar leg het wel vast als het gebeurt.

## 8. Bewijs vastleggen onder `evidence/stap-d/` en `evidence/stap-e/`

Kopieer bewijs van max2 terug naar deze repo (niet andersom — de bundel blijft
canoniek in `scrum4me-server`, CLAUDE.md-hardstop). Voorgestelde bestanden,
naar het voorbeeld van `evidence/stap-a/`:

| Bestand | Inhoud |
|---|---|
| `evidence/stap-d/docker-inspect-runner-image.txt` | Output van stap 4: `docker inspect`-regel + beide `docker run`-uitkomsten (pass of fail) |
| `evidence/stap-d/trust-verdict-published.json` | Kopie van `/opt/forgejo-runner/trust-verdict.json` (geen secrets: alleen `ok`/`measured_at`/target/hashes) |
| `evidence/stap-d/runner-online-forgejo.txt` (of screenshot) | Bewijs dat `max2-forgejo-runner-02` online/idle staat na stap 5 |
| `evidence/stap-d/systemd-status.txt` | `systemctl status` + `journalctl`-uittreksel van de start (stap 5) |
| `evidence/stap-e/smoke-green.txt` | Journal-uittreksel + Forgejo-run-URL/terminale status van de groene job |
| `evidence/stap-e/smoke-red.txt` | Idem voor de rode job — inclusief `runner exit rc=0` én `scrub ok=True` ondanks de rode workflowuitslag |
| `evidence/stap-e/endpoints.md` | De drie endpoints uit §7.5 live bevestigd: `tcp://127.0.0.1:2375` binnen DinD (healthcheck), `tcp://dind:2375` vanuit de runnercontainer, `tcp://dind.internal:2375` vanuit een job-/stepcontainer (bijv. een `docker info` teststap in de smoke-workflow) |
| `evidence/stap-e/no-host-listeners.txt` | `ss -ltn \| grep -E ':(2375\|2376)'` → leeg; of de ingebouwde check via `bash scripts/verify-stack.sh <commit> <bundelhash>` (print `isolatie: OK` naast commit-/hashdrift) |
| `evidence/stap-e/dind-isolation.md` | Bewijs dat een jobcontainer de hostcontainers niet ziet: geen `/var/run/docker.sock`-mount in `docker inspect` van de runnercontainer; `docker -H tcp://dind:2375 ps` vanuit de job ziet alleen DinD-lokale containers |
| `evidence/stap-d/clean-stop.txt` | Output van stap 7: `ExecMainStatus`/`Result`, lege `docker compose ps`, afwezige marker |

Scan bewijsbestanden vóór je ze commit met `bash scripts/secret-scan.sh
<bestanden>` (expliciete argumenten, want deze staan niet al gestaged) —
dezelfde gate die al op de bundel draait. Commit de evidence apart van deze
runbook, met een duidelijke boodschap per stap (net als bij stap A/B,
`evidence/stap-a/afsluitgate.md`).

## 9. Als iets misgaat — terugdraaien en melden

- **Stap 4 faalt** (argv-sanity): niet verder, geen `systemctl enable`. Meld
  aan JP; fix hoort in `compose.yaml` in de `scrum4me-server`-repo, met een
  nieuwe commit + review — niet als hostpatch (§4 hierboven).
- **Preflight of headroomgate faalt** (§1): geen mutatie; dat is een
  architectuur-/capaciteitsbeslissing voor JP, geen scriptfout om te omzeilen.
- **Trust-verdict blijft `ok:false`** (stap 2): de controller start dan
  terecht geen runner (`gates_groen=False`); dat is fail-closed gedrag, geen
  bug — herstel de onderliggende trustafwijking of het token, niet de gate.
- **Wil je terug naar de uitgangssituatie:** stop en disable de unit
  (`forgejo-runner/README.md` §Terugdraaien), verwijder alleen de runner- en
  DinD-containers van déze stack, laat het volume
  `forgejo-runner-dind-data` staan voor onderzoek. Herstart nooit de
  host-Dockerdaemon en raak de bestaande `scrum4me-server`-runner niet aan.
- **Elke onverwachte hostimpact** (een productieservice die omvalt, een
  claim die verdwijnt): registreer dat met `create_issue` op het `max2`- of
  `scrum4me-server`-product met een fingerprint `max2:<component>:<kern>`,
  zoals voorgeschreven in `max2/CLAUDE.md` §"Infra-issues melden" — niet
  stilzwijgend negeren.

## Checklist (samenvatting)

| # | Wat | Groen betekent |
|---|---|---|
| 1 | Vooraf (stap A/B/C, bundel op SHA, token, preflight) | alle vinkjes in §1 |
| 2 | Trust-verdict | `trust-verdict.json` heeft `"ok":true`, verse `measured_at` |
| 3 | `controller.toml` | `--check` geeft exit 0 |
| 4 | Argv-sanity (§6.2) | `docker run --rm $RUNNER_IMAGE one-job --wait` bereikt forgejo-runner (geen `$PATH`-fout) |
| 5 | Stap D | `max2-forgejo-runner-02` online/idle in Forgejo |
| 6 | Kern stap E | groene + rode job: beide `runner exit rc=0`, beide `scrub ok=True`, juiste Forgejo-terminale status, terug naar `WAITING` |
| 7 | Nette stop | `ExecMainStatus=0`, geen runnercontainer, geen marker |
| 8 | Bewijs | alle bestanden uit de tabel in §8 aanwezig en secret-scan-schoon |
