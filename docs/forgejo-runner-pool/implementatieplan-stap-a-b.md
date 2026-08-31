# Forgejo Runner tweemachinepool — implementatieplan stap A + B

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stap A (alles meten en bewijzen zonder de live runner aan te raken) en stap B (de gedeelde, digest-gepinde bundel bouwen en valideren) volledig uitvoerbaar maken, zodat stap C tot en met H daarna op echte meetwaarden kunnen worden gepland.

**Architecture:** Stap A is uitsluitend read-only: scripts draaien via SSH op `scrum4me-srv` en `max2`, schrijven hun uitvoer naar bewijsbestanden in de repo, en muteren niets aan de draaiende stack. Stap B bouwt daaruit de gedeelde bundel: Compose, labels, policy, de Python-cyclecontroller met zijn unittestsuite, de scrubroutine, de systemd-unit en de verificatiescripts. Beide stappen leveren gates die groen moeten zijn voordat stap C mag beginnen.

**Tech Stack:** Ubuntu 26.04 LTS, systemd 259, Docker Engine 29.7.2, Forgejo 15.0.2, Forgejo Runner 12.10.1, Docker-in-Docker, Python 3.14 (stdlib `unittest`, geen externe dependencies), Bash met `shellcheck` en `bats`, `jq`, `curl`, `tea`.

**Spec:** [docs/forgejo-runner-pool/migratieontwerp.md](migratieontwerp.md) — het goedgekeurde migratieontwerp (delta-review R12, ronde 3, GO). Dit plan implementeert uitsluitend §8 stap A en stap B; iedere taak verwijst naar de secties die haar binden. Executors lezen beide documenten.

---

## Gemeten omgevingsfeiten

Gemeten op 2026-08-31 vanaf `mac` via Tailscale-SSH. Deze waarden zijn **niet** gekopieerd uit het ontwerp maar op de hosts gemeten; stap A meet ze opnieuw en legt ze als bewijs vast. Wijkt een waarde af bij uitvoering, dan is dat een bevinding en geen reden om het plan aan te passen zonder overleg.

| Feit | `scrum4me-server` | `max2` |
|---|---|---|
| SSH-doel | `janpeter@scrum4me-srv` | `janpeter@max2` |
| Tailscale-IP | `100.118.195.120` | `100.102.8.64` |
| `hostname` | `scrum4me-server` | `max2` |
| OS | Ubuntu 26.04 LTS | Ubuntu 26.04 LTS |
| systemd | 259 (259.5-0ubuntu3.4) | 259 (259.5-0ubuntu3.4) |
| Docker Engine | 29.7.2 | 29.7.2 |
| `DockerRootDir` | `/var/lib/docker` | `/var/lib/docker` |
| vCPU | 8 | 28 |
| MemTotal | 15,0 GiB | 30,6 GiB |
| Python | 3.14.4, stdlib `unittest` beschikbaar | 3.14.4, stdlib `unittest` beschikbaar |
| `sudo -n` | zonder wachtwoord | zonder wachtwoord |
| Containers totaal (`docker ps -aq`) | 23 | 19 (11 draaiend, 8 gestopt) |

Let op: de Tailscale-naam van de serverhost is **`scrum4me-srv`**, terwijl `hostname` **`scrum4me-server`** teruggeeft. Gebruik `scrum4me-srv` in SSH-commando's en `scrum4me-server` als hostnaam in bewijsbestanden en configuratie.

Relevante containers op `scrum4me-server`, gemeten met `docker ps -a`:

| Container | Image | Status bij meting |
|---|---|---|
| `scrum4me-forgejo-runner` | `code.forgejo.org/forgejo/runner:12` | Up 6 hours |
| `scrum4me-forgejo-dind` | `docker:dind` | Up 10 days |
| `scrum4me-forgejo` | `codeberg.org/forgejo/forgejo:15.0.2` | Up 10 days |

Beide runner-images hangen aan een **mutable tag** (`runner:12`, `docker:dind`). Dat bevestigt de eis uit §4 van het ontwerp: stap A legt de actuele `RepoDigests` vast en stap B pint op digest. `max2` heeft geen runner-, DinD- of Forgejo-container; dat is de verwachte uitgangssituatie.

Lokale toolversies op `mac` waar de scripts worden ontwikkeld en getest: Python 3.14.6, `shellcheck`, `bats` 1.14.0, `jq` 1.7.1, `docker` 29.7.2, `tea` 0.14.1. **`pytest` is niet geïnstalleerd** — de controllertests gebruiken daarom uitsluitend de stdlib `unittest`, zodat ze zonder installatie op mac én op beide hosts draaien. `yq` is niet aanwezig; YAML-verwerking gaat via Python.

---

## Global Constraints

Deze eisen binden **iedere** taak in dit plan. Waarden zijn letterlijk overgenomen uit het ontwerp.

- **Stap A muteert niets aan de draaiende stack.** Geen `docker run`, `stop`, `rm`, `pull`, `prune`, `exec` met bijwerking, geen bestandswijziging op de hosts, geen herstart van welke service dan ook. Alleen lezen, inspecteren en meten. (§8 stap A)
- **Eén begrensde uitzondering: de ephemeral-spike (Task 4).** Die maakt via de admin-API één runnerrecord aan en verwijdert het in dezelfde taak. Voorwaarden, alle vier hard: het record draagt uitsluitend een uniek canary-label en nooit een gedeeld productielabel, zodat geen productiejob erop kan landen; er wordt geen runnerproces mee gestart; het record wordt in dezelfde taak verwijderd en die verwijdering wordt bewezen; de bestaande runner wordt niet aangeraakt. Deze uitzondering geldt uitsluitend voor Task 4 en voor niets anders in stap A.
- **Host-Docker blijft ongemoeid.** Geen APT-repository toevoegen, geen Docker- of containerd-pakket installeren of upgraden, `/etc/docker/daemon.json` niet wijzigen, de Docker-daemon niet herstarten, geen hostbrede `docker system prune`. (§7.1)
- **De bestaande runner op `scrum4me-server` blijft in stap A en B onaangeraakt.** De eerste deployment is `max2`, en die valt buiten dit plan. (§7.2)
- **Runner 12.10.1** met exact dezelfde tag én registry-gevalideerde manifestdigest; **DinD** met exact dezelfde tag én digest als de werkende installatie. Een lokale image-ID of een tag als `runner:12` is niet voldoende reproduceerbaar. (§4)
- **`capacity: 1`** per runner, **exact één** `server.connections`-verbinding per runnerconfig, opdracht `one-job --wait`. (§4, §7.9)
- **Geen host-Docker-socket, geen gepubliceerde 2375/2376, geen gedeelde DinD of gedeeld DinD-volume.** `privileged: true` uitsluitend op DinD; jobcontainers nooit privileged. (§7.5, §7.6)
- **Endpointmatrix is bindend:** DinD-container zelf `tcp://127.0.0.1:2375`; runnercontainer `tcp://dind:2375`; job-/stepcontainer `tcp://dind.internal:2375`. Geen enkele check valt terug op `/var/run/docker.sock`. (§7.5)
- **Secrets nooit in Git**, niet in `runner-config.yml`, `.env`, Compose `command`, shellhistory of containermetadata. Het actieve token leeft uitsluitend als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`, eigendom van de effectieve runner-UID:GID. Tokenwaarden worden nooit gelogd. (§6, §7.3)
- **`FORGEJO_TOKEN` staat in `~/.zshenv` op `mac`.** Gebruik hem via `curl --config` met process-substitution zodat hij niet in `argv` of in de shellhistory belandt. Waarde nooit printen.
- **De bundel is canoniek in deze repo.** `max2` krijgt geen kopie. Beide hosts rollen uit vanaf dezelfde commit-SHA. (§6.1)
- **Deployment nooit via een Forgejo Actions-workflow.** Uitrol gebeurt handmatig of via SSH vanaf `mac`. (§6.1)
- **Caps zijn gelijk op beide hosts.** Lagere caps op alleen `max2` zijn niet toegestaan. (§7.8)
- **Beweer niets over de boom of de hosts dat niet is gemeten.** Iedere bewering in een bewijsbestand verwijst naar het commando dat haar heeft opgeleverd.

---

## Interpretatie van §6.1 over bewijsopslag

§6.1 belegt `hosts/scrum4me-server/` bij stap G en `evidence/` in de `max2`-repo bij stap A en E. Stap A produceert echter ook bewijs over `scrum4me-server` zelf, en `hosts/scrum4me-server/` bestaat dan nog niet.

Dit plan lost dat zo op, zonder van §6.1 af te wijken:

- **Gedeeld bewijs dat input is voor de bundel** — imagedigests, canonieke labels, `T_requeue`, de trust-allowlist, de berekende caps — gaat naar `docs/forgejo-runner-pool/evidence/stap-a/` in deze repo. Het is bundelinput, geen host-overlay.
- **Hostspecifiek bewijs over `scrum4me-server`** gaat naar dezelfde map, met `scrum4me-server-` als bestandsprefix, tot `hosts/scrum4me-server/` in stap G ontstaat.
- **Hostspecifiek bewijs over `max2`** gaat naar `evidence/stap-a/` in de **`max2`-repo**, precies zoals §6.1 voorschrijft.

---

## File Structure

Alles onder `forgejo-runner/` is de gedeelde bundel uit §6 en wordt byte-identiek naar beide hosts uitgerold.

| Bestand | Verantwoordelijkheid | Taak |
|---|---|---|
| `forgejo-runner/scripts/lib/readonly.sh` | Whitelist van read-only Docker-subcommando's; weigert iedere mutatie. Bron van de stap-A-garantie | 1 |
| `forgejo-runner/scripts/capture-current.sh` | Read-only inventarisatie van de live stack op een host: images, digests, Compose, netwerken, volumes, health, DinD-dataomvang | 2 |
| `forgejo-runner/scripts/capture-forgejo-records.sh` | Read-only inventarisatie via de Forgejo-API: runnerrecords, scope, labels, online/busy | 3 |
| `forgejo-runner/scripts/spike-ephemeral.sh` | Meet feitelijk of en hoe ephemeral registratie werkt op deze instance; levert het bewijs voor de delta-review | 4 |
| `forgejo-runner/scripts/capture-clock-skew.sh` | NTP-/chrony-status en gemeten wandklokskew tegen de Forgejo-`Date`-header | 5 |
| `forgejo-runner/scripts/verify-trust-scope.sh` | Entry point van de trustscope-gate zoals §6 hem benoemt | 6 |
| `forgejo-runner/scripts/trust_scope.py` | Inventarisatie- en classificatielogica van de trustscope, zonder netwerk-IO | 6 |
| `forgejo-runner/scripts/trust_scope_cli.py` | Netwerkclient en CLI rond `trust_scope.py`; vertaalt het oordeel naar exitcodes | 6 |
| `forgejo-runner/trusted-actions-scope.yml` | De goedgekeurde allowlist die de gate toetst | 6 |
| `forgejo-runner/scripts/pick_heaviest_workflow.py` | Kiest de zwaarste representatieve workflow uit historische runs; IO-vrij | 7 |
| `forgejo-runner/scripts/pick-heaviest-workflow.py` | CLI eromheen die de runs ophaalt via de Forgejo-API | 7 |
| `forgejo-runner/scripts/measure-workload.sh` | Meet iedere vijf seconden CPU, geheugen, PID's en `MemAvailable` tijdens de zwaarste workflow; legt jobduur vast | 7 |
| `forgejo-runner/scripts/capture-host-facts.sh` | vCPU, geheugen, laagste `MemAvailable`, vrije ruimte en inodes op `DockerRootDir` | 8 |
| `forgejo-runner/scripts/compute_caps.py` | Berekent de caps volgens §7.8 uit de meetreeks | 9 |
| `forgejo-runner/scripts/preflight.sh` | De vier harde drempels uit §7.8; stopt vóór iedere mutatie | 10 |
| `forgejo-runner/scripts/forgejo_runner_cycle.py` | De cyclecontroller: toestandsmachine, eventloop, readinessclassificatie, fence, watchdog, maintenance, cyclus | 11–15 |
| `forgejo-runner/tests/test_cycle_*.py` | De unittestsuite van de controller; tevens het stub-/testharnas dat stap A eist | 11–15 |
| `forgejo-runner/compose.yaml` | Runner- en DinD-services, netwerken, volume, healthchecks, logging, limieten | 16 |
| `forgejo-runner/.env.example` | Uitsluitend imagepins en niet-geheime waarden | 16 |
| `forgejo-runner/labels.txt` | Canonieke geordende labellijst, digest-gepind | 16 |
| `forgejo-runner/allowed-job-images.txt` | Registry-gevalideerde digests die de scrub mag behouden | 16 |
| `forgejo-runner/scripts/resolve-digests.sh` | Zet een mutable tag om in een registry-gevalideerde digest | 16 |
| `forgejo-runner/runner-config.policy.yml` | Capacity, timeouts en DinD-policy | 17 |
| `forgejo-runner/scripts/render-config.sh` | Maakt de hostconfig uit basisconfig, policy, UUID en labels | 17 |
| `forgejo-runner/scripts/scrub-dind.sh` | Fenced cleanup binnen uitsluitend de eigen DinD | 18 |
| `forgejo-runner/forgejo-runner-cycle.service` | De systemd-unit die de controller als enige eigenaar van de runnerlevenscyclus draait | 19 |
| `forgejo-runner/scripts/bundle-hash.sh` | Canonieke hash over de bundelbestanden; de mechanische invulling van "byte-identiek" | 20 |
| `forgejo-runner/scripts/verify-stack.sh` | Health, poorten, config, labels, isolatie, `BUNDLE_COMMIT` en bundelhash | 20 |
| `forgejo-runner/scripts/secret-scan.sh` | Scant staged inhoud op tokenpatronen en secretbestandsnamen | 21 |
| `forgejo-runner/scripts/install-git-hooks.sh` | Installeert de scan als pre-commit hook in een werkboom | 21 |
| `forgejo-runner/README.md` | Uitrol-, rollback- en upgradeprocedure | 22 |

Testbestanden voor de shellscripts staan naast de bundel in `forgejo-runner/tests/` als `bats`-bestanden met een nep-`docker` en nep-`curl` op `PATH`, zodat geen enkele test een echte host of registry raakt.

---

## Stap A — meten en bewijzen

Stap A raakt de draaiende stack niet aan. De enige schrijfactie op een host is het neerzetten van de scripts in een tijdelijke map onder `/tmp`; alle uitvoer komt terug naar `mac` en landt als bewijsbestand in de repo. Dat is expliciet toegestaan en verandert niets aan runner, DinD, Docker of Forgejo.

### Task 1: Read-only guard

De garantie "stap A muteert niets" moet mechanisch zijn, niet een belofte. Iedere Docker-aanroep in stap A loopt via deze guard.

**Files:**
- Create: `forgejo-runner/scripts/lib/readonly.sh`
- Test: `forgejo-runner/tests/test_readonly_guard.bats`

**Interfaces:**
- Consumes: niets
- Produces: `ro_docker <args...>` — voert `docker` uit als het subcommando read-only is, en geeft anders exitcode `64` met een melding op stderr. `ro_docker_is_allowed <woord1> <woord2>` — retourneert 0 als de combinatie is toegestaan.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_readonly_guard.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/docker" <<'EOS'
#!/usr/bin/env bash
echo "FAKE-DOCKER $*"
EOS
  chmod +x "$FAKE_BIN/docker"
  PATH="$FAKE_BIN:$PATH"
  source "$REPO_ROOT/forgejo-runner/scripts/lib/readonly.sh"
}

@test "laat docker ps door" {
  run ro_docker ps --format '{{.Names}}'
  [ "$status" -eq 0 ]
  [[ "$output" == FAKE-DOCKER\ ps* ]]
}

@test "laat docker image inspect door" {
  run ro_docker image inspect busybox
  [ "$status" -eq 0 ]
}

@test "laat system df door" {
  run ro_docker system df
  [ "$status" -eq 0 ]
}

@test "weigert system prune" {
  run ro_docker system prune -f
  [ "$status" -eq 64 ]
  [[ "$output" == *"geweigerd"* ]]
}

@test "weigert rm, stop, pull en exec" {
  for sub in rm stop pull exec restart kill; do
    run ro_docker "$sub" iets
    [ "$status" -eq 64 ]
  done
}

@test "weigert een leeg subcommando" {
  run ro_docker
  [ "$status" -eq 64 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_readonly_guard.bats`
Expected: FAIL — `readonly.sh` bestaat nog niet, `source` mislukt.

- [ ] **Step 3: Schrijf de implementatie**

```bash
# forgejo-runner/scripts/lib/readonly.sh
# Read-only guard voor stap A van het runnerpool-migratieontwerp.
# Iedere Docker-aanroep in stap A loopt hierlangs. Alles wat niet expliciet
# read-only is, wordt geweigerd met exitcode 64.

ro_docker_is_allowed() {
  local one="${1:-}" two="${2:-}"
  case "$one $two" in
    "image inspect"|"image ls"|"image history"|\
    "volume ls"|"volume inspect"|\
    "network ls"|"network inspect"|\
    "container inspect"|"container ls"|\
    "system df"|"compose config"|"manifest inspect")
      return 0 ;;
  esac
  case "$one" in
    ps|images|inspect|info|version|logs|stats|top|port|diff)
      return 0 ;;
  esac
  return 1
}

ro_docker() {
  if ! ro_docker_is_allowed "${1:-}" "${2:-}"; then
    printf 'readonly-guard: geweigerd: docker %s\n' "$*" >&2
    return 64
  fi
  docker "$@"
}
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_readonly_guard.bats`
Expected: PASS — 6 tests, 0 failures.

- [ ] **Step 5: Lint**

Run: `shellcheck -x forgejo-runner/scripts/lib/readonly.sh`
Expected: geen bevindingen.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/lib/readonly.sh forgejo-runner/tests/test_readonly_guard.bats
git commit -m "feat(stap-a): read-only guard voor Docker-aanroepen"
```

---

### Task 2: Inventarisatie van de live stack

Legt vast wat er nu draait op `scrum4me-server`, inclusief de digests die stap B gaat pinnen en de omvang van de inner-DinD-data. Bindt §8 stap A en §4.

**Files:**
- Create: `forgejo-runner/scripts/capture-current.sh`
- Test: `forgejo-runner/tests/test_capture_current.bats`

**Interfaces:**
- Consumes: `ro_docker` uit Task 1
- Produces: een bewijsmap met per artefact één bestand — `images.json`, `containers.json`, `networks.json`, `volumes.json`, `dind-usage.txt`, `runner-registration.json` (zonder tokenwaarde). Stap B leest `images.json` voor de digests en `runner-registration.json` voor de canonieke labels.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_capture_current.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/capture-current.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/docker" <<'EOS'
#!/usr/bin/env bash
case "$1 $2" in
  "image inspect")
    echo '[{"Id":"sha256:aaa","RepoTags":["code.forgejo.org/forgejo/runner:12"],"RepoDigests":["code.forgejo.org/forgejo/runner@sha256:1111"]}]' ;;
  "container inspect")
    echo '[{"Name":"/scrum4me-forgejo-runner","State":{"Health":{"Status":"healthy"}},"Mounts":[{"Type":"volume","Name":"anon123","Source":"/var/lib/docker/volumes/anon123/_data","Destination":"/data"}]}]' ;;
  "volume ls") echo 'anon123' ;;
  "network ls") echo 'bridge' ;;
  *) echo "{}" ;;
esac
EOS
  chmod +x "$FAKE_BIN/docker"
  cat > "$FAKE_BIN/sudo" <<'EOS'
#!/usr/bin/env bash
# -n wegstrippen en de rest gewoon uitvoeren
[ "$1" = "-n" ] && shift
exec "$@"
EOS
  chmod +x "$FAKE_BIN/sudo"
  cat > "$FAKE_BIN/du" <<'EOS'
#!/usr/bin/env bash
echo "129922760704	$3"
EOS
  chmod +x "$FAKE_BIN/du"
  PATH="$FAKE_BIN:$PATH"
}

@test "schrijft alle verwachte bewijsbestanden" {
  out="$BATS_TEST_TMPDIR/evidence"
  run bash "$SCRIPT" --runner scrum4me-forgejo-runner --dind scrum4me-forgejo-dind --out "$out"
  [ "$status" -eq 0 ]
  for f in images.json containers.json networks.json volumes.json dind-usage.txt; do
    [ -f "$out/$f" ] || { echo "ontbreekt: $f"; false; }
  done
}

@test "legt de RepoDigest vast en niet alleen de tag" {
  out="$BATS_TEST_TMPDIR/evidence"
  bash "$SCRIPT" --runner scrum4me-forgejo-runner --dind scrum4me-forgejo-dind --out "$out"
  grep -q 'sha256:1111' "$out/images.json"
}

@test "faalt zonder --out" {
  run bash "$SCRIPT" --runner a --dind b
  [ "$status" -ne 0 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_capture_current.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/capture-current.sh
# Read-only inventarisatie van de live runnerstack. Draait OP de host.
# Muteert niets: schrijft uitsluitend naar de opgegeven uitvoermap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

RUNNER="" ; DIND="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --runner) RUNNER="$2" ; shift 2 ;;
    --dind)   DIND="$2"   ; shift 2 ;;
    --out)    OUT="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$RUNNER" ] && [ -n "$DIND" ] && [ -n "$OUT" ] || {
  printf 'gebruik: capture-current.sh --runner NAAM --dind NAAM --out MAP\n' >&2
  exit 2
}

mkdir -p "$OUT"

# Images met hun RepoDigests. De tag alleen is niet reproduceerbaar (Global Constraints).
ro_docker image inspect \
  "$(ro_docker container inspect "$RUNNER" --format '{{.Config.Image}}')" \
  "$(ro_docker container inspect "$DIND" --format '{{.Config.Image}}')" \
  > "$OUT/images.json" 2>/dev/null \
  || ro_docker image inspect "$RUNNER" "$DIND" > "$OUT/images.json"

ro_docker container inspect "$RUNNER" "$DIND" > "$OUT/containers.json"
ro_docker network ls --format '{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}' > "$OUT/networks.json"
ro_docker volume ls --format '{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}' > "$OUT/volumes.json"

# Omvang van de inner-DinD-data. Kan bij ~121 GB enkele minuten duren.
DIND_SRC="$(ro_docker container inspect "$DIND" \
  --format '{{range .Mounts}}{{if eq .Destination "/var/lib/docker"}}{{.Source}}{{end}}{{end}}')"
if [ -n "$DIND_SRC" ]; then
  printf 'mountpoint\t%s\n' "$DIND_SRC" > "$OUT/dind-usage.txt"
  sudo -n du -sb "$DIND_SRC" >> "$OUT/dind-usage.txt"
else
  printf 'mountpoint\tONBEKEND — geen mount op /var/lib/docker gevonden\n' > "$OUT/dind-usage.txt"
fi

# Legacy .runner: metadata bewaren, tokenwaarde nooit.
RUNNER_SRC="$(ro_docker container inspect "$RUNNER" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
if [ -n "$RUNNER_SRC" ] && sudo -n test -f "$RUNNER_SRC/.runner"; then
  sudo -n stat -c '%a %U:%G %n' "$RUNNER_SRC/.runner" > "$OUT/runner-registration-stat.txt"
  sudo -n cat "$RUNNER_SRC/.runner" | python3 -c '
import json, sys
d = json.load(sys.stdin)
d.pop("token", None)
d["token"] = "<GEREDIGEERD>"
json.dump(d, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
print()
' > "$OUT/runner-registration.json"
else
  printf '{"fout":"geen .runner gevonden"}\n' > "$OUT/runner-registration.json"
fi

printf 'inventarisatie geschreven naar %s\n' "$OUT"
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_capture_current.bats`
Expected: PASS — 3 tests, 0 failures.

- [ ] **Step 5: Lint**

Run: `shellcheck -x forgejo-runner/scripts/capture-current.sh`
Expected: geen bevindingen.

- [ ] **Step 6: Draai hem echt, read-only, op `scrum4me-server`**

```bash
ssh janpeter@scrum4me-srv 'mkdir -p /tmp/s4m-capture/scripts/lib'
scp forgejo-runner/scripts/capture-current.sh janpeter@scrum4me-srv:/tmp/s4m-capture/scripts/
scp forgejo-runner/scripts/lib/readonly.sh janpeter@scrum4me-srv:/tmp/s4m-capture/scripts/lib/
ssh janpeter@scrum4me-srv 'bash /tmp/s4m-capture/scripts/capture-current.sh \
  --runner scrum4me-forgejo-runner --dind scrum4me-forgejo-dind \
  --out /tmp/s4m-capture/out'
mkdir -p docs/forgejo-runner-pool/evidence/stap-a
scp -r janpeter@scrum4me-srv:/tmp/s4m-capture/out/. \
  docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/
```

Expected: alle vijf bestanden aanwezig; `images.json` bevat voor beide images een `RepoDigests`-regel met een `sha256:`-waarde.

- [ ] **Step 7: Extraheer de canonieke labelnamen**

Task 6 heeft de labelnamen nodig om te bepalen of een workflow de gedeelde pool kan bereiken. Die namen staan in de live installatie in het `labels`-veld van `.runner` — het Forgejo-record toont alleen kale namen en is volgens §7.4 geen geldige bron voor de imageverwijzing, maar voor de **namen** is `.runner` de canonieke bron en die is in stap A al beschikbaar. Zo hoeft Task 6 niet op `labels.txt` uit stap B te wachten.

```bash
EV=docs/forgejo-runner-pool/evidence/stap-a
python3 - "$EV/scrum4me-server/runner-registration.json" > "$EV/shared-label-names.txt" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for label in d.get("labels") or []:
    # Een label heeft de vorm `naam` of `naam:docker://image`; alleen de naam telt hier.
    print(str(label).split(":", 1)[0])
PY
cat "$EV/shared-label-names.txt"
```

Expected: minstens één regel, met `ubuntu-latest` als de live installatie ongewijzigd is. Is het bestand leeg, dan is `.runner` niet uitgelezen of bevat het geen labels — dat is een bevinding vóór Task 6, want de trustgate kan dan niet bepalen welke workflows de pool bereiken.

- [ ] **Step 8: Controleer dat er geen tokenwaarde in het bewijs staat**

```bash
grep -rE '[A-Za-z0-9_-]{30,}' docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/runner-registration.json
```

Expected: geen treffer anders dan een UUID; het veld `token` bevat letterlijk `<GEREDIGEERD>`. Vind je wél een tokenachtige string, verwijder het bestand, corrigeer de redactie en begin deze stap opnieuw — commit hem niet.

- [ ] **Step 9: Commit**

```bash
git add forgejo-runner/scripts/capture-current.sh forgejo-runner/tests/test_capture_current.bats \
        docs/forgejo-runner-pool/evidence/stap-a/scrum4me-server/ \
        docs/forgejo-runner-pool/evidence/stap-a/shared-label-names.txt
git commit -m "feat(stap-a): read-only inventarisatie van de live runnerstack"
```

---

### Task 3: Runnerrecords inventariseren via de Forgejo-API

§8 stap A eist een inventarisatie van alle zichtbare runnerrecords met ID, naam, scope, versie, labels, online/offline en busy/idle. De endpoints en veldnamen hieronder zijn op 2026-08-31 uit de OpenAPI-spec van de draaiende instance gelezen en niet uit documentatie overgenomen.

Bevestigde endpoints op Forgejo `15.0.2+gitea-1.22.0`, basis `/api/v1`:

| Endpoint | Methoden | Gebruik |
|---|---|---|
| `/admin/actions/runners` | `get`, `post` | globale runnerrecords lezen; `post` pas in stap C |
| `/admin/actions/runners/{runner_id}` | `get`, `delete` | één record lezen of verwijderen |
| `/admin/actions/runners/jobs` | `get` | jobs per runner — bron voor het assignment-nulbewijs |
| `/admin/actions/runners/registration-token` | `get` | registratietoken |
| `/orgs/{org}/actions/runners` | `get`, `post` | org-scope |
| `/repos/{owner}/{repo}/actions/runners` | `get`, `post` | repo-scope |

Bevestigde responsevelden:

- `ActionRunner`: `id`, `uuid`, `name`, `labels` (array), `status`, `version`, `ephemeral` (boolean), `owner_id`, `repo_id`, `description`
- `ActionRunJob`: `id`, `name`, `status`, `runs_on` (array), `task_id`, `handle`, `attempt`, `owner_id`, `repo_id`
- `RegisterRunnerOptions` (POST-body): `name`, `description`, `ephemeral`
- `RegisterRunnerResponse`: `id`, `uuid`, `token`

Global scope is `owner_id: 0` en `repo_id: 0`, wat §7.4 van het ontwerp stelt; de inventarisatie bevestigt dat en neemt het niet aan.

**Files:**
- Create: `forgejo-runner/scripts/capture-forgejo-records.sh`
- Test: `forgejo-runner/tests/test_capture_forgejo_records.bats`

**Interfaces:**
- Consumes: omgevingsvariabele `FORGEJO_TOKEN`; `FORGEJO_URL` met standaardwaarde `https://git.jp-visser.nl`
- Produces: `runners-<scope>.json` met de ruwe API-respons, en `runners-summary.tsv` met per record `id`, `uuid`, `name`, `status`, `ephemeral`, `owner_id`, `repo_id` en de labels als komma-lijst. Task 6 en stap F lezen `runners-summary.tsv` om te bewijzen dat alleen de bedoelde records de gedeelde labels aanbieden.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_capture_forgejo_records.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/capture-forgejo-records.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/curl" <<'EOS'
#!/usr/bin/env bash
# Negeer alle opties; geef een vaste, geldige respons terug.
for a in "$@"; do
  case "$a" in
    *runners) echo '[{"id":1,"uuid":"u-1","name":"scrum4me-srv-runner-01","status":"online","ephemeral":false,"owner_id":0,"repo_id":0,"labels":["ubuntu-latest"],"version":"12.10.1"}]' ; exit 0 ;;
  esac
done
echo '[]'
EOS
  chmod +x "$FAKE_BIN/curl"
  PATH="$FAKE_BIN:$PATH"
  export FORGEJO_TOKEN="niet-echt"
}

@test "schrijft ruwe respons en samenvatting" {
  out="$BATS_TEST_TMPDIR/ev"
  run bash "$SCRIPT" --scope global --out "$out"
  [ "$status" -eq 0 ]
  [ -f "$out/runners-global.json" ]
  [ -f "$out/runners-summary.tsv" ]
}

@test "samenvatting bevat labels en scope-velden" {
  out="$BATS_TEST_TMPDIR/ev"
  bash "$SCRIPT" --scope global --out "$out"
  grep -q 'scrum4me-srv-runner-01' "$out/runners-summary.tsv"
  grep -q 'ubuntu-latest' "$out/runners-summary.tsv"
  head -1 "$out/runners-summary.tsv" | grep -q 'ephemeral'
}

@test "faalt zonder FORGEJO_TOKEN" {
  out="$BATS_TEST_TMPDIR/ev"
  FORGEJO_TOKEN="" run bash "$SCRIPT" --scope global --out "$out"
  [ "$status" -ne 0 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_capture_forgejo_records.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/capture-forgejo-records.sh
# Read-only inventarisatie van Forgejo-runnerrecords. Draait op mac.
# Het token gaat via curl --config zodat het niet in argv of shellhistory staat.
set -euo pipefail

FORGEJO_URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
SCOPE="global" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2" ; shift 2 ;;
    --out)   OUT="$2"   ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { printf 'gebruik: --scope global|org:NAAM|repo:OWNER/NAAM --out MAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt in de omgeving\n' >&2 ; exit 3 ; }

case "$SCOPE" in
  global)   PATH_SEG="/api/v1/admin/actions/runners" ; SLUG="global" ;;
  org:*)    PATH_SEG="/api/v1/orgs/${SCOPE#org:}/actions/runners" ; SLUG="org-${SCOPE#org:}" ;;
  repo:*)   PATH_SEG="/api/v1/repos/${SCOPE#repo:}/actions/runners" ; SLUG="repo-$(printf '%s' "${SCOPE#repo:}" | tr '/' '-')" ;;
  *) printf 'onbekende scope: %s\n' "$SCOPE" >&2 ; exit 2 ;;
esac

mkdir -p "$OUT"
RAW="$OUT/runners-$SLUG.json"

curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
     --silent --show-error --fail-with-body --max-time 30 \
     "$FORGEJO_URL$PATH_SEG" > "$RAW"

SUMMARY="$OUT/runners-summary.tsv"
[ -f "$SUMMARY" ] || printf 'scope\tid\tuuid\tname\tstatus\tephemeral\towner_id\trepo_id\tlabels\n' > "$SUMMARY"

python3 - "$RAW" "$SCOPE" >> "$SUMMARY" <<'PY'
import json, sys
raw, scope = sys.argv[1], sys.argv[2]
data = json.load(open(raw))
records = data if isinstance(data, list) else data.get("runners", [])
for r in records:
    print("\t".join([
        scope,
        str(r.get("id", "")),
        str(r.get("uuid", "")),
        str(r.get("name", "")),
        str(r.get("status", "")),
        str(r.get("ephemeral", "")),
        str(r.get("owner_id", "")),
        str(r.get("repo_id", "")),
        ",".join(r.get("labels") or []),
    ]))
PY

printf 'records voor scope %s geschreven naar %s\n' "$SCOPE" "$OUT"
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_capture_forgejo_records.bats`
Expected: PASS — 3 tests, 0 failures.

- [ ] **Step 5: Lint**

Run: `shellcheck forgejo-runner/scripts/capture-forgejo-records.sh`
Expected: geen bevindingen.

- [ ] **Step 6: Draai hem echt tegen de instance**

```bash
source ~/.zshenv
bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global \
  --out docs/forgejo-runner-pool/evidence/stap-a/forgejo
cat docs/forgejo-runner-pool/evidence/stap-a/forgejo/runners-summary.tsv
```

Expected: minstens één record met `status: online` en `version` beginnend met `12.`. Krijg je HTTP 403, dan mist `FORGEJO_TOKEN` adminrechten — dat is een bevinding voor JP en geen reden om een ander token te zoeken. Noteer het en stop deze taak.

- [ ] **Step 7: Bevestig de scope-aanname uit §7.4**

```bash
awk -F'\t' 'NR>1 {print $4, "owner_id="$7, "repo_id="$8}' \
  docs/forgejo-runner-pool/evidence/stap-a/forgejo/runners-summary.tsv
```

Expected: het bestaande runnerrecord heeft `owner_id=0` en `repo_id=0`. Wijkt dat af, dan klopt §7.4 niet en is dat een bevinding vóór stap B.

- [ ] **Step 8: Stel `T_requeue` vast en leg het bewijs vast**

§8 stap A eist dat de effectieve Actions assignment- of requeue-timeout als `T_requeue` wordt vastgelegd, omdat die uitkomst de wachttak in §7.9 aan- of uitzet. Deze waarde komt uit de effectieve Forgejo-configuratie en de bijbehorende versiebron, niet uit een schatting.

```bash
# 1. De effectieve configuratie van de draaiende instance.
ssh janpeter@scrum4me-srv 'docker exec scrum4me-forgejo \
  cat /data/gitea/conf/app.ini 2>/dev/null || cat /etc/gitea/app.ini' \
  | grep -iA 20 '^\[actions\]' | tee /tmp/actions-config.txt

# 2. De defaults van deze exacte versie, uit de container zelf.
ssh janpeter@scrum4me-srv 'docker exec scrum4me-forgejo forgejo --version'
```

Schrijf `docs/forgejo-runner-pool/evidence/stap-a/t-requeue.md` met: het gevonden configblok, de versie waartegen je het hebt gelezen, de afgeleide waarde van `T_requeue` in seconden, en het commando waarmee je het hebt vastgesteld.

Kun je `T_requeue` **niet** aantoonbaar vaststellen, schrijf dat dan expliciet op. Dat is een geldige uitkomst: §7.9 schakelt de wachttak dan uit en iedere ambigue toewijzing gaat via gecontroleerde cancel en redispatch. Raad geen waarde — een verzonnen `T_requeue` maakt de wachttak juist gevaarlijk.

Let op: `docker exec` is hier een leesactie, maar staat bewust niet in de read-only guard van Task 1. Voer hem daarom handmatig uit zoals hierboven en niet via `ro_docker`; de guard blijft zo scherp voor de geautomatiseerde paden.

- [ ] **Step 9: Commit**

```bash
git add forgejo-runner/scripts/capture-forgejo-records.sh \
        forgejo-runner/tests/test_capture_forgejo_records.bats \
        docs/forgejo-runner-pool/evidence/stap-a/forgejo/ \
        docs/forgejo-runner-pool/evidence/stap-a/t-requeue.md
git commit -m "feat(stap-a): inventarisatie van Forgejo-runnerrecords en T_requeue"
```

---

### Task 4: Ephemeral-spike

Het ontwerp noemt ephemeral runners nergens, terwijl Forgejo 15.0.2 ze native ondersteunt en de officiële documentatie ze als **securityfeature** beschrijft: Forgejo wijst zo'n runner hooguit één job toe en verwijdert hem daarna, wat voorkomt dat een gelekt runnertoken nog een volgende job kan opvragen. Voor een ontwerp dat een privileged DinD met global scope naast productie zet en zwaar op tokenhygiëne leunt (§7.3, §7.6), is dat direct relevant.

Deze taak meet wat er feitelijk gebeurt, zodat de daaropvolgende delta-review op bewijs berust en niet op documentatie. Ze beslist zelf niets.

Wat de documentatie stelt en wat deze spike moet toetsen:

| Bewering uit de Forgejo-docs | Toetsing hier |
|---|---|
| Registratie accepteert `ephemeral: true` | Step 5 — POST en respons |
| Het record toont `ephemeral: true` | Step 6 — GET op hetzelfde record |
| Forgejo wijst hooguit één job toe en verwijdert het record daarna | **Niet hier** — vereist een echte job; wordt een extra assertie in stap E op `max2` |
| Ephemeral vereist de one-job-uitvoermethode; daemon-mode stopt direct | Step 7 — tegen de echte Runner 12.10.1-image, zonder registratie |

**Veiligheidskaders, alle vier hard.** Deze taak is de enige uitzondering op "stap A muteert niets" en blijft strikt binnen deze grenzen:

1. het testrecord krijgt `name: ephemeral-spike-<datum>` en draagt **geen enkel label**. Dat is geen keuze maar een eigenschap van de API: `RegisterRunnerOptions` kent exact drie velden — `description`, `ephemeral` en `name` — en heeft geen `labels`. Labels bereiken een runnerrecord uitsluitend doordat een runnerdaemon ze bij het verbinden meldt, en kader 2 verbiedt juist dat er een daemon start. Een record zonder labels matcht geen enkele `runs-on`, dus er kan geen productiejob op landen. Het script bewijst dit met een harde assertie op het teruggelezen record;
2. er wordt **geen runnerproces** met dit record gestart;
3. het record wordt in dezelfde taak verwijderd en de verwijdering wordt bewezen;
4. de bestaande runner en zijn record worden niet aangeraakt.

**Files:**
- Create: `forgejo-runner/scripts/spike-ephemeral.sh`
- Create: `docs/forgejo-runner-pool/evidence/stap-a/ephemeral-spike.md`
- Test: `forgejo-runner/tests/test_spike_ephemeral.bats`

**Interfaces:**
- Consumes: `FORGEJO_TOKEN`, `FORGEJO_URL`; `capture-forgejo-records.sh` uit Task 3 voor de vóór- en nameting
- Produces: `ephemeral-spike.md` met per bewering het commando, de respons en de uitkomst. Dit bestand is de bijlage bij de delta-review.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_spike_ephemeral.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/spike-ephemeral.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  # De nep-curl is bewust stateful: na de DELETE moet een GET op hetzelfde
  # record falen, anders is het opruimbewijs niet te halen en kan de suite
  # per constructie nooit groen worden.
  export FAKE_STATE="$BATS_TEST_TMPDIR/verwijderd"
  cat > "$FAKE_BIN/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*)
    touch "$FAKE_STATE" ; echo '' ; exit 0 ;;
  *runners/999*)
    # Na de DELETE bestaat het record niet meer; curl --fail-with-body geeft dan non-zero.
    [ -e "$FAKE_STATE" ] && exit 22
    echo '{"id":999,"uuid":"u-999","name":"ephemeral-spike-test","ephemeral":true,"labels":[],"status":"offline"}'
    exit 0 ;;
  *runners*)
    echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
echo '{}'
EOS
  chmod +x "$FAKE_BIN/curl"
  PATH="$FAKE_BIN:$PATH"
  export FORGEJO_TOKEN="niet-echt"
}

@test "weigert een label zonder spike-prefix" {
  run bash "$SCRIPT" --label ubuntu-latest --out "$BATS_TEST_TMPDIR/ev"
  [ "$status" -ne 0 ]
  [[ "$output" == *"ephemeral-spike-"* ]]
}

@test "lekt het teruggegeven token niet naar het bewijsbestand" {
  out="$BATS_TEST_TMPDIR/ev"
  bash "$SCRIPT" --label ephemeral-spike-test --out "$out"
  run grep -r "GEHEIM" "$out"
  [ "$status" -ne 0 ]
}

@test "verwijdert het record en legt dat vast" {
  out="$BATS_TEST_TMPDIR/ev"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$out"
  [ "$status" -eq 0 ]
  grep -q "verwijderd" "$out/ephemeral-spike.md"
}

@test "faalt als het record na de DELETE blijft bestaan" {
  # Zonder state blijft de GET slagen; het script hoort dan met 5 te stoppen.
  cat > "$BATS_TEST_TMPDIR/bin/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*) echo '' ; exit 0 ;;
  *runners/999*) echo '{"id":999,"uuid":"u-999","labels":[]}' ; exit 0 ;;
  *runners*)     echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
EOS
  chmod +x "$BATS_TEST_TMPDIR/bin/curl"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$BATS_TEST_TMPDIR/ev2"
  [ "$status" -eq 5 ]
}

@test "faalt als het record toch labels blijkt te dragen" {
  cat > "$BATS_TEST_TMPDIR/bin/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*) touch "$FAKE_STATE" ; echo '' ; exit 0 ;;
  *runners/999*)
    [ -e "$FAKE_STATE" ] && exit 22
    echo '{"id":999,"uuid":"u-999","labels":["ubuntu-latest"]}' ; exit 0 ;;
  *runners*) echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
EOS
  chmod +x "$BATS_TEST_TMPDIR/bin/curl"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$BATS_TEST_TMPDIR/ev3"
  [ "$status" -eq 6 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_spike_ephemeral.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/spike-ephemeral.sh
# Meet of ephemeral runnerregistratie werkt op deze Forgejo-instance.
# Maakt exact een record aan met een canary-label en verwijdert het weer.
# Start nooit een runnerproces en raakt de bestaande runner niet aan.
set -euo pipefail

FORGEJO_URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
LABEL="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$2" ; shift 2 ;;
    --out)   OUT="$2"   ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$LABEL" ] && [ -n "$OUT" ] || { printf 'gebruik: --label ephemeral-spike-<datum> --out MAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt\n' >&2 ; exit 3 ; }

# Veiligheidskader 1: alleen een canary-label, nooit een productielabel.
case "$LABEL" in
  ephemeral-spike-*) : ;;
  *) printf 'geweigerd: het label moet met ephemeral-spike- beginnen, kreeg %s\n' "$LABEL" >&2 ; exit 4 ;;
esac

mkdir -p "$OUT"
DOC="$OUT/ephemeral-spike.md"
api() { curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
             --silent --show-error --fail-with-body --max-time 30 "$@" ; }

{
  printf '# Ephemeral-spike\n\n'
  printf 'Instance: %s\n\n' "$FORGEJO_URL"
  printf 'Canary-label: `%s`\n\n' "$LABEL"
} > "$DOC"

# Registreren met ephemeral: true.
CREATE_JSON="$(api --request POST --header 'Content-Type: application/json' \
  --data "$(printf '{"name":"%s","description":"stap-A ephemeral spike","ephemeral":true}' "$LABEL")" \
  "$FORGEJO_URL/api/v1/admin/actions/runners")"

RUNNER_ID="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
RUNNER_UUID="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uuid",""))')"
HAS_TOKEN="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print("ja" if json.load(sys.stdin).get("token") else "nee")')"

{
  printf '## 1. Registratie accepteert `ephemeral: true`\n\n'
  printf -- '- record-id: `%s`\n' "$RUNNER_ID"
  printf -- '- uuid: `%s`\n' "$RUNNER_UUID"
  printf -- '- respons bevatte een token: %s (waarde bewust niet vastgelegd)\n\n' "$HAS_TOKEN"
} >> "$DOC"

# Terugleesbewijs: staat ephemeral echt op het record, en draagt het geen labels?
READ_JSON="$(api "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID")"

# Veiligheidskader 1: RegisterRunnerOptions kent geen labels en er verbindt geen
# daemon, dus het record hoort labelloos te zijn. Blijkt dat niet zo, dan klopt
# de aanname niet en stoppen we voordat er iets op dit record kan landen.
LABELS_AANTAL="$(printf '%s' "$READ_JSON" | python3 -c '
import json,sys
print(len(json.load(sys.stdin).get("labels") or []))
')"
if [ "$LABELS_AANTAL" != "0" ]; then
  printf 'FOUT: record %s draagt %s label(s); veiligheidskader 1 klopt niet. Verwijder het record handmatig.\n' \
    "$RUNNER_ID" "$LABELS_AANTAL" >&2
  api --request DELETE "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null || true
  exit 6
fi

{
  printf '## 2. Het record toont ephemeral en draagt geen labels\n\n```json\n'
  printf '%s' "$READ_JSON" | python3 -c '
import json,sys
d=json.load(sys.stdin)
d.pop("token",None)
json.dump(d,sys.stdout,indent=2,sort_keys=True,ensure_ascii=False)
print()
'
  printf '```\n\n'
} >> "$DOC"

# Veiligheidskader 3: opruimen en bewijzen.
api --request DELETE "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null
if api "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null 2>&1; then
  printf '## 3. Opruimen\n\nFOUT: record %s bestaat na DELETE nog steeds. Handmatig opruimen vereist.\n' "$RUNNER_ID" >> "$DOC"
  exit 5
fi
printf '## 3. Opruimen\n\nRecord `%s` is verwijderd; een GET erop geeft geen record meer terug.\n' "$RUNNER_ID" >> "$DOC"

printf 'spike afgerond, bewijs in %s\n' "$DOC"
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_spike_ephemeral.bats`
Expected: PASS — 5 tests, 0 failures.

- [ ] **Step 5: Draai de spike echt, met vóór- en nameting**

```bash
source ~/.zshenv
SPIKE_LABEL="ephemeral-spike-$(date -u +%Y%m%d)"
EV=docs/forgejo-runner-pool/evidence/stap-a

bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out "$EV/forgejo-voor-spike"
bash forgejo-runner/scripts/spike-ephemeral.sh --label "$SPIKE_LABEL" --out "$EV"
bash forgejo-runner/scripts/capture-forgejo-records.sh --scope global --out "$EV/forgejo-na-spike"

diff <(cut -f2- "$EV/forgejo-voor-spike/runners-summary.tsv" | sort) \
     <(cut -f2- "$EV/forgejo-na-spike/runners-summary.tsv" | sort)
```

Expected: de spike rapporteert dat het record is verwijderd, en de `diff` is leeg — de recordlijst is na de spike identiek aan ervoor. Is de diff niet leeg, dan is er een record blijven staan; verwijder het onmiddellijk via `DELETE /api/v1/admin/actions/runners/{id}` en noteer dat in het bewijs.

- [ ] **Step 6: Toets de daemon-mode-bewering tegen de echte runner-image**

De documentatie stelt dat daemon-mode direct stopt zodra de runner een ephemeral-configuratie krijgt. Dit toetst dat zonder enige registratie, in een wegwerpcontainer op `max2` die verder niets aanraakt.

```bash
ssh janpeter@max2 'docker run --rm --entrypoint forgejo-runner \
  code.forgejo.org/forgejo/runner:12 --help 2>&1 | sed -n "1,60p"'
```

Expected: de uitvoer toont de beschikbare subcommando's, waaronder `daemon` en `one-job`. Noteer in `ephemeral-spike.md` letterlijk welke subcommando's en vlaggen bestaan; dit is tevens de eerste bevestiging van de `one-job --wait`-opdracht die Task 17 opnieuw hard valideert. Verschijnt `one-job` hier niet, dan is dat een BLOCKER voor het hele ontwerp en stopt dit plan.

- [ ] **Step 7: Schrijf de afweging op zonder haar te beslissen**

Vul `ephemeral-spike.md` aan met een slotsectie die precies drie dingen bevat, en geen aanbeveling:

1. **Wat gemeten is** — de uitkomsten van step 5 en 6, met de commando's erbij.
2. **Wat ephemeral zou toevoegen** — server-side afdwinging dat een gelekt runnertoken geen volgende job kan opvragen; relevant omdat §7.6 een privileged DinD met global scope naast productie accepteert.
3. **Wat het kost** — een ephemeral record wordt na één job door het systeem verwijderd, dus de cyclecontroller moet elke cyclus opnieuw registreren met een registratietoken. Dat raakt §7.3 (tokenhygiëne per cyclus in plaats van één stabiel token) en §7.4 (de gate "alleen de twee bedoelde records bieden de gedeelde labels aan" wordt dynamisch in plaats van statisch). Noteer ook wat het **niet** oplost: het FetchTask-ambiguïteitsvenster bij een drain blijft bestaan, dus het assignment-nulbewijs uit §7.9 en de schedulingfence uit §7.7 blijven nodig.

- [ ] **Step 8: Commit**

```bash
git add forgejo-runner/scripts/spike-ephemeral.sh \
        forgejo-runner/tests/test_spike_ephemeral.bats \
        docs/forgejo-runner-pool/evidence/stap-a/
git commit -m "feat(stap-a): ephemeral-spike met bewijs voor de delta-review"
```

- [ ] **Step 9: Leg de uitkomst aan JP voor**

Dit is een besluitpunt, geen implementatiestap. Meld de uitkomst en vraag of ephemeral als delta op het ontwerp moet worden opgenomen. Bouw niets ephemeral-gerelateerds in de bundel voordat die delta-review GO heeft: tot dat moment blijft het ontwerp met persistente records en de client-side fence leidend.

---

### Task 5: Klokskew en tijdsynchronisatie vastleggen

§8 stap A eist op beide hosts de NTP-/chrony-status en de gemeten wandklokskew tegen de Forgejo-`Date`-header. Deze meting is **uitsluitend audit en corroboratie**: `event_seq` blijft volgens §7.7 de enige vóór/na-fencebeslisser. Het plan legt dat vast zodat niemand later de klok als beslisser inbouwt.

**Files:**
- Create: `forgejo-runner/scripts/capture-clock-skew.sh`
- Test: `forgejo-runner/tests/test_capture_clock_skew.bats`

**Interfaces:**
- Consumes: niets uit eerdere taken
- Produces: `clock-<host>.txt` met `timedatectl`-status, chrony-tracking indien aanwezig, en de skew in milliseconden tussen de lokale klok en de `Date`-header van de Forgejo-instance.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_capture_clock_skew.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/capture-clock-skew.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/timedatectl" <<'EOS'
#!/usr/bin/env bash
echo "System clock synchronized: yes"
echo "NTP service: active"
EOS
  cat > "$FAKE_BIN/curl" <<'EOS'
#!/usr/bin/env bash
echo "date: Sun, 31 Aug 2026 17:00:00 GMT"
EOS
  chmod +x "$FAKE_BIN"/*
  PATH="$FAKE_BIN:$PATH"
}

@test "schrijft een bewijsbestand met sync-status en skew" {
  out="$BATS_TEST_TMPDIR/ev"
  run bash "$SCRIPT" --host testhost --url https://voorbeeld.invalid --out "$out"
  [ "$status" -eq 0 ]
  grep -q "synchronized" "$out/clock-testhost.txt"
  grep -q "skew_ms" "$out/clock-testhost.txt"
}

@test "vermeldt dat de meting alleen audit is" {
  out="$BATS_TEST_TMPDIR/ev"
  bash "$SCRIPT" --host testhost --url https://voorbeeld.invalid --out "$out"
  grep -qi "audit" "$out/clock-testhost.txt"
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_capture_clock_skew.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/capture-clock-skew.sh
# Legt tijdsynchronisatie en wandklokskew vast. Read-only.
# Deze meting is uitsluitend audit/corroboratie; event_seq blijft de enige
# voor/na-fencebeslisser volgens 7.7 van het migratieontwerp.
set -euo pipefail

HOSTNAME_LABEL="" ; URL="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOSTNAME_LABEL="$2" ; shift 2 ;;
    --url)  URL="$2"            ; shift 2 ;;
    --out)  OUT="$2"            ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$HOSTNAME_LABEL" ] && [ -n "$URL" ] && [ -n "$OUT" ] || {
  printf 'gebruik: --host NAAM --url URL --out MAP\n' >&2 ; exit 2 ; }

mkdir -p "$OUT"
DEST="$OUT/clock-$HOSTNAME_LABEL.txt"

{
  printf 'host\t%s\n' "$HOSTNAME_LABEL"
  printf 'doel\taudit en corroboratie; event_seq blijft de enige voor/na-fencebeslisser (7.7)\n'
  printf '\n## timedatectl\n'
  timedatectl 2>&1 || printf 'timedatectl niet beschikbaar\n'
  printf '\n## chrony\n'
  if command -v chronyc >/dev/null 2>&1; then chronyc tracking 2>&1; else printf 'chronyc niet aanwezig\n'; fi
  printf '\n## skew tegen de Forgejo Date-header\n'
} > "$DEST"

LOCAL_BEFORE_MS="$(python3 -c 'import time;print(int(time.time()*1000))')"
REMOTE_DATE="$(curl --silent --show-error --head --max-time 20 "$URL" 2>/dev/null \
  | tr 'A-Z' 'a-z' | awk -F': ' '/^date: /{print $2; exit}')"
LOCAL_AFTER_MS="$(python3 -c 'import time;print(int(time.time()*1000))')"

if [ -z "$REMOTE_DATE" ]; then
  printf 'skew_ms\tONBEKEND — geen Date-header ontvangen\n' >> "$DEST"
else
  python3 - "$REMOTE_DATE" "$LOCAL_BEFORE_MS" "$LOCAL_AFTER_MS" >> "$DEST" <<'PY'
import sys
from email.utils import parsedate_to_datetime
remote, before, after = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
remote_ms = int(parsedate_to_datetime(remote).timestamp() * 1000)
midpoint = (before + after) // 2
print("remote_date\t%s" % remote)
print("lokaal_midden_ms\t%d" % midpoint)
print("rondreis_ms\t%d" % (after - before))
print("skew_ms\t%d" % (midpoint - remote_ms))
print("let_op\tde Date-header heeft secondeprecisie; een skew onder 1000 ms is niet betekenisvol")
PY
fi

printf 'klokbewijs geschreven naar %s\n' "$DEST"
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_capture_clock_skew.bats`
Expected: PASS — 2 tests, 0 failures.

- [ ] **Step 5: Lint en meet op beide hosts**

```bash
shellcheck forgejo-runner/scripts/capture-clock-skew.sh
for H in scrum4me-srv max2; do
  scp forgejo-runner/scripts/capture-clock-skew.sh "janpeter@$H:/tmp/"
  ssh "janpeter@$H" "bash /tmp/capture-clock-skew.sh --host \$(hostname) \
    --url https://git.jp-visser.nl --out /tmp/clock"
done
mkdir -p docs/forgejo-runner-pool/evidence/stap-a
scp janpeter@scrum4me-srv:/tmp/clock/clock-scrum4me-server.txt docs/forgejo-runner-pool/evidence/stap-a/
scp janpeter@max2:/tmp/clock/clock-max2.txt docs/forgejo-runner-pool/evidence/stap-a/max2-clock.txt
```

Expected: op beide hosts `System clock synchronized: yes`. Staat er `no`, dan is dat een bevinding die vóór stap D moet zijn opgelost — niet omdat de fence ervan afhangt, maar omdat de auditsporen anders onbruikbaar zijn.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/capture-clock-skew.sh \
        forgejo-runner/tests/test_capture_clock_skew.bats \
        docs/forgejo-runner-pool/evidence/stap-a/
git commit -m "feat(stap-a): klokskew en tijdsynchronisatie als auditbewijs"
```

---

### Task 6: Trustscope-gate

De zwaarste gate van stap A. §7.7 eist een mechanische allowlist van iedere Actions-enabled repository en iedere identiteit met write- of adminrechten op workflowbestanden, met fail-closed gedrag zodra iets niet ondubbelzinnig uitleesbaar is.

De inventarisatie is nu volledig mechanisch te maken: de `Repository`-respons van Forgejo 15.0.2 bevat het veld **`has_actions`** (boolean), naast `full_name`, `owner`, `private`, `internal`, `fork` en `default_branch`. Daarmee is de vraag "is Actions ingeschakeld?" een gemeten waarde in plaats van een aanname — precies wat delta-review R12 ronde 2 eiste.

Bevestigde endpoints:

| Endpoint | Gebruik |
|---|---|
| `/api/v1/repos/search` | alle zichtbare repositories, gepagineerd |
| `/api/v1/repos/{owner}/{repo}/contents/{filepath}` | bestaan en inhoud van de workflowmap |
| `/api/v1/repos/{owner}/{repo}/collaborators` | collaborators |
| `/api/v1/repos/{owner}/{repo}/collaborators/{user}/permission` | effectief recht per collaborator |
| `/api/v1/repos/{owner}/{repo}/teams` | teams met toegang |
| `/api/v1/repos/{owner}/{repo}/branch_protections` | branch-protection op de default branch |
| `/api/v1/teams/{id}/members` | leden van een team met toegang tot de repository |

Bevestigde responseschema's, uit dezelfde spec gelezen:

- `Team`: `id`, `name`, `permission`, `units`, `units_map`, `organization`, `includes_all_repositories`
- `Permission`: `admin`, `pull`, `push`
- `User`: `login`, `is_admin`, …
- `BranchProtection`: `rule_name`, `branch_name`, `required_approvals`, `enable_push`, `enable_push_whitelist`, `push_whitelist_usernames`, `push_whitelist_teams`, `block_on_rejected_reviews`, `dismiss_stale_approvals`, `apply_to_admins`, …
- `ContentsResponse`: `name`, `path`, `type`, `size`, `content` (base64), `encoding`

§6 van het ontwerp benoemt `verify-trust-scope.sh` als het bundelbestand. De JSON-logica komt in een apart Python-module `scripts/trust_scope.py`, met `verify-trust-scope.sh` als dunne wrapper: de naam en de verantwoordelijkheid van het bundelbestand blijven zo exact zoals §6 ze belegt, terwijl de logica testbaar wordt zonder externe dependencies.

**Files:**
- Create: `forgejo-runner/scripts/trust_scope.py`
- Create: `forgejo-runner/scripts/trust_scope_cli.py`
- Create: `forgejo-runner/scripts/verify-trust-scope.sh`
- Create: `forgejo-runner/trusted-actions-scope.yml`
- Test: `forgejo-runner/tests/test_trust_scope.py`

**Interfaces:**
- Consumes: `FORGEJO_TOKEN`, `FORGEJO_URL`, en de gedeelde labelnamen uit `labels.txt`
- Produces:
  - `trust_scope.inventory(client, shared_labels) -> dict` — de gemeten toestand, met per repository `has_actions`, `workflow_source`, `workflows`, `risky_triggers`, `gebruikt_gedeeld_label`, `writers` (collaborators én teamleden), `branch_protection` en `unreadable`
  - `trust_scope.classify(inventory, allowlist) -> Verdict` met velden `hard: list[str]`, `soft: list[str]`, `unreadable: list[str]`. `Verdict.ok` is alleen `True` bij nul harde afwijkingen en nul onleesbare objecten.
  - clientcontract dat `trust_scope` verwacht: `repos()`, `contents(full_name, path)`, `collaborators(full_name)`, `collaborator_permission(full_name, login)`, `teams(full_name)`, `team_members(team_id)`, `branch_protections(full_name)`. Alleen `contents()` mag `None` teruggeven — dat betekent "map bestaat niet" en stuurt de fallback aan. Geeft een van de andere methoden `None`, dan is de meting onvolledig en is dat `Unreadable`.
  - Exitcodes van de wrapper: `0` groen, `10` zachte afwijking, `20` harde afwijking, `30` onleesbaar of fail-closed.

**Classificatieregels, afgeleid uit §7.7.** Hard: een workflow-schrijver die niet bij naam in de allowlist staat, ongeacht of hij via collaborator of via team binnenkomt; een Actions-enabled repository die niet in de allowlist staat; een risicovolle trigger (`pull_request`, `pull_request_target`, `workflow_run`) in een workflow die óók een gedeeld runnerlabel gebruikt — dat is het fork/PR-pad waarlangs onbetrouwbare code op de gedeelde labels kan starten. Zacht: een risicovolle trigger in een workflow die géén gedeeld label gebruikt; een ontbrekende branch-protection op de default branch van een repository die de gedeelde labels wél gebruikt; een nieuwe repository met Actions uit. Onleesbaar: iedere workflowmap, workflowbestand, collaborator-, team- of branch-protectionrespons die niet ondubbelzinnig uitleesbaar is — dat is fail-closed en levert exit 30.

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_trust_scope.py
import base64, unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import trust_scope

GEDEELDE_LABELS = ("ubuntu-latest",)


def b64(tekst):
    return {"content": base64.b64encode(tekst.encode()).decode(), "encoding": "base64",
            "path": "wf.yml", "type": "file", "name": "wf.yml"}


class FakeClient:
    """Levert vaste API-antwoorden; raakt geen netwerk."""

    def __init__(self, repos, contents=None, collaborators=None, permissions=None,
                 teams=None, team_members=None, protections=None, unreadable=()):
        self._repos = repos
        self._contents = contents or {}
        self._collaborators = collaborators or {}
        self._permissions = permissions or {}
        self._teams = teams or {}
        self._team_members = team_members or {}
        self._protections = protections or {}
        self._unreadable = set(unreadable)

    def repos(self):
        return self._repos

    def contents(self, full_name, path):
        if (full_name, path) in self._unreadable:
            raise trust_scope.Unreadable(f"{full_name}:{path}")
        return self._contents.get((full_name, path))

    def collaborators(self, full_name):
        return self._collaborators.get(full_name, [])

    def collaborator_permission(self, full_name, login):
        return self._permissions.get((full_name, login), {})

    def teams(self, full_name):
        return self._teams.get(full_name, [])

    def team_members(self, team_id):
        return self._team_members.get(team_id, [])

    def branch_protections(self, full_name):
        return self._protections.get(full_name, [])


REPO_ACTIONS = {
    "full_name": "janpeter/app", "has_actions": True, "private": True,
    "internal": False, "fork": False, "default_branch": "main",
    "owner": {"login": "janpeter"},
}
REPO_NO_ACTIONS = dict(REPO_ACTIONS, full_name="janpeter/stil", has_actions=False)

ALLOWLIST = {
    "repositories": [
        {"full_name": "janpeter/app", "actions_enabled": True,
         "workflow_source": ".forgejo/workflows", "writers": ["janpeter"]},
        {"full_name": "janpeter/stil", "actions_enabled": False,
         "workflow_source": None, "writers": ["janpeter"]},
    ],
    "identities": [{"name": "janpeter"}],
}

MAP = [{"name": "ci.yml", "type": "file", "path": ".forgejo/workflows/ci.yml"}]


class TestWorkflowSource(unittest.TestCase):
    def test_forgejo_map_wint_van_github_fallback(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".github/workflows"): [{"name": "oud.yml", "type": "file"}],
            ("janpeter/app", ".forgejo/workflows/ci.yml"): b64("on: push\n"),
        })
        inv = trust_scope.inventory(client, GEDEELDE_LABELS)
        self.assertEqual(inv["repositories"][0]["workflow_source"], ".forgejo/workflows")

    def test_valt_terug_op_github_als_forgejo_map_ontbreekt(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".github/workflows"): [
                {"name": "ci.yml", "type": "file", "path": ".github/workflows/ci.yml"}],
            ("janpeter/app", ".github/workflows/ci.yml"): b64("on: push\n"),
        })
        inv = trust_scope.inventory(client, GEDEELDE_LABELS)
        self.assertEqual(inv["repositories"][0]["workflow_source"], ".github/workflows")

    def test_onleesbare_map_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], unreadable=[("janpeter/app", ".forgejo/workflows")])
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.unreadable)

    def test_onleesbaar_workflowbestand_is_fail_closed(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"): {
                "content": "@@geen-base64@@", "encoding": "base64",
                "path": "ci.yml", "type": "file", "name": "ci.yml"},
        })
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.unreadable)

    def test_repo_zonder_actions_krijgt_geen_workflowbron(self):
        inv = trust_scope.inventory(FakeClient([REPO_NO_ACTIONS]), GEDEELDE_LABELS)
        self.assertIsNone(inv["repositories"][0]["workflow_source"])


class TestTriggerscan(unittest.TestCase):
    def test_detecteert_pull_request_target(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  pull_request_target:\n", GEDEELDE_LABELS)
        self.assertIn("pull_request_target", triggers)

    def test_pull_request_target_slokt_pull_request_niet_dubbel_op(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  pull_request_target:\n", GEDEELDE_LABELS)
        self.assertEqual(triggers, ["pull_request_target"])

    def test_detecteert_workflow_run(self):
        triggers, _ = trust_scope.scan_workflow("on: workflow_run\n", GEDEELDE_LABELS)
        self.assertIn("workflow_run", triggers)

    def test_push_only_is_niet_riskant(self):
        triggers, _ = trust_scope.scan_workflow("on:\n  push:\n", GEDEELDE_LABELS)
        self.assertEqual(triggers, [])

    def test_detecteert_gedeeld_label(self):
        _, gebruikt = trust_scope.scan_workflow("runs-on: ubuntu-latest\n", GEDEELDE_LABELS)
        self.assertTrue(gebruikt)

    def test_ander_label_telt_niet_als_gedeeld(self):
        _, gebruikt = trust_scope.scan_workflow("runs-on: eigen-runner\n", GEDEELDE_LABELS)
        self.assertFalse(gebruikt)

    def test_inventory_vult_risky_triggers_werkelijk(self):
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"):
                b64("on:\n  pull_request:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"),
        })
        repo = trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]
        self.assertEqual(repo["risky_triggers"], ["pull_request"])
        self.assertTrue(repo["gebruikt_gedeeld_label"])


class TestSchrijvers(unittest.TestCase):
    def _client(self, **kw):
        basis = dict(contents={("janpeter/app", ".forgejo/workflows"): []})
        basis.update(kw)
        return FakeClient([REPO_ACTIONS], **basis)

    def test_collaborator_met_push_is_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"permission": "write"}})
        # De eigenaar janpeter hoort er per definitie bij.
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["eva", "janpeter"])

    def test_collaborator_met_alleen_pull_is_geen_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "lezer"}]},
            permissions={("janpeter/app", "lezer"): {"permission": "read"}})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_teamlid_met_write_telt_ook_als_schrijver(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "write"}]},
            team_members={7: [{"login": "sam"}]})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter", "sam"])

    def test_teamlid_met_alleen_read_telt_niet(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 8, "name": "kijkers", "permission": "read"}]},
            team_members={8: [{"login": "kim"}]})
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_eigenaar_is_altijd_schrijver_ook_zonder_collaborators(self):
        # Forgejo neemt de eigenaar niet op in /collaborators; zonder deze regel
        # zou de meest bevoorrechte identiteit onzichtbaar blijven.
        client = self._client()
        self.assertEqual(trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"],
                         ["janpeter"])

    def test_permissierespons_is_de_echte_RepoCollaboratorPermission_vorm(self):
        # /collaborators/{c}/permission levert permission, role_name en user —
        # geen booleanmap. Deze test pint die vorm vast.
        client = self._client(
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {
                "permission": "write", "role_name": "write", "user": {"login": "eva"}}})
        self.assertIn("eva", trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"])

    def test_rol_owner_telt_als_schrijver(self):
        client = self._client(
            collaborators={"janpeter/app": [{"login": "baas"}]},
            permissions={("janpeter/app", "baas"): {"permission": "owner"}})
        self.assertIn("baas", trust_scope.inventory(client, GEDEELDE_LABELS)["repositories"][0]["writers"])

    def test_onbekend_teamlid_is_een_harde_afwijking(self):
        client = self._client(
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "admin"}]},
            team_members={7: [{"login": "vreemdeling"}]})
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("vreemdeling" in h for h in verdict.hard))


class TestVierenveertigVierNulVier(unittest.TestCase):
    """Een 404 op een trustscope-endpoint mag nooit stil "leeg" betekenen.

    Alleen het aftasten van de workflowmappen kent afwezigheid als geldige
    uitkomst; alles daarbuiten moet de gate rood maken (7.7 fail-closed).
    """

    class StubClient(FakeClient):
        def __init__(self, leeg_endpoint):
            super().__init__([REPO_ACTIONS],
                             contents={("janpeter/app", ".forgejo/workflows"): []})
            self.leeg = leeg_endpoint

        def collaborators(self, full_name):
            return None if self.leeg == "collaborators" else []

        def teams(self, full_name):
            return None if self.leeg == "teams" else []

        def branch_protections(self, full_name):
            return None if self.leeg == "branch_protections" else []

    def _verdict(self, endpoint):
        client = self.StubClient(endpoint)
        return trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)

    def test_404_op_collaborators_is_fail_closed(self):
        verdict = self._verdict("collaborators")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("collaboratorlijst" in u for u in verdict.unreadable))

    def test_404_op_teams_is_fail_closed(self):
        verdict = self._verdict("teams")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("teamlijst" in u for u in verdict.unreadable))

    def test_404_op_branch_protections_is_fail_closed(self):
        verdict = self._verdict("branch_protections")
        self.assertFalse(verdict.ok)
        self.assertTrue(any("branch-protection" in u for u in verdict.unreadable))

    def test_ontbrekende_permissierespons_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={})   # geen permissierespons voor eva
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("eva" in u for u in verdict.unreadable))

    def test_permissierespons_zonder_rolvelden_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"user": {"login": "eva"}}})
        verdict = trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("eva" in u for u in verdict.unreadable))

    def test_client_geeft_alleen_bij_missing_ok_none_terug(self):
        import urllib.error
        import trust_scope_cli

        class Nep404:
            def __call__(self, req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        client = trust_scope_cli.ForgejoClient("https://voorbeeld.invalid", "x")
        origineel = trust_scope_cli.urllib.request.urlopen
        trust_scope_cli.urllib.request.urlopen = Nep404()
        try:
            # De workflowmap mag ontbreken.
            self.assertIsNone(client._get("/repos/a/b/contents/.forgejo/workflows",
                                          missing_ok=True))
            # Alles daarbuiten is onleesbaar.
            with self.assertRaises(trust_scope.Unreadable):
                client._get("/repos/a/b/collaborators")
        finally:
            trust_scope_cli.urllib.request.urlopen = origineel


class TestVerplichteVelden(unittest.TestCase):
    """Een ontbrekend veld binnen een gemeten object is een onvolledige meting,
    nooit een stilzwijgende "nee" (7.7 fail-closed)."""

    def _verdict(self, client):
        return trust_scope.classify(trust_scope.inventory(client, GEDEELDE_LABELS), ALLOWLIST)

    def _rood(self, verdict, fragment):
        self.assertFalse(verdict.ok)
        self.assertTrue(any(fragment in u for u in verdict.unreadable),
                        f"{fragment!r} niet gevonden in {verdict.unreadable}")

    def test_repo_zonder_has_actions_is_fail_closed(self):
        repo = {k: v for k, v in REPO_ACTIONS.items() if k != "has_actions"}
        self._rood(self._verdict(FakeClient([repo])), "has_actions")

    def test_has_actions_als_null_is_fail_closed(self):
        repo = dict(REPO_ACTIONS, has_actions=None)
        self._rood(self._verdict(FakeClient([repo])), "has_actions")

    def test_repo_zonder_owner_login_is_fail_closed(self):
        repo = dict(REPO_ACTIONS, owner={})
        self._rood(self._verdict(FakeClient([repo])), "owner.login")

    def test_repo_zonder_default_branch_is_fail_closed(self):
        repo = {k: v for k, v in REPO_ACTIONS.items() if k != "default_branch"}
        self._rood(self._verdict(FakeClient([repo])), "default_branch")

    def test_collaborator_zonder_login_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"avatar_url": "x"}]})
        self._rood(self._verdict(client), "collaborator zonder login")

    def test_team_zonder_permission_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            teams={"janpeter/app": [{"id": 7, "name": "devs"}]})
        self._rood(self._verdict(client), "geen uitleesbare permission")

    def test_teamlid_zonder_login_is_fail_closed(self):
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            teams={"janpeter/app": [{"id": 7, "name": "devs", "permission": "write"}]},
            team_members={7: [{"full_name": "Zonder Login"}]})
        self._rood(self._verdict(client), "teamlid zonder login")

    def test_workflowbestand_zonder_encoding_is_fail_closed(self):
        bestand = {"content": "b24gcHVzaAo=", "path": "ci.yml", "type": "file", "name": "ci.yml"}
        client = FakeClient([REPO_ACTIONS], contents={
            ("janpeter/app", ".forgejo/workflows"): MAP,
            ("janpeter/app", ".forgejo/workflows/ci.yml"): bestand,
        })
        self._rood(self._verdict(client), "encoding-veld ontbreekt")

    def test_volledig_object_blijft_gewoon_groen(self):
        # De strengheid mag een correcte meting niet rood maken.
        client = FakeClient(
            [REPO_ACTIONS],
            contents={("janpeter/app", ".forgejo/workflows"): []},
            collaborators={"janpeter/app": [{"login": "eva"}]},
            permissions={("janpeter/app", "eva"): {"permission": "read"}},
            teams={"janpeter/app": [{"id": 7, "name": "kijkers", "permission": "read"}]},
            protections={"janpeter/app": [{"branch_name": "main"}]})
        verdict = self._verdict(client)
        self.assertTrue(verdict.ok, f"onverwacht rood: {verdict.hard} {verdict.unreadable}")


class TestClassificatie(unittest.TestCase):
    def _inv(self, **overrides):
        repo = {
            "full_name": "janpeter/app", "has_actions": True,
            "workflow_source": ".forgejo/workflows", "writers": ["janpeter"],
            "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [{"branch_name": "main"}],
            "default_branch": "main", "unreadable": [],
        }
        repo.update(overrides)
        return {"repositories": [repo], "unreadable": []}

    def test_alles_bekend_is_groen(self):
        verdict = trust_scope.classify(self._inv(), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.hard, [])
        self.assertEqual(verdict.soft, [])

    def test_onbekende_schrijver_is_hard(self):
        verdict = trust_scope.classify(self._inv(writers=["janpeter", "vreemdeling"]), ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("vreemdeling" in h for h in verdict.hard))

    def test_risicotrigger_met_gedeeld_label_is_hard(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request_target"], gebruikt_gedeeld_label=True),
            ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("pull_request_target" in h for h in verdict.hard))

    def test_risicotrigger_zonder_gedeeld_label_is_zacht(self):
        verdict = trust_scope.classify(
            self._inv(risky_triggers=["pull_request"], gebruikt_gedeeld_label=False), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("pull_request" in z for z in verdict.soft))

    def test_ontbrekende_branch_protection_bij_gedeeld_label_is_zacht(self):
        verdict = trust_scope.classify(
            self._inv(gebruikt_gedeeld_label=True, branch_protection=[]), ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("branch-protection" in z for z in verdict.soft))

    def test_nieuwe_repo_zonder_actions_is_zacht(self):
        inv = self._inv()
        inv["repositories"].append({
            "full_name": "janpeter/nieuw", "has_actions": False, "workflow_source": None,
            "writers": [], "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [], "default_branch": "main", "unreadable": [],
        })
        verdict = trust_scope.classify(inv, ALLOWLIST)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("janpeter/nieuw" in z for z in verdict.soft))

    def test_nieuwe_repo_met_actions_is_hard(self):
        inv = self._inv()
        inv["repositories"].append({
            "full_name": "janpeter/nieuw", "has_actions": True,
            "workflow_source": ".forgejo/workflows", "writers": [],
            "risky_triggers": [], "gebruikt_gedeeld_label": False,
            "branch_protection": [], "default_branch": "main", "unreadable": [],
        })
        verdict = trust_scope.classify(inv, ALLOWLIST)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("janpeter/nieuw" in h for h in verdict.hard))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_trust_scope.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trust_scope'`.

- [ ] **Step 3: Schrijf de implementatie**

```python
# forgejo-runner/scripts/trust_scope.py
"""Trustscope-inventarisatie en -classificatie volgens 7.7 van het migratieontwerp.

Fail-closed: alles wat niet ondubbelzinnig uitleesbaar is, telt als onleesbaar
en maakt het oordeel rood. De module doet zelf geen netwerk-IO; de client wordt
ingespoten, zodat de tests geen echte instance nodig hebben.
"""

from dataclasses import dataclass, field

RISKY_TRIGGERS = ("pull_request_target", "pull_request", "workflow_run")
FORGEJO_WORKFLOWS = ".forgejo/workflows"
GITHUB_WORKFLOWS = ".github/workflows"
WORKFLOW_SUFFIXEN = (".yml", ".yaml")


class Unreadable(Exception):
    """Een object bestaat mogelijk wel maar is niet ondubbelzinnig te lezen."""


@dataclass
class Verdict:
    hard: list = field(default_factory=list)
    soft: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.hard and not self.unreadable


def _workflow_source(client, full_name):
    """Forgejo gebruikt .forgejo/workflows en valt anders terug op .github/workflows."""
    for path in (FORGEJO_WORKFLOWS, GITHUB_WORKFLOWS):
        listing = client.contents(full_name, path)
        if listing:
            return path, listing
    return None, []


BEKENDE_TEAMROLLEN = ("none", "read", "write", "admin", "owner")


def _valideer_repo(repo):
    """Fail-closed validatie van de repository-objectvorm.

    Een ontbrekend veld is geen "nee" maar een onvolledige meting. Zonder deze
    check zou een ontbrekende `has_actions` de hele inspectie overslaan en een
    ontbrekende `owner.login` de meest bevoorrechte identiteit onzichtbaar maken.
    """
    naam = repo.get("full_name")
    if not naam:
        raise Unreadable("repository zonder full_name in de zoekrespons")
    if not isinstance(repo.get("has_actions"), bool):
        raise Unreadable(f"{naam}: has_actions ontbreekt of is geen boolean")
    if not (repo.get("owner") or {}).get("login"):
        raise Unreadable(f"{naam}: owner.login ontbreekt")
    if not repo.get("default_branch"):
        raise Unreadable(f"{naam}: default_branch ontbreekt")
    return naam


def _decodeer(entry):
    """Leest de inhoud van een ContentsResponse. Alles wat niet ondubbelzinnig
    te decoderen is, is onleesbaar en dus fail-closed."""
    import base64
    inhoud = entry.get("content")
    if inhoud is None:
        raise Unreadable(f"{entry.get('path')}: geen content in de respons")
    if "encoding" not in entry:
        # Een ontbrekend veld is iets anders dan "ondubbelzinnig platte tekst".
        # Base64 die als platte tekst wordt gescand bevat geen triggernamen en
        # zou de repository ten onrechte schoon verklaren — onder-detectie is
        # precies de gevaarlijke faalrichting.
        raise Unreadable(f"{entry.get('path')}: encoding-veld ontbreekt")
    codering = (entry.get("encoding") or "").lower()
    if codering == "base64":
        try:
            return base64.b64decode(inhoud).decode("utf-8", errors="strict")
        except Exception as exc:
            raise Unreadable(f"{entry.get('path')}: base64 niet te decoderen: {exc}") from exc
    if codering in ("", "utf-8", "plain"):
        return inhoud
    raise Unreadable(f"{entry.get('path')}: onbekende encoding {codering!r}")


def scan_workflow(tekst, shared_labels):
    """Conservatieve detectie van risicovolle triggers en gedeeld-labelgebruik.

    Bewust geen YAML-parser: er is er geen beschikbaar zonder externe dependency,
    en een half-werkende parser is gevaarlijker dan overgevoelige detectie.
    Over-detectie kost hooguit een handmatige goedkeuring in de allowlist;
    onder-detectie laat onbetrouwbare code toe. Daarom een tekstscan die eerder
    te veel dan te weinig markeert.
    """
    gevonden = []
    for trigger in RISKY_TRIGGERS:
        if trigger in tekst and trigger not in gevonden:
            # pull_request_target bevat pull_request; alleen de langste telt.
            if trigger == "pull_request" and "pull_request_target" in gevonden:
                continue
            gevonden.append(trigger)
    gebruikt_label = any(label and label in tekst for label in shared_labels)
    return gevonden, gebruikt_label


ROLLEN_MET_SCHRIJFRECHT = ("owner", "admin", "write")


def _schrijvers(client, full_name, owner_login=None):
    """Iedere identiteit met schrijfrecht op de workflowbestanden van deze
    repository: de eigenaar, collaborators en teamleden.

    De eigenaar staat er expliciet bij omdat Forgejo hem niet in de
    collaboratorlijst opneemt. Zonder die regel zou juist de meest bevoorrechte
    identiteit onzichtbaar blijven voor de allowlist.

    `/repos/{owner}/{repo}/collaborators/{c}/permission` levert
    `RepoCollaboratorPermission`: `permission` (string), `role_name` (string) en
    `user`. Het is dus geen booleanmap; de rol wordt als string vergeleken.
    """
    schrijvers = set()

    if not owner_login:
        # De aanroepplek geeft entry["owner"] altijd mee en _valideer_repo heeft
        # die al gecontroleerd; een lege waarde betekent dus een onvolledige meting.
        raise Unreadable(f"{full_name}: eigenaar niet vastgesteld")
    schrijvers.add(owner_login)

    collabs = client.collaborators(full_name)
    if collabs is None:
        raise Unreadable(f"{full_name}: collaboratorlijst niet uitleesbaar")
    for collab in collabs:
        login = collab.get("login")
        if not login:
            raise Unreadable(f"{full_name}: collaborator zonder login in de respons")
        perm = client.collaborator_permission(full_name, login)
        # De permissierespons is de beslissende meting voor deze identiteit.
        # Ontbreekt hij of mist hij beide rolvelden, dan is dat onleesbaar en
        # nooit "geen schrijfrecht": dat zou de collaborator stil uit writers
        # laten verdwijnen.
        if perm is None or not (perm.get("permission") or perm.get("role_name")):
            raise Unreadable(
                f"{full_name}: permissie van collaborator {login} niet uitleesbaar")
        rol = str(perm.get("permission") or perm.get("role_name")).lower()
        if rol in ROLLEN_MET_SCHRIJFRECHT:
            schrijvers.add(login)

    teams = client.teams(full_name)
    if teams is None:
        raise Unreadable(f"{full_name}: teamlijst niet uitleesbaar")
    for team in teams:
        team_id = team.get("id")
        rol = str(team.get("permission") or "").lower()
        if team_id is None:
            raise Unreadable(f"{full_name}: team zonder id in de respons")
        if rol not in BEKENDE_TEAMROLLEN:
            # Ontbrekend of onbekend: geen meting, dus geen "geen schrijver".
            raise Unreadable(
                f"{full_name}: team {team_id} heeft geen uitleesbare permission")
        if rol not in ROLLEN_MET_SCHRIJFRECHT:
            continue
        leden = client.team_members(team_id)
        if leden is None:
            raise Unreadable(f"{full_name}: leden van team {team_id} niet uitleesbaar")
        for lid in leden:
            login = lid.get("login")
            if not login:
                raise Unreadable(f"{full_name}: teamlid zonder login in team {team_id}")
            schrijvers.add(login)

    return sorted(schrijvers)


def inventory(client, shared_labels=()):
    repositories = []
    unreadable = []

    for repo in client.repos():
        try:
            full_name = _valideer_repo(repo)
        except Unreadable as exc:
            # Fail-closed: het oordeel wordt hierdoor rood, en de overige
            # repositories worden nog wel gemeten zodat het beeld compleet is.
            unreadable.append(str(exc))
            continue
        entry = {
            "full_name": full_name,
            "has_actions": bool(repo.get("has_actions")),
            "private": bool(repo.get("private")),
            "internal": bool(repo.get("internal")),
            "fork": bool(repo.get("fork")),
            "default_branch": repo.get("default_branch"),
            "owner": (repo.get("owner") or {}).get("login"),
            "workflow_source": None,
            "workflows": [],
            "risky_triggers": [],
            "gebruikt_gedeeld_label": False,
            "writers": [],
            "branch_protection": None,
            "unreadable": [],
        }

        if entry["has_actions"]:
            listing = []
            try:
                entry["workflow_source"], listing = _workflow_source(client, full_name)
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

            for item in listing or []:
                naam = item.get("name", "")
                if item.get("type") != "file" or not naam.endswith(WORKFLOW_SUFFIXEN):
                    continue
                pad = item.get("path") or f"{entry['workflow_source']}/{naam}"
                entry["workflows"].append(pad)
                try:
                    bestand = client.contents(full_name, pad)
                    if isinstance(bestand, list) or bestand is None:
                        raise Unreadable(f"{full_name}:{pad}: geen bestandsrespons")
                    triggers, gebruikt = scan_workflow(_decodeer(bestand), shared_labels)
                except Unreadable as exc:
                    entry["unreadable"].append(str(exc))
                    continue
                for trigger in triggers:
                    if trigger not in entry["risky_triggers"]:
                        entry["risky_triggers"].append(trigger)
                entry["gebruikt_gedeeld_label"] = entry["gebruikt_gedeeld_label"] or gebruikt

            try:
                entry["writers"] = _schrijvers(client, full_name, entry["owner"])
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

            try:
                regels = client.branch_protections(full_name)
                if regels is None:
                    raise Unreadable(f"{full_name}: branch-protection niet uitleesbaar")
                entry["branch_protection"] = [
                    r for r in regels
                    if r.get("branch_name") == entry["default_branch"]
                    or r.get("rule_name") == entry["default_branch"]
                ]
            except Unreadable as exc:
                entry["unreadable"].append(str(exc))

        unreadable.extend(entry["unreadable"])
        repositories.append(entry)

    return {"repositories": repositories, "unreadable": unreadable}


def classify(inv, allowlist):
    """Splitst afwijkingen in hard en zacht volgens 7.7."""
    verdict = Verdict()
    verdict.unreadable.extend(inv.get("unreadable", []))

    approved_repos = {r["full_name"]: r for r in allowlist.get("repositories", [])}
    approved_identities = {i["name"] for i in allowlist.get("identities", [])}

    for repo in inv["repositories"]:
        name = repo["full_name"]
        entry = approved_repos.get(name)

        if entry is None:
            if repo["has_actions"]:
                verdict.hard.append(
                    f"{name}: Actions staat aan maar de repository staat niet in de allowlist")
            else:
                verdict.soft.append(
                    f"{name}: nieuwe repository zonder Actions; binnen 24 uur beoordelen")
            continue

        if repo["has_actions"] and not entry.get("actions_enabled"):
            verdict.hard.append(
                f"{name}: Actions staat aan terwijl de allowlist uitgaat van uit")

        for writer in repo.get("writers", []):
            if writer not in approved_identities:
                verdict.hard.append(
                    f"{name}: niet-goedgekeurde workflow-schrijver {writer}")

        for trigger in repo.get("risky_triggers", []):
            if repo.get("gebruikt_gedeeld_label"):
                verdict.hard.append(
                    f"{name}: trigger {trigger} in een workflow die een gedeeld runnerlabel "
                    f"gebruikt; onbetrouwbare code kan zo op de pool starten")
            else:
                verdict.soft.append(
                    f"{name}: trigger {trigger} aanwezig maar zonder gedeeld runnerlabel; "
                    f"binnen 24 uur beoordelen")

        if repo["has_actions"] and repo["workflow_source"] is None:
            verdict.soft.append(
                f"{name}: Actions staat aan maar er is geen workflowmap gevonden")

        if repo.get("gebruikt_gedeeld_label") and not repo.get("branch_protection"):
            verdict.soft.append(
                f"{name}: gebruikt de gedeelde labels maar heeft geen branch-protection "
                f"op {repo.get('default_branch')}; binnen 24 uur beoordelen")

    return verdict
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_trust_scope.py' -v`
Expected: PASS — 42 tests, 0 failures.

- [ ] **Step 5: Bevestig dat de logica geen netwerk raakt**

Run: `grep -nE "urllib|requests|socket|http" forgejo-runner/scripts/trust_scope.py`
Expected: geen treffer. `trust_scope.py` mag geen IO doen; alle netwerkcode hoort in `trust_scope_cli.py`.

- [ ] **Step 6: Schrijf de netwerkclient en de CLI**

`trust_scope.py` doet bewust geen IO. Deze module levert de echte client en vertaalt het oordeel naar exitcodes. De allowlist is YAML, maar bewust een strikte deelverzameling — sleutel-waardeparen, lijsten met streepjes, geen ankers of blokstijl — zodat hij zonder `yq` of PyYAML leesbaar is; `yq` is op geen van de machines aanwezig.

```python
# forgejo-runner/scripts/trust_scope_cli.py
"""Netwerkclient en CLI voor de trustscope-gate.

Exitcodes: 0 groen, 10 zachte afwijking, 20 harde afwijking, 30 onleesbaar.
"""

import argparse, json, os, sys, urllib.error, urllib.request

import trust_scope
from trust_scope import Unreadable


class ForgejoClient:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.token = token

    def _get(self, path, params=None, *, missing_ok=False):
        """Haalt een API-pad op. Een 404 is standaard NIET normaal.

        Alleen bij het aftasten van de twee workflowmappen is afwezigheid een
        geldige uitkomst; daar geldt `missing_ok=True`. Overal elders zou een
        404 stil "geen collaborators", "geen teams" of "geen branch-protection"
        betekenen, en dat is fail-open in een gate die volgens 7.7 fail-closed
        moet zijn.
        """
        url = f"{self.base}/api/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"token {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing_ok:
                return None
            raise Unreadable(f"{path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, ValueError) as exc:
            raise Unreadable(f"{path}: {exc}") from exc

    def repos(self):
        """Alle zichtbare repositories, gepagineerd.

        Een onverwachte vorm is hier extra gevaarlijk: een stilzwijgend lege
        lijst betekent "niets te toetsen" en zou de trustgate groen maken
        zonder een enkele repository te hebben gemeten.
        """
        out, page = [], 1
        while True:
            data = self._get("/repos/search", {"limit": 50, "page": page})
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise Unreadable(f"/repos/search pagina {page}: onverwachte respons")
            items = data["data"]
            out.extend(items)
            if len(items) < 50:
                return out
            page += 1

    def contents(self, full_name, path):
        # De enige plek waar een 404 een geldige uitkomst is: de workflowmap
        # bestaat niet en de fallback moet worden geprobeerd.
        return self._get(f"/repos/{full_name}/contents/{path}", missing_ok=True)

    # Hieronder is een 404 nooit normaal: die maakt de meting onvolledig en
    # moet de gate rood maken in plaats van een lege verzameling te leveren.
    def collaborators(self, full_name):
        return self._get(f"/repos/{full_name}/collaborators")

    def collaborator_permission(self, full_name, login):
        return self._get(f"/repos/{full_name}/collaborators/{login}/permission")

    def teams(self, full_name):
        return self._get(f"/repos/{full_name}/teams")

    def team_members(self, team_id):
        return self._get(f"/teams/{team_id}/members")

    def branch_protections(self, full_name):
        return self._get(f"/repos/{full_name}/branch_protections")


def load_allowlist(path):
    """Leest de strikte YAML-deelverzameling van trusted-actions-scope.yml."""
    doc = {"identities": [], "repositories": [], "approved_by": "", "approved_at": ""}
    section, current = None, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        text = line.strip()
        if indent == 0 and text.endswith(":"):
            section = text[:-1]
            continue
        if indent == 0 and ":" in text:
            key, _, value = text.partition(":")
            doc[key.strip()] = value.strip().strip('"')
            section = None
            continue
        if text.startswith("- "):
            current = {}
            doc.setdefault(section, []).append(current)
            text = text[2:].strip()
            if not text:
                continue
        if current is not None and ":" in text:
            key, _, value = text.partition(":")
            value = value.strip().strip('"')
            if value in ("true", "false"):
                value = value == "true"
            elif value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip('"') for v in value[1:-1].split(",") if v.strip()]
            elif value in ("null", "~", ""):
                value = None
            current[key.strip()] = value
    return doc


def load_shared_labels(path):
    """Leest de labelnamen uit labels.txt. Een regel heeft de vorm
    `naam:docker://image@sha256:...`; alleen het deel voor de eerste dubbele punt
    is de labelnaam waarop een workflow `runs-on` kan matchen."""
    namen = []
    for regel in open(path, encoding="utf-8"):
        regel = regel.strip()
        if not regel or regel.startswith("#"):
            continue
        namen.append(regel.split(":", 1)[0])
    return tuple(namen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", required=True)
    ap.add_argument("--labels", required=True,
                    help="pad naar labels.txt; de labelnamen bepalen of een workflow "
                         "de gedeelde pool kan bereiken")
    ap.add_argument("--out", required=True)
    ap.add_argument("--emit-allowlist", action="store_true",
                    help="print een allowlist-voorstel uit de meting en wijzig niets")
    args = ap.parse_args()

    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        print("FORGEJO_TOKEN ontbreekt", file=sys.stderr)
        return 30

    client = ForgejoClient(os.environ.get("FORGEJO_URL", "https://git.jp-visser.nl"), token)
    shared_labels = load_shared_labels(args.labels)
    if not shared_labels:
        print("fail-closed: geen gedeelde labels gelezen uit labels.txt", file=sys.stderr)
        return 30
    try:
        inv = trust_scope.inventory(client, shared_labels)
    except Unreadable as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return 30

    if args.emit_allowlist:
        print("version: 1")
        print('approved_by: ""')
        print('approved_at: ""')
        print("\nidentities:")
        names = sorted({w for r in inv["repositories"] for w in r["writers"]})
        for name in names:
            print(f"  - name: {name}")
        print("\nrepositories:")
        for repo in sorted(inv["repositories"], key=lambda r: r["full_name"]):
            print(f"  - full_name: {repo['full_name']}")
            print(f"    actions_enabled: {str(repo['has_actions']).lower()}")
            source = repo["workflow_source"]
            print(f"    workflow_source: {source if source else 'null'}")
            print(f"    writers: [{', '.join(repo['writers'])}]")
        return 0

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "trust-inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(inv, fh, indent=2, sort_keys=True, ensure_ascii=False)

    allowlist = load_allowlist(args.allowlist)
    if not allowlist.get("approved_by"):
        print("fail-closed: de allowlist is nog niet door JP goedgekeurd", file=sys.stderr)
        return 30

    verdict = trust_scope.classify(inv, allowlist)
    with open(os.path.join(args.out, "trust-verdict.json"), "w", encoding="utf-8") as fh:
        json.dump({"hard": verdict.hard, "soft": verdict.soft,
                   "unreadable": verdict.unreadable, "ok": verdict.ok},
                  fh, indent=2, ensure_ascii=False)

    for item in verdict.unreadable:
        print(f"ONLEESBAAR: {item}", file=sys.stderr)
    for item in verdict.hard:
        print(f"HARD: {item}", file=sys.stderr)
    for item in verdict.soft:
        print(f"ZACHT: {item}", file=sys.stderr)

    if verdict.unreadable:
        return 30
    if verdict.hard:
        return 20
    if verdict.soft:
        return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Voeg bovenaan `trust_scope_cli.py` ook `import urllib.parse` toe; `urllib.request` importeert die niet vanzelf.

- [ ] **Step 7: Schrijf de wrapper die §6 als bundelbestand benoemt**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/verify-trust-scope.sh
# Entry point van de trustscope-gate (7.7). De logica staat in trust_scope.py.
# Exit 0 groen, 10 zachte afwijking, 20 harde afwijking, 30 onleesbaar.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOWLIST="${ALLOWLIST:-$SCRIPT_DIR/../trusted-actions-scope.yml}"
LABELS="${LABELS:-$SCRIPT_DIR/../labels.txt}"
OUT="${1:-}"
[ -n "$OUT" ] || { printf 'gebruik: verify-trust-scope.sh UITVOERMAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt\n' >&2 ; exit 30 ; }

mkdir -p "$OUT"
exec python3 "$SCRIPT_DIR/trust_scope_cli.py" --allowlist "$ALLOWLIST" \
  --labels "$LABELS" --out "$OUT"
```

- [ ] **Step 8: Schrijf de allowlist met de vandaag bekende toestand**

```yaml
# forgejo-runner/trusted-actions-scope.yml
# Expliciete allowlist voor de global-scope runners (7.7 van het migratieontwerp).
# Een identiteit is alleen trusted als JP haar bij naam heeft goedgekeurd.
# Dit bestand wordt in Task 6 step 7 gevuld met de gemeten toestand en daarna
# door JP goedgekeurd. Zolang approved_by leeg is, faalt de gate fail-closed.
version: 1
approved_by: ""
approved_at: ""

identities: []

repositories: []
```

- [ ] **Step 9: Vul de allowlist uit de meting en laat JP hem goedkeuren**

```bash
source ~/.zshenv
EV=docs/forgejo-runner-pool/evidence/stap-a
# De labelnamen komen uit Task 2 step 7; labels.txt uit stap B bestaat nog niet.
LABELS="$EV/shared-label-names.txt" \
  bash forgejo-runner/scripts/verify-trust-scope.sh "$EV/trust" || true
python3 forgejo-runner/scripts/trust_scope_cli.py \
  --allowlist forgejo-runner/trusted-actions-scope.yml \
  --labels "$EV/shared-label-names.txt" \
  --out "$EV/trust" \
  --emit-allowlist > /tmp/voorstel-allowlist.yml
diff forgejo-runner/trusted-actions-scope.yml /tmp/voorstel-allowlist.yml || true
```

Neem het voorstel pas over nadat JP iedere identiteit en iedere Actions-enabled repository bij naam heeft goedgekeurd, en vul dan `approved_by` en `approved_at`. Dit is een menselijke gate: een allowlist die zichzelf goedkeurt is geen allowlist.

De repo's `janpeter/scrum4me-server` en `janpeter/max2` horen hier expliciet bij, elk met hun gemeten `has_actions`-waarde. Staat Actions bij een van beide aan, dan komt de repo als trusted scope in de lijst; staat het uit, dan wordt dat expliciet vastgelegd zodat later inschakelen als drift zichtbaar wordt.

- [ ] **Step 10: Bewijs dat de gate fail-closed is**

```bash
EV=docs/forgejo-runner-pool/evidence/stap-a
FORGEJO_TOKEN="" LABELS="$EV/shared-label-names.txt" \
  bash forgejo-runner/scripts/verify-trust-scope.sh /tmp/leeg ; echo "exit=$?"

# En zonder labelnamen evenmin: dan kan de gate niet bepalen welke workflows de pool bereiken.
LABELS=/dev/null bash forgejo-runner/scripts/verify-trust-scope.sh /tmp/leeg ; echo "exit=$?"
```

Expected: beide aanroepen geven `exit=30`. De gate mag zonder token en zonder labelnamen nooit groen worden.

Na Task 16 draait dezelfde gate nogmaals met `LABELS=forgejo-runner/labels.txt`; de labelnamen daarin moeten identiek zijn aan `shared-label-names.txt`. Wijken ze af, dan is het labelcontract gebroken en is dat een harde bevinding vóór stap C.

- [ ] **Step 11: Commit**

```bash
git add forgejo-runner/scripts/trust_scope.py forgejo-runner/scripts/trust_scope_cli.py forgejo-runner/scripts/verify-trust-scope.sh \
        forgejo-runner/trusted-actions-scope.yml forgejo-runner/tests/test_trust_scope.py \
        docs/forgejo-runner-pool/evidence/stap-a/trust/
git commit -m "feat(stap-a): trustscope-gate met has_actions-meting en fail-closed classificatie"
```

---

### Task 7: Representatieve workflow kiezen en meten

§7.8 eist dat de caps uit een **gemeten piek** volgen, niet uit een momentopname: tijdens minimaal één representatieve zwaarste workflow wordt iedere vijf seconden CPU, geheugengebruik en PID-aantal van runner en DinD gemeten, plus `MemAvailable` van de host. §2 voegt daar na delta-review R12 de jobduur aan toe als warme-cachebaseline.

De keuze van "de zwaarste workflow" is mechanisch te maken. Bevestigde endpoints:

| Endpoint | Gebruik |
|---|---|
| `/api/v1/repos/{owner}/{repo}/actions/runs` | historische runs; `ActionRun` bevat `duration`, `started`, `stopped`, `status`, `workflow_id` |
| `/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}` | één run in detail |
| `/api/v1/repos/{owner}/{repo}/actions/workflows/{workflowfilename}/dispatches` | een workflow gericht starten |

**Files:**
- Create: `forgejo-runner/scripts/pick-heaviest-workflow.py`
- Create: `forgejo-runner/scripts/measure-workload.sh`
- Test: `forgejo-runner/tests/test_pick_heaviest_workflow.py`

**Interfaces:**
- Consumes: `trust-inventory.json` uit Task 6 voor de lijst Actions-enabled repositories; `FORGEJO_TOKEN`
- Produces: `heaviest-workflow.json` met `repo`, `workflow_id`, `run_id`, `duration_seconds`; en `workload-<host>.tsv` met per meetmoment `t`, `runner_cpu_pct`, `runner_mem_bytes`, `runner_pids`, `dind_cpu_pct`, `dind_mem_bytes`, `dind_pids`, `mem_available_bytes`.

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_pick_heaviest_workflow.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import pick_heaviest_workflow as p


class TestKiezen(unittest.TestCase):
    def test_kiest_de_langste_geslaagde_run(self):
        runs = {
            "janpeter/app": [
                {"id": 1, "workflow_id": "ci.yml", "status": "success", "duration": 120},
                {"id": 2, "workflow_id": "zwaar.yml", "status": "success", "duration": 900},
            ],
            "janpeter/ander": [
                {"id": 3, "workflow_id": "klein.yml", "status": "success", "duration": 30},
            ],
        }
        keuze = p.pick(runs)
        self.assertEqual(keuze["repo"], "janpeter/app")
        self.assertEqual(keuze["workflow_id"], "zwaar.yml")
        self.assertEqual(keuze["duration_seconds"], 900)

    def test_negeert_mislukte_en_lopende_runs(self):
        runs = {"janpeter/app": [
            {"id": 1, "workflow_id": "kapot.yml", "status": "failure", "duration": 9999},
            {"id": 2, "workflow_id": "loopt.yml", "status": "running", "duration": 8888},
            {"id": 3, "workflow_id": "goed.yml", "status": "success", "duration": 10},
        ]}
        self.assertEqual(p.pick(runs)["workflow_id"], "goed.yml")

    def test_zonder_geslaagde_runs_is_er_geen_keuze(self):
        self.assertIsNone(p.pick({"janpeter/app": [
            {"id": 1, "workflow_id": "x.yml", "status": "failure", "duration": 5}]}))

    def test_duration_als_dict_wordt_ondersteund(self):
        runs = {"janpeter/app": [
            {"id": 1, "workflow_id": "a.yml", "status": "success",
             "duration": {"seconds": 42}}]}
        self.assertEqual(p.pick(runs)["duration_seconds"], 42)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_pick_heaviest_workflow.py' -v`
Expected: FAIL — module bestaat nog niet.

- [ ] **Step 3: Schrijf de keuzelogica**

```python
# forgejo-runner/scripts/pick_heaviest_workflow.py
"""Kiest de zwaarste representatieve workflow uit historische runs.

Zwaarst = de langste succesvol afgeronde run. Mislukte en lopende runs tellen
niet mee: hun duur zegt niets over de werkelijke piekbelasting.
"""

TERMINAAL_GESLAAGD = ("success", "completed")


def _duration_seconds(run):
    raw = run.get("duration")
    if isinstance(raw, dict):
        return int(raw.get("seconds", 0))
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def pick(runs_per_repo):
    beste = None
    for repo, runs in runs_per_repo.items():
        for run in runs:
            if str(run.get("status", "")).lower() not in TERMINAAL_GESLAAGD:
                continue
            duur = _duration_seconds(run)
            if beste is None or duur > beste["duration_seconds"]:
                beste = {
                    "repo": repo,
                    "workflow_id": run.get("workflow_id"),
                    "run_id": run.get("id"),
                    "duration_seconds": duur,
                }
    return beste
```

Let op: het CLI-deel dat de runs ophaalt hoort in `pick-heaviest-workflow.py` (met streepjes), dat `pick_heaviest_workflow` importeert en `GET /api/v1/repos/{repo}/actions/runs` aanroept met dezelfde `ForgejoClient` als Task 6. De logica blijft IO-vrij zodat de tests geen instance nodig hebben.

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_pick_heaviest_workflow.py' -v`
Expected: PASS — 4 tests, 0 failures.

- [ ] **Step 5: Schrijf de meetlus**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/measure-workload.sh
# Meet iedere vijf seconden het gebruik van runner en DinD plus MemAvailable.
# Read-only: docker stats leest alleen. Draait OP de host tijdens de workflow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

RUNNER="" ; DIND="" ; OUT="" ; SECONDS_TOTAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --runner)  RUNNER="$2"        ; shift 2 ;;
    --dind)    DIND="$2"          ; shift 2 ;;
    --out)     OUT="$2"           ; shift 2 ;;
    --seconds) SECONDS_TOTAL="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$RUNNER" ] && [ -n "$DIND" ] && [ -n "$OUT" ] && [ "$SECONDS_TOTAL" -gt 0 ] || {
  printf 'gebruik: --runner NAAM --dind NAAM --out BESTAND --seconds N\n' >&2 ; exit 2 ; }

printf 't\trunner_cpu_pct\trunner_mem_bytes\trunner_pids\tdind_cpu_pct\tdind_mem_bytes\tdind_pids\tmem_available_bytes\n' > "$OUT"

sample_container() {
  # CPUPerc, MemUsage en PIDs in een keer; --no-stream leest een momentopname.
  ro_docker stats --no-stream --format '{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' "$1" 2>/dev/null || printf '0%%\t0B / 0B\t0\n'
}

t=0
while [ "$t" -lt "$SECONDS_TOTAL" ]; do
  R="$(sample_container "$RUNNER")"
  D="$(sample_container "$DIND")"
  MEMAV="$(awk '/MemAvailable/{print $2 * 1024; exit}' /proc/meminfo)"
  printf '%s\t%s\t%s\t%s\n' "$t" \
    "$(printf '%s' "$R" | python3 -c '
import sys
cpu, mem, pids = sys.stdin.read().rstrip("\n").split("\t")
def to_bytes(s):
    s = s.split("/")[0].strip()
    units = {"B":1,"KiB":1024,"MiB":1024**2,"GiB":1024**3,"kB":1000,"MB":1000**2,"GB":1000**3}
    for unit, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.endswith(unit):
            return int(float(s[:-len(unit)]) * factor)
    return 0
print("%s\t%d\t%s" % (cpu.rstrip("%"), to_bytes(mem), pids))
')" \
    "$(printf '%s' "$D" | python3 -c '
import sys
cpu, mem, pids = sys.stdin.read().rstrip("\n").split("\t")
def to_bytes(s):
    s = s.split("/")[0].strip()
    units = {"B":1,"KiB":1024,"MiB":1024**2,"GiB":1024**3,"kB":1000,"MB":1000**2,"GB":1000**3}
    for unit, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.endswith(unit):
            return int(float(s[:-len(unit)]) * factor)
    return 0
print("%s\t%d\t%s" % (cpu.rstrip("%"), to_bytes(mem), pids))
')" \
    "$MEMAV" >> "$OUT"
  sleep 5
  t=$((t + 5))
done

printf 'meetreeks geschreven naar %s\n' "$OUT"
```

- [ ] **Step 6: Kies de workflow en meet hem echt**

```bash
source ~/.zshenv
EV=docs/forgejo-runner-pool/evidence/stap-a
python3 forgejo-runner/scripts/pick-heaviest-workflow.py \
  --inventory "$EV/trust/trust-inventory.json" --out "$EV/heaviest-workflow.json"
cat "$EV/heaviest-workflow.json"
```

Start daarna die workflow (via de Forgejo-UI of `POST /api/v1/repos/{owner}/{repo}/actions/workflows/{workflowfilename}/dispatches`) en draai tegelijk de meetlus met een `--seconds` die ruim boven de historische duur ligt:

```bash
ssh janpeter@scrum4me-srv 'mkdir -p /tmp/s4m-capture/scripts/lib'
scp forgejo-runner/scripts/measure-workload.sh janpeter@scrum4me-srv:/tmp/s4m-capture/scripts/
scp forgejo-runner/scripts/lib/readonly.sh janpeter@scrum4me-srv:/tmp/s4m-capture/scripts/lib/
ssh janpeter@scrum4me-srv 'bash /tmp/s4m-capture/scripts/measure-workload.sh \
  --runner scrum4me-forgejo-runner --dind scrum4me-forgejo-dind \
  --out /tmp/s4m-capture/workload-scrum4me-server.tsv --seconds 1800'
scp janpeter@scrum4me-srv:/tmp/s4m-capture/workload-scrum4me-server.tsv "$EV/"
```

Expected: een TSV met ten minste één regel per vijf seconden over de hele looptijd van de workflow, met plausibele niet-nul waarden voor beide containers.

- [ ] **Step 7: Leg de jobduurbaseline vast**

Noteer in `$EV/jobduur-baseline.md` de wandkloktijd van de gemeten job met de huidige **warme** DinD-cache, met de `run_id` en het commando waarmee je hem hebt opgehaald. §9 zet de cacheloze pool tegen deze waarde af met een grens van 200%; zonder deze meting is dat criterium niet toetsbaar.

- [ ] **Step 8: Commit**

```bash
git add forgejo-runner/scripts/pick_heaviest_workflow.py \
        forgejo-runner/scripts/pick-heaviest-workflow.py \
        forgejo-runner/scripts/measure-workload.sh \
        forgejo-runner/tests/test_pick_heaviest_workflow.py \
        docs/forgejo-runner-pool/evidence/stap-a/
git commit -m "feat(stap-a): representatieve workflow kiezen en piekgebruik meten"
```

---

### Task 8: Hostfeiten van beide machines

Delta-review R12 voegde toe dat `max2` niet ongemeten mag blijven terwijl de caps daar gelijk gelden. Deze taak levert de vier waarden waarop `preflight.sh` in Task 10 toetst.

De vandaag gemeten uitgangswaarden staan in "Gemeten omgevingsfeiten" bovenaan dit plan: `scrum4me-server` 8 vCPU en 15,0 GiB, `max2` 28 vCPU en 30,6 GiB. Deze taak meet ze opnieuw en voegt de laagste `MemAvailable` onder eigen productielast en de schijf- en inodesituatie toe.

**Files:**
- Create: `forgejo-runner/scripts/capture-host-facts.sh`
- Test: `forgejo-runner/tests/test_capture_host_facts.bats`

**Interfaces:**
- Consumes: niets
- Produces: `host-facts-<host>.tsv` met de sleutels `vcpu`, `mem_total_bytes`, `mem_available_bytes`, `docker_root_dir`, `docker_root_free_bytes`, `docker_root_free_pct`, `docker_root_free_inodes_pct`.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_capture_host_facts.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/capture-host-facts.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/docker" <<'EOS'
#!/usr/bin/env bash
echo "/var/lib/docker"
EOS
  cat > "$FAKE_BIN/nproc" <<'EOS'
#!/usr/bin/env bash
echo 28
EOS
  chmod +x "$FAKE_BIN"/*
  PATH="$FAKE_BIN:$PATH"
}

@test "schrijft alle zeven sleutels" {
  out="$BATS_TEST_TMPDIR/facts.tsv"
  run bash "$SCRIPT" --out "$out"
  [ "$status" -eq 0 ]
  for k in vcpu mem_total_bytes mem_available_bytes docker_root_dir \
           docker_root_free_bytes docker_root_free_pct docker_root_free_inodes_pct; do
    grep -q "^$k	" "$out" || { echo "ontbreekt: $k"; false; }
  done
}

@test "vcpu komt uit nproc" {
  out="$BATS_TEST_TMPDIR/facts.tsv"
  bash "$SCRIPT" --out "$out"
  grep -q "^vcpu	28$" "$out"
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_capture_host_facts.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/capture-host-facts.sh
# Legt de hostfeiten vast waarop preflight.sh toetst. Read-only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { printf 'gebruik: capture-host-facts.sh --out BESTAND\n' >&2 ; exit 2 ; }

ROOT="$(ro_docker info --format '{{.DockerRootDir}}')"

{
  printf 'vcpu\t%s\n' "$(nproc)"
  printf 'mem_total_bytes\t%s\n' "$(awk '/MemTotal/{print $2 * 1024; exit}' /proc/meminfo)"
  printf 'mem_available_bytes\t%s\n' "$(awk '/MemAvailable/{print $2 * 1024; exit}' /proc/meminfo)"
  printf 'docker_root_dir\t%s\n' "$ROOT"
  printf 'docker_root_free_bytes\t%s\n' "$(df -B1 --output=avail "$ROOT" | tail -1 | tr -d ' ')"
  printf 'docker_root_free_pct\t%s\n' "$(df --output=pcent "$ROOT" | tail -1 | tr -d ' %' | awk '{print 100 - $1}')"
  printf 'docker_root_free_inodes_pct\t%s\n' "$(df --output=ipcent "$ROOT" | tail -1 | tr -d ' %' | awk '{print 100 - $1}')"
} > "$OUT"

printf 'hostfeiten geschreven naar %s\n' "$OUT"
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_capture_host_facts.bats`
Expected: PASS — 2 tests, 0 failures.

- [ ] **Step 5: Meet beide hosts, `max2` onder eigen productielast**

```bash
EV=docs/forgejo-runner-pool/evidence/stap-a
for H in scrum4me-srv max2; do
  ssh "janpeter@$H" 'mkdir -p /tmp/s4m-capture/scripts/lib'
  scp forgejo-runner/scripts/capture-host-facts.sh "janpeter@$H:/tmp/s4m-capture/scripts/"
  scp forgejo-runner/scripts/lib/readonly.sh "janpeter@$H:/tmp/s4m-capture/scripts/lib/"
  ssh "janpeter@$H" "bash /tmp/s4m-capture/scripts/capture-host-facts.sh \
    --out /tmp/s4m-capture/host-facts-\$(hostname).tsv"
done
scp janpeter@scrum4me-srv:/tmp/s4m-capture/host-facts-scrum4me-server.tsv "$EV/"
scp janpeter@max2:/tmp/s4m-capture/host-facts-max2.tsv "$EV/"
```

Op `max2` draaien blijkens de meting van 31 augustus onder meer `scrum4me-agent-codex`, twee worker-idea-containers, `scrum4me-caddy`, `scrum4me-postgres`, `media-organizer-web`, `media-organizer-postgres`, `scrum4me-ops-dashboard`, `scrum4me-workers`, `tei-gpu` en `scraper`. Meet daarom op een moment dat die last representatief is, niet op een stil moment; noteer bij de meting wat er draaide.

Expected: `vcpu` 8 op `scrum4me-server` en 28 op `max2`; wijkt dat af van de waarden bovenaan dit plan, dan is de hostconfiguratie veranderd en moet dat vóór stap B worden uitgezocht.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/capture-host-facts.sh \
        forgejo-runner/tests/test_capture_host_facts.bats \
        docs/forgejo-runner-pool/evidence/stap-a/
git commit -m "feat(stap-a): hostfeiten van beide machines vastleggen"
```

---

### Task 9: Caps berekenen uit de meetreeks

§7.8 legt de rekenregel exact vast. De limiet per service is de **hoogste** van twee waarden:

- de ondergrens — runner: 1 vCPU, 1 GiB, 256 PID; DinD: 2 vCPU, 4 GiB, 2048 PID;
- 150% van de gemeten piek, naar boven afgerond op 0,5 vCPU, 256 MiB en 128 PID.

Daarna geldt de headroomgate: de som van de geheugenlimieten mag niet boven 50% van de **laagste gemeten** `MemAvailable`, en de som van de CPU-limieten niet boven 50% van de aanwezige vCPU's. Na delta-review R12 geldt die gate op **beide** hosts.

**Files:**
- Create: `forgejo-runner/scripts/compute_caps.py`
- Test: `forgejo-runner/tests/test_compute_caps.py`

**Interfaces:**
- Consumes: `workload-<host>.tsv` uit Task 7 en `host-facts-<host>.tsv` uit Task 8
- Produces: `compute_caps.compute(samples) -> Caps` met velden `runner_cpu`, `runner_mem_bytes`, `runner_pids`, `dind_cpu`, `dind_mem_bytes`, `dind_pids`, en `compute_caps.headroom_ok(caps, vcpu, lowest_mem_available) -> tuple[bool, list[str]]`.

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_compute_caps.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import compute_caps

GIB = 1024 ** 3
MIB = 1024 ** 2


def sample(rc, rm, rp, dc, dm, dp, memav):
    return {"runner_cpu_pct": rc, "runner_mem_bytes": rm, "runner_pids": rp,
            "dind_cpu_pct": dc, "dind_mem_bytes": dm, "dind_pids": dp,
            "mem_available_bytes": memav}


class TestOndergrens(unittest.TestCase):
    def test_lichte_belasting_valt_terug_op_de_ondergrens(self):
        caps = compute_caps.compute([sample(5, 100 * MIB, 10, 10, 200 * MIB, 20, 8 * GIB)])
        self.assertEqual(caps.runner_cpu, 1.0)
        self.assertEqual(caps.runner_mem_bytes, 1 * GIB)
        self.assertEqual(caps.runner_pids, 256)
        self.assertEqual(caps.dind_cpu, 2.0)
        self.assertEqual(caps.dind_mem_bytes, 4 * GIB)
        self.assertEqual(caps.dind_pids, 2048)


class TestPiek(unittest.TestCase):
    def test_gebruikt_150_procent_van_de_piek_en_rondt_af(self):
        # DinD-piek: 300% CPU = 3 vCPU -> 4,5 vCPU; 6 GiB -> 9 GiB -> afronden op 256 MiB
        caps = compute_caps.compute([
            sample(10, 100 * MIB, 10, 100, 2 * GIB, 100, 8 * GIB),
            sample(20, 200 * MIB, 20, 300, 6 * GIB, 3000, 8 * GIB),
        ])
        self.assertEqual(caps.dind_cpu, 4.5)
        self.assertEqual(caps.dind_mem_bytes, 9 * GIB)
        self.assertEqual(caps.dind_pids, 4608)

    def test_rondt_cpu_naar_boven_af_op_een_half(self):
        caps = compute_caps.compute([sample(140, 100 * MIB, 10, 10, 200 * MIB, 20, 8 * GIB)])
        # 1,4 vCPU * 1,5 = 2,1 -> 2,5
        self.assertEqual(caps.runner_cpu, 2.5)


class TestHeadroom(unittest.TestCase):
    def _caps(self):
        return compute_caps.Caps(runner_cpu=1.0, runner_mem_bytes=1 * GIB, runner_pids=256,
                                 dind_cpu=2.0, dind_mem_bytes=4 * GIB, dind_pids=2048)

    def test_ruime_host_is_groen(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=28, lowest_mem_available=20 * GIB)
        self.assertTrue(ok)
        self.assertEqual(redenen, [])

    def test_te_weinig_geheugen_is_rood(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=28, lowest_mem_available=6 * GIB)
        self.assertFalse(ok)
        self.assertTrue(any("geheugen" in r for r in redenen))

    def test_te_weinig_vcpu_is_rood(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=4, lowest_mem_available=20 * GIB)
        self.assertFalse(ok)
        self.assertTrue(any("vCPU" in r for r in redenen))

    def test_precies_op_de_helft_is_nog_groen(self):
        caps = compute_caps.Caps(runner_cpu=1.0, runner_mem_bytes=1 * GIB, runner_pids=256,
                                 dind_cpu=3.0, dind_mem_bytes=4 * GIB, dind_pids=2048)
        ok, _ = compute_caps.headroom_ok(caps, vcpu=8, lowest_mem_available=10 * GIB)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_compute_caps.py' -v`
Expected: FAIL — module bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```python
# forgejo-runner/scripts/compute_caps.py
"""Berekent de resourcecaps volgens 7.8 van het migratieontwerp.

Limiet per service = max(ondergrens, 150% van de gemeten piek), waarbij de piek
naar boven wordt afgerond op 0,5 vCPU, 256 MiB en 128 PID. De headroomgate
geldt na delta-review R12 op beide hosts.
"""

import math
from dataclasses import dataclass

GIB = 1024 ** 3
MIB = 1024 ** 2

ONDERGRENS = {
    "runner": {"cpu": 1.0, "mem": 1 * GIB, "pids": 256},
    "dind": {"cpu": 2.0, "mem": 4 * GIB, "pids": 2048},
}
MARGE = 1.5
STAP_CPU = 0.5
STAP_MEM = 256 * MIB
STAP_PIDS = 128


@dataclass
class Caps:
    runner_cpu: float
    runner_mem_bytes: int
    runner_pids: int
    dind_cpu: float
    dind_mem_bytes: int
    dind_pids: int


def _omhoog(waarde, stap):
    return math.ceil(waarde / stap) * stap


def _voor_service(samples, prefix, ondergrens):
    piek_cpu = max((float(s[f"{prefix}_cpu_pct"]) for s in samples), default=0.0) / 100.0
    piek_mem = max((int(s[f"{prefix}_mem_bytes"]) for s in samples), default=0)
    piek_pids = max((int(s[f"{prefix}_pids"]) for s in samples), default=0)
    return (
        max(ondergrens["cpu"], _omhoog(piek_cpu * MARGE, STAP_CPU)),
        int(max(ondergrens["mem"], _omhoog(piek_mem * MARGE, STAP_MEM))),
        int(max(ondergrens["pids"], _omhoog(piek_pids * MARGE, STAP_PIDS))),
    )


def compute(samples):
    r_cpu, r_mem, r_pids = _voor_service(samples, "runner", ONDERGRENS["runner"])
    d_cpu, d_mem, d_pids = _voor_service(samples, "dind", ONDERGRENS["dind"])
    return Caps(runner_cpu=r_cpu, runner_mem_bytes=r_mem, runner_pids=r_pids,
                dind_cpu=d_cpu, dind_mem_bytes=d_mem, dind_pids=d_pids)


def headroom_ok(caps, vcpu, lowest_mem_available):
    redenen = []
    cpu_som = caps.runner_cpu + caps.dind_cpu
    mem_som = caps.runner_mem_bytes + caps.dind_mem_bytes
    if cpu_som > vcpu * 0.5:
        redenen.append(
            f"vCPU: som van de limieten {cpu_som} overschrijdt 50% van {vcpu} vCPU")
    if mem_som > lowest_mem_available * 0.5:
        redenen.append(
            f"geheugen: som van de limieten {mem_som} bytes overschrijdt 50% van de "
            f"laagste MemAvailable {lowest_mem_available} bytes")
    return (not redenen), redenen
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_compute_caps.py' -v`
Expected: PASS — 7 tests, 0 failures.

- [ ] **Step 5: Bereken de caps uit de echte meting en gate beide hosts**

```bash
EV=docs/forgejo-runner-pool/evidence/stap-a
python3 - <<'PY' > "$EV/caps.md"
import csv, pathlib, sys
sys.path.insert(0, "forgejo-runner/scripts")
import compute_caps

ev = pathlib.Path("docs/forgejo-runner-pool/evidence/stap-a")
samples = list(csv.DictReader(open(ev / "workload-scrum4me-server.tsv"), delimiter="\t"))
caps = compute_caps.compute(samples)
laagste_memav = min(int(s["mem_available_bytes"]) for s in samples)

print("# Berekende caps (7.8)\n")
print(f"- laagste gemeten MemAvailable: {laagste_memav} bytes\n")
print("| Service | CPU | Geheugen | PIDs |")
print("|---|---|---|---|")
print(f"| runner | {caps.runner_cpu} | {caps.runner_mem_bytes} | {caps.runner_pids} |")
print(f"| dind | {caps.dind_cpu} | {caps.dind_mem_bytes} | {caps.dind_pids} |")
print("\n## Headroomgate per host\n")
for host, facts in (("scrum4me-server", ev / "host-facts-scrum4me-server.tsv"),
                    ("max2", ev / "host-facts-max2.tsv")):
    f = dict(l.rstrip("\n").split("\t", 1) for l in open(facts))
    ok, redenen = compute_caps.headroom_ok(caps, int(f["vcpu"]), laagste_memav)
    print(f"- **{host}**: {'GROEN' if ok else 'ROOD'}")
    for r in redenen:
        print(f"  - {r}")
PY
cat "$EV/caps.md"
```

Expected: beide hosts GROEN. Is een host ROOD, dan is dat volgens §7.8 een NO-GO voor identieke caps en stopt stap A hier. Lagere caps op alleen `max2` zijn niet toegestaan; de uitweg is een beperktere workload of een nieuw architectuurbesluit, en dat is JP's beslissing.

- [ ] **Step 6: Schrijf `caps.env`, het machineleesbare formaat dat `preflight.sh` sourcet**

`caps.md` is voor mensen; `preflight.sh` uit Task 10 sourcet een shellbestand en verwacht exact de namen `RUNNER_CPU`, `RUNNER_MEM_BYTES`, `DIND_CPU` en `DIND_MEM_BYTES`. Compose gebruikt in Task 16 een ander schema (`RUNNER_CPUS`, `RUNNER_MEM`, …); `caps.env` levert daarom beide blokken, zodat er nergens handmatig hoeft te worden omgerekend.

```bash
EV=docs/forgejo-runner-pool/evidence/stap-a
python3 - <<'PY' > "$EV/caps.env"
import csv, pathlib, sys
sys.path.insert(0, "forgejo-runner/scripts")
import compute_caps

ev = pathlib.Path("docs/forgejo-runner-pool/evidence/stap-a")
samples = list(csv.DictReader(open(ev / "workload-scrum4me-server.tsv"), delimiter="\t"))
caps = compute_caps.compute(samples)

print("# Gegenereerd door Task 9 uit workload-scrum4me-server.tsv. Niet handmatig bewerken.")
print("# Namen zoals preflight.sh ze sourcet:")
print(f"RUNNER_CPU={caps.runner_cpu}")
print(f"RUNNER_MEM_BYTES={caps.runner_mem_bytes}")
print(f"RUNNER_PIDS={caps.runner_pids}")
print(f"DIND_CPU={caps.dind_cpu}")
print(f"DIND_MEM_BYTES={caps.dind_mem_bytes}")
print(f"DIND_PIDS={caps.dind_pids}")
print("# Namen zoals compose.yaml ze verwacht (Task 16):")
print(f"RUNNER_CPUS={caps.runner_cpu}")
print(f"RUNNER_MEM={caps.runner_mem_bytes}")
print(f"DIND_CPUS={caps.dind_cpu}")
print(f"DIND_MEM={caps.dind_mem_bytes}")
PY
cat "$EV/caps.env"
```

Expected: dertien regels — drie commentaarregels en tien toewijzingen — met elke waarde niet-leeg. Controleer daarna dat `preflight.sh` dit bestand daadwerkelijk kan sourcen:

```bash
bash -c 'set -euo pipefail; source docs/forgejo-runner-pool/evidence/stap-a/caps.env; \
  printf "%s %s %s %s\n" "$RUNNER_CPU" "$RUNNER_MEM_BYTES" "$DIND_CPU" "$DIND_MEM_BYTES"'
```

Expected: vier waarden. Faalt dit, dan faalt de gate van Task 10 op zijn invoer in plaats van op zijn drempels.

- [ ] **Step 7: Commit**

```bash
git add forgejo-runner/scripts/compute_caps.py forgejo-runner/tests/test_compute_caps.py \
        docs/forgejo-runner-pool/evidence/stap-a/caps.md \
        docs/forgejo-runner-pool/evidence/stap-a/caps.env
git commit -m "feat(stap-a): caps berekenen, caps.env genereren en headroomgate op beide hosts"
```

---

### Task 10: Preflight-gate

De laatste gate van stap A en de poortwachter van iedere mutatie daarna. §7.8 noemt na delta-review R12 vier harde drempels. `preflight.sh` faalt vóór iedere mutatie als er ook maar één niet haalt.

**Files:**
- Create: `forgejo-runner/scripts/preflight.sh`
- Test: `forgejo-runner/tests/test_preflight.bats`

**Interfaces:**
- Consumes: `host-facts-<host>.tsv` uit Task 8, `caps.env` zoals Task 9 step 6 die genereert (met exact de variabelen `RUNNER_CPU`, `RUNNER_MEM_BYTES`, `DIND_CPU`, `DIND_MEM_BYTES`), en `allowed-job-images.txt` uit Task 16 wanneer die bestaat
- Produces: exitcode `0` als alle vier drempels halen, `40` als er één faalt; een regel per drempel op stdout met `OK` of `FAIL`.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_preflight.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/preflight.sh"
  FACTS="$BATS_TEST_TMPDIR/facts.tsv"
  CAPS="$BATS_TEST_TMPDIR/caps.env"
  IMAGES="$BATS_TEST_TMPDIR/images.txt"
  cat > "$CAPS" <<'EOS'
RUNNER_CPU=1.0
RUNNER_MEM_BYTES=1073741824
DIND_CPU=2.0
DIND_MEM_BYTES=4294967296
EOS
  echo "catthehacker/ubuntu@sha256:abc 2147483648" > "$IMAGES"
}

ruime_host() {
  cat > "$FACTS" <<'EOS'
vcpu	28
mem_total_bytes	32000000000
mem_available_bytes	21474836480
docker_root_dir	/var/lib/docker
docker_root_free_bytes	500000000000
docker_root_free_pct	60
docker_root_free_inodes_pct	80
EOS
}

@test "ruime host haalt alle vier drempels" {
  ruime_host
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 0 ]
  [[ "$output" == *"vcpu: OK"* ]]
  [[ "$output" == *"inodes: OK"* ]]
}

@test "te weinig vrije schijfruimte faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_pct.*/docker_root_free_pct	9/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"schijf: FAIL"* ]]
}

@test "te weinig vrije bytes voor images plus werkruimte faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_bytes.*/docker_root_free_bytes	3000000000/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
}

@test "te weinig vrije inodes faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_inodes_pct.*/docker_root_free_inodes_pct	5/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"inodes: FAIL"* ]]
}

@test "te krappe cpu-headroom faalt" {
  ruime_host
  sed -i.bak 's/^vcpu.*/vcpu	4/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"vcpu: FAIL"* ]]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_preflight.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/preflight.sh
# De vier harde drempels uit 7.8. Faalt voor iedere mutatie op deze host.
# Exit 0 als alles haalt, 40 zodra een drempel faalt.
set -euo pipefail

FACTS="" ; CAPS="" ; IMAGES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --facts)  FACTS="$2"  ; shift 2 ;;
    --caps)   CAPS="$2"   ; shift 2 ;;
    --images) IMAGES="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -f "$FACTS" ] && [ -f "$CAPS" ] || {
  printf 'gebruik: preflight.sh --facts TSV --caps ENV [--images BESTAND]\n' >&2 ; exit 2 ; }

fact() { awk -F'\t' -v k="$1" '$1==k{print $2; exit}' "$FACTS" ; }
# shellcheck source=/dev/null
source "$CAPS"

WERKRUIMTE_BYTES=$((20 * 1024 * 1024 * 1024))   # 20 GiB, vastgelegd in 7.8
FALEN=0
melding() { printf '%s: %s — %s\n' "$1" "$2" "$3" ; [ "$2" = "FAIL" ] && FALEN=1 ; return 0 ; }

VCPU="$(fact vcpu)"
CPU_SOM="$(python3 -c "print(${RUNNER_CPU} + ${DIND_CPU})")"
if python3 -c "import sys; sys.exit(0 if ${CPU_SOM} <= ${VCPU} * 0.5 else 1)"; then
  melding vcpu OK "som ${CPU_SOM} binnen 50% van ${VCPU}"
else
  melding vcpu FAIL "som ${CPU_SOM} boven 50% van ${VCPU}"
fi

MEMAV="$(fact mem_available_bytes)"
MEM_SOM=$((RUNNER_MEM_BYTES + DIND_MEM_BYTES))
if [ "$MEM_SOM" -le $((MEMAV / 2)) ]; then
  melding geheugen OK "som ${MEM_SOM} binnen 50% van ${MEMAV}"
else
  melding geheugen FAIL "som ${MEM_SOM} boven 50% van ${MEMAV}"
fi

VRIJ_PCT="$(fact docker_root_free_pct)"
VRIJ_BYTES="$(fact docker_root_free_bytes)"
IMAGES_BYTES=0
if [ -n "$IMAGES" ] && [ -f "$IMAGES" ]; then
  IMAGES_BYTES="$(awk '{som += $2} END {print som + 0}' "$IMAGES")"
fi
NODIG=$((IMAGES_BYTES + WERKRUIMTE_BYTES))
if [ "$VRIJ_PCT" -ge 20 ] && [ "$VRIJ_BYTES" -ge "$NODIG" ]; then
  melding schijf OK "${VRIJ_PCT}% vrij en ${VRIJ_BYTES} bytes >= ${NODIG} nodig"
else
  melding schijf FAIL "${VRIJ_PCT}% vrij en ${VRIJ_BYTES} bytes tegenover ${NODIG} nodig"
fi

INODES_PCT="$(fact docker_root_free_inodes_pct)"
if [ "$INODES_PCT" -ge 20 ]; then
  melding inodes OK "${INODES_PCT}% vrij"
else
  melding inodes FAIL "${INODES_PCT}% vrij"
fi

[ "$FALEN" -eq 0 ] || exit 40
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_preflight.bats`
Expected: PASS — 5 tests, 0 failures.

- [ ] **Step 5: Lint en draai op beide hosts**

```bash
shellcheck forgejo-runner/scripts/preflight.sh
EV=docs/forgejo-runner-pool/evidence/stap-a
for H in scrum4me-srv max2; do
  scp forgejo-runner/scripts/preflight.sh "janpeter@$H:/tmp/"
  # caps.env komt uit Task 9 step 6 en moet mee: preflight sourcet hem.
  scp "$EV/caps.env" "janpeter@$H:/tmp/s4m-capture/caps.env"
  ssh "janpeter@$H" "bash /tmp/preflight.sh --facts /tmp/s4m-capture/host-facts-\$(hostname).tsv \
    --caps /tmp/s4m-capture/caps.env" | tee "$EV/preflight-$H.txt"
done
```

Expected: viermaal `OK` op beide hosts en exitcode 0. Faalt er één, dan stopt stap A hier en volgt overleg met JP; `preflight.sh` mag niet worden versoepeld om verder te kunnen.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/preflight.sh forgejo-runner/tests/test_preflight.bats \
        docs/forgejo-runner-pool/evidence/stap-a/
git commit -m "feat(stap-a): preflight-gate met de vier harde drempels uit 7.8"
```

---

## De cyclecontroller

§7.9 belegt de hele runnerlevenscyclus bij één hostcontroller. Na delta-review R12 is dat expliciet `scripts/forgejo_runner_cycle.py` in Python en niet in shell: signal handling, de race tussen childexit en readinessprobe, monotone deadlines en atomaire statepersistentie zijn in shell niet betrouwbaar uit te drukken.

De unittestsuite van deze module is tevens het **stub- en testharnas dat §8 stap A eist**. De stap-A-gates zijn pas groen als deze suite groen is; daarom staan de controllertaken in dit plan na de meettaken maar vóór de bundelassemblage.

Ontwerpprincipes die de tests afdwingen:

- **Geen echte tijd, geen echt netwerk, geen echte processen.** Klok, probe en childproces worden ingespoten. Een test die `sleep` gebruikt is fout.
- **`event_seq` is de enige vóór/na-fencebeslisser.** Wandklok en Forgejo-tijdlijn zijn audit en corroboratie, nooit beslissend (§7.7).
- **Fail-closed.** Elke onbekende uitkomst gaat naar de zwaarste passende toestand, nooit naar `WAITING`.

### Task 11: Readinessclassificatie en bevestigingsregel

§7.7 eist een uitputtende vierwegclassificatie zonder default-gat, en dezelfde tweewaarnemingendrempel voor alle drie foutklassen.

**Files:**
- Create: `forgejo-runner/scripts/forgejo_runner_cycle.py`
- Test: `forgejo-runner/tests/test_cycle_readiness.py`

**Interfaces:**
- Consumes: niets
- Produces:
  - `ReadinessClass` met de leden `READY`, `SOURCE_WAIT`, `CREDENTIAL_ERROR`, `PROTOCOL`
  - `classify_probe(probe) -> ReadinessClass` waarbij `probe` een dict is met `kind` (`"general"` of `"auth"`), en óf `error` óf `status` plus `schema_ok`
  - `SEVERITY: dict[ReadinessClass, int]` met `PROTOCOL > CREDENTIAL_ERROR > SOURCE_WAIT`
  - `Confirmation` met `observe(klasse, now) -> ReadinessClass | None`, die pas een klasse teruggeeft bij twee opeenvolgende gelijke waarnemingen met minimaal `CONFIRM_SECONDS` ertussen

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_cycle_readiness.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c

R = c.ReadinessClass


class TestVierwegclassificatie(unittest.TestCase):
    def test_transportfout_is_source_wait(self):
        for fout in ("timeout", "connection refused", "dns failure"):
            self.assertEqual(c.classify_probe({"kind": "general", "error": fout}), R.SOURCE_WAIT)

    def test_5xx_is_source_wait(self):
        for status in (500, 502, 503, 504):
            self.assertEqual(
                c.classify_probe({"kind": "general", "status": status, "schema_ok": False}),
                R.SOURCE_WAIT)

    def test_401_en_403_op_de_authprobe_is_credential_error(self):
        for status in (401, 403):
            self.assertEqual(
                c.classify_probe({"kind": "auth", "status": status, "schema_ok": False}),
                R.CREDENTIAL_ERROR)

    def test_401_op_de_algemene_probe_is_protocol(self):
        # De algemene probe hoort geen auth te vereisen; 401 daar is een protocolfout.
        self.assertEqual(
            c.classify_probe({"kind": "general", "status": 401, "schema_ok": False}),
            R.PROTOCOL)

    def test_overige_status_is_protocol(self):
        for status in (301, 404, 418):
            self.assertEqual(
                c.classify_probe({"kind": "auth", "status": status, "schema_ok": False}),
                R.PROTOCOL)

    def test_2xx_met_verkeerd_schema_is_protocol(self):
        self.assertEqual(
            c.classify_probe({"kind": "auth", "status": 200, "schema_ok": False}),
            R.PROTOCOL)

    def test_2xx_met_geldig_schema_is_ready(self):
        self.assertEqual(
            c.classify_probe({"kind": "auth", "status": 200, "schema_ok": True}),
            R.READY)

    def test_er_is_geen_default_gat(self):
        # Iedere combinatie valt in precies een van de vier klassen.
        for kind in ("general", "auth"):
            for status in (200, 201, 301, 400, 401, 403, 404, 418, 500, 503):
                for schema in (True, False):
                    uitkomst = c.classify_probe(
                        {"kind": kind, "status": status, "schema_ok": schema})
                    self.assertIn(uitkomst, (R.READY, R.SOURCE_WAIT, R.CREDENTIAL_ERROR, R.PROTOCOL))


class TestSeverity(unittest.TestCase):
    def test_protocol_is_zwaarder_dan_credential_dan_availability(self):
        self.assertGreater(c.SEVERITY[R.PROTOCOL], c.SEVERITY[R.CREDENTIAL_ERROR])
        self.assertGreater(c.SEVERITY[R.CREDENTIAL_ERROR], c.SEVERITY[R.SOURCE_WAIT])


class TestBevestiging(unittest.TestCase):
    def test_een_waarneming_bevestigt_niets(self):
        conf = c.Confirmation()
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=0.0))

    def test_twee_gelijke_waarnemingen_bevestigen(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertEqual(conf.observe(R.SOURCE_WAIT, now=5.0), R.SOURCE_WAIT)

    def test_te_snel_herhalen_bevestigt_nog_niet(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=1.0))

    def test_klassesprong_herstart_de_bevestiging(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertIsNone(conf.observe(R.CREDENTIAL_ERROR, now=5.0))
        self.assertEqual(conf.observe(R.CREDENTIAL_ERROR, now=10.0), R.CREDENTIAL_ERROR)

    def test_geldige_probe_bevestigt_ready_pas_bij_de_tweede(self):
        conf = c.Confirmation()
        self.assertIsNone(conf.observe(R.READY, now=0.0))
        self.assertEqual(conf.observe(R.READY, now=5.0), R.READY)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_readiness.py' -v`
Expected: FAIL — module bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```python
# forgejo-runner/scripts/forgejo_runner_cycle.py
"""Cyclecontroller van de Forgejo-Runner-tweemachinepool.

Implementeert 7.7 en 7.9 van het migratieontwerp: readinessclassificatie,
bevestigingsregel, schedulingfence, deadlinewatchdog, maintenance-record en de
per-job levenscyclus rond `one-job --wait`.

Ontwerpregels die hier hard in zitten:
- event_seq is de enige voor/na-fencebeslisser; klokken zijn audit.
- Monotone tijd voor deadlines, wandklok alleen voor logging.
- Fail-closed: onbekend gaat nooit naar WAITING.
"""

from dataclasses import dataclass, field
from enum import Enum

CONFIRM_SECONDS = 5.0
FENCE_MAX_AGE_SECONDS = 60.0
RETRY_INTERVAL_SECONDS = 30.0


class ReadinessClass(str, Enum):
    READY = "READY"
    SOURCE_WAIT = "SOURCE_WAIT"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"
    PROTOCOL = "PROTOCOL"


SEVERITY = {
    ReadinessClass.SOURCE_WAIT: 1,
    ReadinessClass.CREDENTIAL_ERROR: 2,
    ReadinessClass.PROTOCOL: 3,
}


def classify_probe(probe):
    """Vierwegclassificatie zonder default-gat (7.7).

    Tak 1 transportfout, timeout, connection refused of 5xx -> SOURCE_WAIT.
    Tak 2 401/403 op de geauthenticeerde probe -> CREDENTIAL_ERROR.
    Tak 3 iedere andere status, malformed antwoord of verkeerd schema -> PROTOCOL.
    Tak 4 2xx met het verwachte schema -> READY.
    """
    if probe.get("error"):
        return ReadinessClass.SOURCE_WAIT

    status = probe.get("status")
    if status is None:
        return ReadinessClass.PROTOCOL
    if 500 <= status <= 599:
        return ReadinessClass.SOURCE_WAIT
    if status in (401, 403):
        # Alleen op de geauthenticeerde probe is dit een credentialoordeel. De
        # algemene probe hoort geen auth te vereisen; daar is het een protocolfout.
        return (ReadinessClass.CREDENTIAL_ERROR if probe.get("kind") == "auth"
                else ReadinessClass.PROTOCOL)
    if 200 <= status <= 299:
        return ReadinessClass.READY if probe.get("schema_ok") else ReadinessClass.PROTOCOL
    return ReadinessClass.PROTOCOL


@dataclass
class Confirmation:
    """Tweewaarnemingendrempel: pas twee opeenvolgende gelijke uitkomsten,
    minimaal CONFIRM_SECONDS uit elkaar, bevestigen een klasse. Een klassesprong
    herstart de bevestiging (7.7)."""

    laatste: object = None
    laatste_tijd: float = None

    def observe(self, klasse, now):
        if self.laatste == klasse and self.laatste_tijd is not None \
                and (now - self.laatste_tijd) >= CONFIRM_SECONDS:
            self.laatste, self.laatste_tijd = None, None
            return klasse
        if self.laatste != klasse:
            self.laatste, self.laatste_tijd = klasse, now
        return None

    def reset(self):
        self.laatste, self.laatste_tijd = None, None
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_readiness.py' -v`
Expected: PASS — 14 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add forgejo-runner/scripts/forgejo_runner_cycle.py \
        forgejo-runner/tests/test_cycle_readiness.py
git commit -m "feat(controller): vierwegclassificatie en tweewaarnemingendrempel"
```

---

### Task 12: Geserialiseerde eventloop en toestandsmachine

§7.7 eist één geserialiseerde eventloop die readinessresultaten, childstatus en lokaal ontvangen runnerlog- of taskacceptatie-events verwerkt. Ieder event krijgt op ontvangst één oplopend lokaal `event_seq`, een monotone tijd voor deadlines en daarnaast wandkloktijd voor audit.

**Files:**
- Modify: `forgejo-runner/scripts/forgejo_runner_cycle.py`
- Test: `forgejo-runner/tests/test_cycle_eventloop.py`

**Interfaces:**
- Consumes: `ReadinessClass`, `Confirmation` uit Task 11
- Produces:
  - `State` met `SOURCE_WAIT`, `CREDENTIAL_ERROR`, `WAITING`, `RUNNING`, `DRAINING`, `SCRUBBING`, `QUARANTINED`
  - `Event(kind, payload, event_seq, mono, wall)`
  - `EventLoop(clock)` met `submit(kind, payload) -> Event` en `events -> list[Event]`; `clock` levert `(mono, wall)`
  - `Controller(loop, state=State.SOURCE_WAIT)` met attribuut `state` en methode `on_event(event)`

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_cycle_eventloop.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c

S = c.State


class NepKlok:
    """Monotone tijd en wandklok apart, allebei handmatig bestuurd.

    De wandklok loopt bewust achteruit in een test, om te bewijzen dat de
    controller hem nooit voor een beslissing gebruikt.
    """

    def __init__(self):
        self.mono = 0.0
        self.wall = 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden, wall_delta=None):
        self.mono += seconden
        self.wall += seconden if wall_delta is None else wall_delta


class TestEventSeq(unittest.TestCase):
    def test_event_seq_loopt_strikt_op(self):
        loop = c.EventLoop(NepKlok())
        seqs = [loop.submit("probe", {}).event_seq for _ in range(5)]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 5)

    def test_event_seq_loopt_op_ook_als_de_wandklok_terugspringt(self):
        klok = NepKlok()
        loop = c.EventLoop(klok)
        eerste = loop.submit("probe", {})
        klok.tik(1.0, wall_delta=-500.0)
        tweede = loop.submit("probe", {})
        self.assertGreater(tweede.event_seq, eerste.event_seq)
        self.assertLess(tweede.wall, eerste.wall)
        self.assertGreater(tweede.mono, eerste.mono)

    def test_event_draagt_beide_tijden(self):
        loop = c.EventLoop(NepKlok())
        ev = loop.submit("probe", {"x": 1})
        self.assertIsNotNone(ev.mono)
        self.assertIsNotNone(ev.wall)
        self.assertEqual(ev.payload, {"x": 1})


class TestToestandsmachine(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)

    def test_begint_in_source_wait(self):
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)

    def test_waiting_pas_na_twee_ready_probes_en_groene_gates(self):
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)
        self.klok.tik(5.0)
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.assertEqual(self.ctrl.state, S.WAITING)

    def test_rode_gates_houden_de_controller_uit_waiting(self):
        self.ctrl.gates_groen = False
        for _ in range(2):
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
            self.klok.tik(5.0)
        self.assertNotEqual(self.ctrl.state, S.WAITING)

    def test_job_accepted_brengt_waiting_naar_running(self):
        self.ctrl.state = S.WAITING
        self.ctrl.on_event(self.loop.submit("job_accepted", {}))
        self.assertEqual(self.ctrl.state, S.RUNNING)

    def test_childexit_na_running_gaat_naar_scrubbing(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)

    def test_non_zero_childexit_quarantaint_na_scrub(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 1}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_groene_scrub_na_nette_exit_gaat_terug_naar_waiting(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.WAITING)

    def test_mislukte_scrub_quarantaint_altijd(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": False}))
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_onbekend_event_verandert_de_toestand_niet(self):
        self.ctrl.state = S.WAITING
        self.ctrl.on_event(self.loop.submit("iets_onbekends", {}))
        self.assertEqual(self.ctrl.state, S.WAITING)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_eventloop.py' -v`
Expected: FAIL — `State`, `EventLoop` en `Controller` bestaan nog niet.

- [ ] **Step 3: Breid de module uit**

Voeg onderaan `forgejo_runner_cycle.py` toe:

```python
class State(str, Enum):
    SOURCE_WAIT = "SOURCE_WAIT"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    SCRUBBING = "SCRUBBING"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class Event:
    kind: str
    payload: dict
    event_seq: int
    mono: float
    wall: float


class EventLoop:
    """Eén geserialiseerde bron van event_seq (7.7).

    De klok levert (monotoon, wandklok). Monotone tijd stuurt deadlines; de
    wandklok gaat alleen mee in het auditspoor en beslist nooit iets.
    """

    def __init__(self, clock):
        self._clock = clock
        self._seq = 0
        self.events = []

    def submit(self, kind, payload=None):
        self._seq += 1
        mono, wall = self._clock()
        event = Event(kind=kind, payload=payload or {}, event_seq=self._seq,
                      mono=mono, wall=wall)
        self.events.append(event)
        return event


class Controller:
    """Toestandsmachine van 7.9. Start altijd in SOURCE_WAIT: bij boot bestaat
    er nog geen runnerproces en is de bron nog niet bewezen ready."""

    def __init__(self, loop, state=State.SOURCE_WAIT):
        self.loop = loop
        self.state = state
        self.gates_groen = False
        self.readiness = Confirmation()
        self._laatste_exitcode = None

    def on_event(self, event):
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler is not None:
            handler(event)

    def _on_readiness(self, event):
        bevestigd = self.readiness.observe(event.payload["klasse"], now=event.mono)
        if bevestigd is None:
            return
        if bevestigd is ReadinessClass.READY:
            # Alleen na twee geldige probes EN groene gates mag er een runner komen.
            if self.gates_groen and self.state in (State.SOURCE_WAIT,
                                                   State.CREDENTIAL_ERROR,
                                                   State.QUARANTINED):
                self.state = State.WAITING
            return
        if bevestigd is ReadinessClass.SOURCE_WAIT:
            self.state = State.SOURCE_WAIT
        elif bevestigd is ReadinessClass.CREDENTIAL_ERROR:
            self.state = State.CREDENTIAL_ERROR
        else:
            self.state = State.QUARANTINED

    def _on_job_accepted(self, event):
        if self.state is State.WAITING:
            self.state = State.RUNNING

    def _on_child_exit(self, event):
        self._laatste_exitcode = event.payload.get("code")
        # Na iedere exit wordt geschrobd, ook na een fout: containment eerst.
        self.state = State.SCRUBBING

    def _on_scrub_done(self, event):
        if not event.payload.get("ok"):
            self.state = State.QUARANTINED
            return
        if self._laatste_exitcode not in (0, None):
            # Non-zero bij --wait duidt op config-, initialisatie-, poller- of
            # runtimefalen; heropenen mag dan niet (7.9).
            self.state = State.QUARANTINED
            return
        self.state = State.WAITING if self.gates_groen else State.SOURCE_WAIT
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_eventloop.py' -v`
Expected: PASS — 12 tests, 0 failures.

- [ ] **Step 5: Draai de hele suite**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_*.py' -v`
Expected: PASS — alle tests uit Task 11 en 12 samen, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/forgejo_runner_cycle.py \
        forgejo-runner/tests/test_cycle_eventloop.py
git commit -m "feat(controller): geserialiseerde eventloop en toestandsmachine"
```

---

### Task 13: Schedulingfence, latch-classificatie en deadlinewatchdog

Het scherpst geformuleerde deel van het ontwerp, en het resultaat van reviewrondes 8 tot en met 10. §7.7 en §7.9 eisen:

- de **eerste** afwijkende probe zet een schedulingfence met `fence_seq`, logt een informatief `FENCE_SET`-event en blokkeert iedere childstart; dit is nog geen alarm;
- staat de host in `WAITING`, dan gaat hij direct naar `DRAINING` en stopt het wachtende child, zodat het niet nog vijf seconden online blijft pollen;
- alleen een lokaal `JOB_ACCEPTED`- of `RUNNING`-event met `event_seq < fence_seq` geldt als **vóór-latch** en mag gecontroleerd eindigen;
- ieder ander, onbekend of pas later ontvangen jobevent wordt fail-closed als op/na-latch behandeld: child stoppen, job cancel of requeue, daarna scrub en nulbewijs;
- de fence heeft een harde maximale leeftijd van zestig seconden; is hij dan noch bevestigd noch veilig gewist, dan commit de controller deterministisch naar de **zwaarste sinds latch waargenomen klasse**.

**Files:**
- Modify: `forgejo-runner/scripts/forgejo_runner_cycle.py`
- Test: `forgejo-runner/tests/test_cycle_fence.py`

**Interfaces:**
- Consumes: `EventLoop`, `Controller`, `SEVERITY` uit Task 11 en 12
- Produces:
  - `Fence(fence_seq, gezet_op_mono, eerste_klasse)` met `zwaarste_klasse`, `observe(klasse)`, `verlopen(now) -> bool`
  - `Controller.fence: Fence | None`
  - `Controller.latch_verdict(event) -> "voor" | "op-of-na"`
  - `Controller.mag_child_starten -> bool`

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_cycle_fence.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c

S, R = c.State, c.ReadinessClass


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


class FenceBasis(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.gates_groen = True
        self.ctrl.state = S.WAITING

    def wijk_af(self, klasse=R.SOURCE_WAIT):
        return self.ctrl.on_event(self.loop.submit("readiness", {"klasse": klasse}))


class TestFenceZetten(FenceBasis):
    def test_eerste_afwijking_zet_een_fence(self):
        self.assertIsNone(self.ctrl.fence)
        self.wijk_af()
        self.assertIsNotNone(self.ctrl.fence)

    def test_eerste_afwijking_haalt_waiting_direct_uit_de_lucht(self):
        self.wijk_af()
        self.assertEqual(self.ctrl.state, S.DRAINING)

    def test_eerste_afwijking_blokkeert_een_nieuwe_child(self):
        self.wijk_af()
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_eerste_afwijking_logt_fence_set_en_alarmeert_niet(self):
        self.wijk_af()
        soorten = [e.kind for e in self.loop.events]
        self.assertIn("fence_set", soorten)
        self.assertNotIn("alarm", soorten)

    def test_fence_seq_is_het_event_seq_van_de_afwijking(self):
        ev = self.loop.submit("readiness", {"klasse": R.SOURCE_WAIT})
        self.ctrl.on_event(ev)
        self.assertEqual(self.ctrl.fence.fence_seq, ev.event_seq)


class TestLatchclassificatie(FenceBasis):
    def test_job_voor_de_fence_is_voor_latch(self):
        job = self.loop.submit("job_accepted", {})
        self.wijk_af()
        self.assertEqual(self.ctrl.latch_verdict(job), "voor")

    def test_job_na_de_fence_is_op_of_na_latch(self):
        self.wijk_af()
        job = self.loop.submit("job_accepted", {})
        self.assertEqual(self.ctrl.latch_verdict(job), "op-of-na")

    def test_gelijk_seq_telt_als_op_of_na(self):
        self.wijk_af()
        nep = c.Event(kind="job_accepted", payload={},
                      event_seq=self.ctrl.fence.fence_seq, mono=0.0, wall=0.0)
        self.assertEqual(self.ctrl.latch_verdict(nep), "op-of-na")

    def test_late_wandklok_verandert_het_oordeel_niet(self):
        # Een event met een oudere wandklok maar hoger event_seq blijft op/na-latch.
        self.wijk_af()
        laat = c.Event(kind="job_accepted", payload={},
                       event_seq=self.ctrl.fence.fence_seq + 5, mono=0.0, wall=-9999.0)
        self.assertEqual(self.ctrl.latch_verdict(laat), "op-of-na")

    def test_onbekend_event_zonder_fence_is_fail_closed(self):
        nep = c.Event(kind="job_accepted", payload={}, event_seq=1, mono=0.0, wall=0.0)
        self.assertEqual(self.ctrl.latch_verdict(nep), "op-of-na")


class TestDeadlinewatchdog(FenceBasis):
    def test_fence_verloopt_na_zestig_seconden(self):
        self.wijk_af()
        self.klok.tik(59.0)
        self.assertFalse(self.ctrl.fence.verlopen(self.klok.mono))
        self.klok.tik(2.0)
        self.assertTrue(self.ctrl.fence.verlopen(self.klok.mono))

    def test_zwaarste_klasse_wint_bij_een_blijvende_klassesprong(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(1.0); self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0); self.wijk_af(R.CREDENTIAL_ERROR)
        self.assertEqual(self.ctrl.fence.zwaarste_klasse, R.PROTOCOL)

    def test_deadline_commit_gaat_naar_de_zwaarste_klasse(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(1.0); self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.CREDENTIAL_ERROR)

    def test_deadline_commit_alarmeert(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertIn("alarm", [e.kind for e in self.loop.events])

    def test_valid_error_flap_bereikt_alsnog_de_deadline(self):
        self.wijk_af(R.SOURCE_WAIT)
        for _ in range(6):
            self.klok.tik(5.0); self.wijk_af(R.READY)
            self.klok.tik(5.0); self.wijk_af(R.SOURCE_WAIT)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)
        self.assertIsNone(self.ctrl.fence)


class TestFenceWissen(FenceBasis):
    def test_een_geldige_probe_wist_de_fence_niet(self):
        self.wijk_af()
        self.klok.tik(5.0)
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNotNone(self.ctrl.fence)

    def test_twee_geldige_probes_zonder_nulbewijs_wissen_de_fence_niet(self):
        self.wijk_af()
        self.ctrl.nulbewijs_ok = False
        for _ in range(2):
            self.klok.tik(5.0)
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNotNone(self.ctrl.fence)

    def test_twee_geldige_probes_met_nulbewijs_en_groene_gates_wissen_de_fence(self):
        self.wijk_af()
        self.ctrl.nulbewijs_ok = True
        self.ctrl.gates_groen = True
        for _ in range(2):
            self.klok.tik(5.0)
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNone(self.ctrl.fence)
        self.assertTrue(self.ctrl.mag_child_starten)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_fence.py' -v`
Expected: FAIL — `Fence`, `latch_verdict`, `tick` en `mag_child_starten` bestaan nog niet.

- [ ] **Step 3: Breid de module uit**

```python
@dataclass
class Fence:
    """Schedulingfence (7.7). Gezet op de eerste afwijkende probe; blokkeert
    iedere childstart tot hij bevestigd of veilig gewist is."""

    fence_seq: int
    gezet_op_mono: float
    eerste_klasse: object
    zwaarste_klasse: object = None

    def __post_init__(self):
        self.zwaarste_klasse = self.eerste_klasse

    def observe(self, klasse):
        if klasse is ReadinessClass.READY:
            return
        if SEVERITY[klasse] > SEVERITY[self.zwaarste_klasse]:
            self.zwaarste_klasse = klasse

    def verlopen(self, now):
        return (now - self.gezet_op_mono) >= FENCE_MAX_AGE_SECONDS


_KLASSE_NAAR_STATE = {
    ReadinessClass.SOURCE_WAIT: State.SOURCE_WAIT,
    ReadinessClass.CREDENTIAL_ERROR: State.CREDENTIAL_ERROR,
    ReadinessClass.PROTOCOL: State.QUARANTINED,
}
```

Vervang daarna `Controller.__init__` en `_on_readiness` door onderstaande versie en voeg de nieuwe methoden toe:

```python
    def __init__(self, loop, state=State.SOURCE_WAIT):
        self.loop = loop
        self.state = state
        self.gates_groen = False
        self.nulbewijs_ok = False
        self.readiness = Confirmation()
        self.fence = None
        self._laatste_exitcode = None

    @property
    def mag_child_starten(self):
        """Een fence blokkeert onvoorwaardelijk; een unit-restart omzeilt hem nooit."""
        return self.fence is None and self.gates_groen and self.state in (
            State.WAITING, State.SOURCE_WAIT)

    def latch_verdict(self, event):
        """Alleen een lokaal event met event_seq strikt kleiner dan fence_seq is
        vóór-latch. Alles daarbuiten is fail-closed op/na-latch (7.7)."""
        if self.fence is None:
            return "op-of-na"
        return "voor" if event.event_seq < self.fence.fence_seq else "op-of-na"

    def _on_readiness(self, event):
        klasse = event.payload["klasse"]

        if klasse is not ReadinessClass.READY:
            if self.fence is None:
                self.fence = Fence(fence_seq=event.event_seq,
                                   gezet_op_mono=event.mono,
                                   eerste_klasse=klasse)
                # Informatief, geen alarm: reviewronde 8 wilde de fence direct
                # maar de ruis niet.
                self.loop.submit("fence_set", {"fence_seq": self.fence.fence_seq,
                                               "klasse": klasse})
                if self.state is State.WAITING:
                    self.state = State.DRAINING
            else:
                self.fence.observe(klasse)
        elif self.fence is not None:
            self.fence.observe(klasse)

        bevestigd = self.readiness.observe(klasse, now=event.mono)
        if bevestigd is None:
            return

        if bevestigd is ReadinessClass.READY:
            if self.nulbewijs_ok and self.gates_groen:
                self.fence = None
                self.state = State.WAITING
            return

        self.state = _KLASSE_NAAR_STATE[bevestigd]
        self.fence = None
        self.loop.submit("alarm", {"klasse": bevestigd, "reden": "bevestigde fouttoestand"})

    def tick(self, now):
        """Deadlinewatchdog: een onopgeloste fence ouder dan zestig seconden
        commit deterministisch naar de zwaarste sinds latch waargenomen klasse."""
        if self.fence is None or not self.fence.verlopen(now):
            return
        klasse = self.fence.zwaarste_klasse
        self.state = _KLASSE_NAAR_STATE[klasse]
        self.loop.submit("alarm", {"klasse": klasse, "reden": "fence-deadline bereikt"})
        self.fence = None
        self.readiness.reset()
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_fence.py' -v`
Expected: PASS — 18 tests, 0 failures.

- [ ] **Step 5: Draai de hele controllersuite**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_*.py' -v`
Expected: PASS. Faalt er nu een test uit Task 12, dan heeft de herschreven `_on_readiness` iets gebroken; repareer dat vóór de commit in plaats van de oude test aan te passen.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/forgejo_runner_cycle.py forgejo-runner/tests/test_cycle_fence.py
git commit -m "feat(controller): schedulingfence, latch-classificatie en deadlinewatchdog"
```

---

### Task 14: Maintenance-record

§7.7 kent precies één uitzondering op de zestigsecondenwatchdog: een vooraf gearmd control-plane-onderhoudsvenster. Het record bevat `maintenance_id`, UTC-start en een harde UTC-eindtijd van maximaal dertig minuten, is op beide hosts identiek gearmd, en kan niet automatisch worden aangemaakt of verlengd.

Zolang de **algemene** readiness binnen dat venster nog niet tweemaal geldig is geweest, worden alle startuptransport-, status- en schema-uitkomsten voor de watchdog als `SOURCE_WAIT` behandeld. Zodra de algemene readiness tweemaal geldig is, vervalt die uitzondering direct en geldt de normale vierwegclassificatie, zodat een bevestigde 401/403 ook binnen het venster correct wordt gemeld. Bij de harde eindtijd vervalt iedere uitzondering.

Let op het klokonderscheid: de **geldigheid van het venster** is een wandklokinterval, want het is een menselijk geplande afspraak. De **fencedeadline** blijft monotoon. Die twee mogen niet door elkaar lopen; de tests dwingen dat af.

**Files:**
- Modify: `forgejo-runner/scripts/forgejo_runner_cycle.py`
- Test: `forgejo-runner/tests/test_cycle_maintenance.py`

**Interfaces:**
- Consumes: `Fence`, `Controller` uit Task 13
- Produces: `MaintenanceRecord(maintenance_id, start_utc, eind_utc)` met `geldig_op(wall) -> bool` en `MAX_DUUR_SECONDS = 1800`; `MaintenanceRecord.parse(dict)` die weigert bij een ontbrekend veld of een duur boven het maximum; `Controller.maintenance` en `Controller.algemene_readiness_bevestigd`

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_cycle_maintenance.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c

S, R = c.State, c.ReadinessClass


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1_000_000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


def record(start=1_000_000.0, duur=1800.0):
    return c.MaintenanceRecord(maintenance_id="mnt-1", start_utc=start, eind_utc=start + duur)


class TestRecordvalidatie(unittest.TestCase):
    def test_duur_boven_dertig_minuten_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"maintenance_id": "x", "start_utc": 0, "eind_utc": 1801})

    def test_precies_dertig_minuten_mag(self):
        rec = c.MaintenanceRecord.parse({"maintenance_id": "x", "start_utc": 0, "eind_utc": 1800})
        self.assertEqual(rec.maintenance_id, "x")

    def test_ontbrekend_veld_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"start_utc": 0, "eind_utc": 60})

    def test_lege_id_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"maintenance_id": "", "start_utc": 0, "eind_utc": 60})

    def test_geldigheid_is_een_wandklokinterval(self):
        rec = record(start=100.0, duur=60.0)
        self.assertFalse(rec.geldig_op(99.0))
        self.assertTrue(rec.geldig_op(100.0))
        self.assertTrue(rec.geldig_op(159.0))
        self.assertFalse(rec.geldig_op(160.0))


class TestVensterGedrag(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.maintenance = record()

    def wijk_af(self, klasse):
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": klasse}))

    def test_gemengde_startupklassen_committen_alleen_source_wait(self):
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)

    def test_deadline_binnen_het_venster_alarmeert_niet_als_security(self):
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        alarmen = [e for e in self.loop.events if e.kind == "alarm"]
        self.assertTrue(all(e.payload.get("verwacht") for e in alarmen))

    def test_na_tweemaal_geldige_algemene_readiness_vervalt_de_uitzondering(self):
        self.ctrl.algemene_readiness_bevestigd = True
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_na_de_harde_eindtijd_geldt_de_normale_regel(self):
        self.ctrl.maintenance = record(start=1_000_000.0, duur=60.0)
        self.klok.tik(120.0)          # buiten het venster
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_zonder_record_geldt_de_normale_regel(self):
        self.ctrl.maintenance = None
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_het_venster_verlengt_zichzelf_niet(self):
        rec = record(start=1_000_000.0, duur=60.0)
        self.ctrl.maintenance = rec
        self.klok.tik(30.0)
        self.wijk_af(R.SOURCE_WAIT)
        self.assertEqual(rec.eind_utc, 1_000_060.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_maintenance.py' -v`
Expected: FAIL — `MaintenanceRecord` bestaat nog niet.

- [ ] **Step 3: Breid de module uit**

```python
MAINTENANCE_MAX_DUUR_SECONDS = 1800.0


@dataclass(frozen=True)
class MaintenanceRecord:
    """Vooraf gearmd control-plane-onderhoudsvenster (7.7).

    Geldigheid is bewust een wandklokinterval: het is een menselijk geplande
    afspraak die op beide hosts identiek wordt gearmd. Fencedeadlines blijven
    monotoon; die twee klokken worden nooit door elkaar gebruikt.
    """

    maintenance_id: str
    start_utc: float
    eind_utc: float

    @classmethod
    def parse(cls, data):
        for veld in ("maintenance_id", "start_utc", "eind_utc"):
            if veld not in data:
                raise ValueError(f"maintenance-record mist {veld}")
        if not str(data["maintenance_id"]).strip():
            raise ValueError("maintenance_id mag niet leeg zijn")
        duur = float(data["eind_utc"]) - float(data["start_utc"])
        if duur <= 0:
            raise ValueError("maintenance-record heeft geen positieve duur")
        if duur > MAINTENANCE_MAX_DUUR_SECONDS:
            raise ValueError(
                f"maintenance-record duurt {duur}s, maximaal {MAINTENANCE_MAX_DUUR_SECONDS}s")
        return cls(maintenance_id=str(data["maintenance_id"]),
                   start_utc=float(data["start_utc"]),
                   eind_utc=float(data["eind_utc"]))

    def geldig_op(self, wall):
        return self.start_utc <= wall < self.eind_utc
```

Voeg aan `Controller.__init__` toe: `self.maintenance = None` en `self.algemene_readiness_bevestigd = False`. Vervang `tick` door:

```python
    def _startupuitzondering_actief(self, wall):
        """Binnen een geldig gearmd venster en zolang de algemene readiness nog
        niet tweemaal geldig is, committeert de watchdog uitsluitend SOURCE_WAIT."""
        return (self.maintenance is not None
                and self.maintenance.geldig_op(wall)
                and not self.algemene_readiness_bevestigd)

    def tick(self, now, wall=None):
        if self.fence is None or not self.fence.verlopen(now):
            return
        if wall is None:
            wall = self.loop.events[-1].wall if self.loop.events else 0.0

        if self._startupuitzondering_actief(wall):
            klasse = ReadinessClass.SOURCE_WAIT
            verwacht = True
        else:
            klasse = self.fence.zwaarste_klasse
            verwacht = False

        self.state = _KLASSE_NAAR_STATE[klasse]
        self.loop.submit("alarm", {"klasse": klasse,
                                   "reden": "fence-deadline bereikt",
                                   "verwacht": verwacht,
                                   "maintenance_id": (self.maintenance.maintenance_id
                                                      if self.maintenance else None)})
        self.fence = None
        self.readiness.reset()
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_maintenance.py' -v`
Expected: PASS — 11 tests, 0 failures.

- [ ] **Step 5: Draai de hele controllersuite**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_*.py' -v`
Expected: PASS. De testen uit Task 13 die `tick(now)` aanroepen moeten blijven werken: `wall` is optioneel en valt terug op de wandklok van het laatste event.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/scripts/forgejo_runner_cycle.py \
        forgejo-runner/tests/test_cycle_maintenance.py
git commit -m "feat(controller): maintenance-record met harde eindtijd en startupuitzondering"
```

---

### Task 15: Joblevenscyclus, drain en assignment-nulbewijs

De negen stappen van §7.9 en het FetchTask-ambiguïteitsbewijs. Dit is het deel dat bepaalt dat er nooit een tweede job wordt aangenomen voordat de scrub schoon is bewezen.

Het exitcodecontract is brongebonden: `runJob` geeft het resultaat van de single-task-poller terug, die bij een ontvangen taak `runner.Run(...)` aanroept zonder het jobresultaat als procesfout terug te geven en daarna `nil` retourneert. Een normaal afgeronde **groene én rode** workflow levert daarom procesexit `0`; de terminale Forgejo-jobstatus bepaalt het jobresultaat. Non-zero duidt op config-, initialisatie-, poller- of runtimefalen. Task 17 valideert dit contract tegen de echte image; stap E bewijst het met een bewust groene en een bewust rode testjob.

**Files:**
- Modify: `forgejo-runner/scripts/forgejo_runner_cycle.py`
- Test: `forgejo-runner/tests/test_cycle_lifecycle.py`

**Interfaces:**
- Consumes: `Controller` uit Task 13 en 14
- Produces:
  - `assignment_nulbewijs(snapshots) -> bool` — waar bij twee opeenvolgende snapshots, minimaal `NULBEWIJS_INTERVAL_SECONDS` uit elkaar, zonder toegewezen of lopende job
  - `Controller.drain(now)` — zet `DRAINING` en blokkeert een volgende cyclus
  - `Controller.cycle_stappen()` — de bindende volgorde als lijst met stapnamen, zodat de volgorde testbaar is en niet alleen in proza staat

- [ ] **Step 1: Schrijf de falende test**

```python
# forgejo-runner/tests/test_cycle_lifecycle.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c

S = c.State


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


def snap(t, assigned=0, running=0):
    return {"mono": t, "assigned": assigned, "running": running}


class TestNulbewijs(unittest.TestCase):
    def test_twee_lege_snapshots_tien_seconden_uiteen_bewijzen_nul(self):
        self.assertTrue(c.assignment_nulbewijs([snap(0.0), snap(10.0)]))

    def test_te_kort_uiteen_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0), snap(5.0)]))

    def test_een_snapshot_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0)]))

    def test_een_toegewezen_job_breekt_het_bewijs(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0), snap(10.0, assigned=1)]))

    def test_een_lopende_job_breekt_het_bewijs(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0, running=1), snap(10.0)]))

    def test_lege_lijst_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([]))


class TestCyclusvolgorde(unittest.TestCase):
    def test_scrub_komt_voor_een_nieuwe_runnerstart(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("scrub"), stappen.index("start_runner_volgende_cyclus"))

    def test_bewijs_schoon_komt_voor_een_nieuwe_runnerstart(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("bewijs_schoon"),
                        stappen.index("start_runner_volgende_cyclus"))

    def test_trustgate_is_de_eerste_stap(self):
        self.assertEqual(c.Controller.cycle_stappen()[0], "trustgate")

    def test_bewijs_geen_runnerproces_komt_voor_de_scrub(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("bewijs_geen_runnerproces"), stappen.index("scrub"))


class TestDrain(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.gates_groen = True

    def test_drain_vanuit_waiting_gaat_naar_draining(self):
        self.ctrl.state = S.WAITING
        self.ctrl.drain(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.DRAINING)

    def test_drain_blokkeert_een_volgende_child(self):
        self.ctrl.state = S.WAITING
        self.ctrl.drain(self.klok.mono)
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_drain_tijdens_running_breekt_de_job_niet_af(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.drain(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.RUNNING)
        self.assertTrue(self.ctrl.drain_gevraagd)

    def test_na_drain_leidt_een_groene_scrub_niet_terug_naar_waiting(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.drain(self.klok.mono)
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.DRAINING)


class TestOpNaLatchJob(unittest.TestCase):
    def test_job_na_de_fence_leidt_tot_cancel_en_scrub(self):
        klok = NepKlok()
        loop = c.EventLoop(klok)
        ctrl = c.Controller(loop)
        ctrl.gates_groen = True
        ctrl.state = S.WAITING
        ctrl.on_event(loop.submit("readiness", {"klasse": c.ReadinessClass.SOURCE_WAIT}))
        job = loop.submit("job_accepted", {})
        ctrl.on_event(job)
        self.assertEqual(ctrl.latch_verdict(job), "op-of-na")
        self.assertIn("cancel_en_redispatch", [e.kind for e in loop.events])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_lifecycle.py' -v`
Expected: FAIL — `assignment_nulbewijs`, `cycle_stappen` en `drain` bestaan nog niet.

- [ ] **Step 3: Breid de module uit**

```python
NULBEWIJS_INTERVAL_SECONDS = 10.0


def assignment_nulbewijs(snapshots):
    """Sluit het FetchTask-ambiguïteitsvenster (7.9).

    Vereist twee opeenvolgende snapshots, minimaal NULBEWIJS_INTERVAL_SECONDS
    uit elkaar, waarin geen enkele job aan deze runner is toegewezen of loopt.
    Minder bewijs is geen bewijs: de functie is fail-closed.
    """
    if len(snapshots) < 2:
        return False
    vorige, laatste = snapshots[-2], snapshots[-1]
    if (laatste["mono"] - vorige["mono"]) < NULBEWIJS_INTERVAL_SECONDS:
        return False
    return all(s.get("assigned", 0) == 0 and s.get("running", 0) == 0
               for s in (vorige, laatste))
```

Voeg aan `Controller` toe:

```python
    @staticmethod
    def cycle_stappen():
        """De bindende cyclus uit 7.9, als lijst zodat de volgorde testbaar is."""
        return [
            "trustgate",
            "controleer_dind_health",
            "controleer_toegestane_images",
            "start_runner_one_job_wait",
            "wacht_op_child_exit",
            "bewijs_geen_runnerproces",
            "scrub",
            "bewijs_schoon",
            "start_runner_volgende_cyclus",
        ]

    def drain(self, now):
        """Geplande stop. Vanuit WAITING direct stoppen; vanuit RUNNING de job
        terminaal laten worden en daarna geen nieuwe cyclus starten (7.9)."""
        self.drain_gevraagd = True
        if self.state is State.WAITING:
            self.state = State.DRAINING
```

Voeg aan `Controller.__init__` toe: `self.drain_gevraagd = False`.

Pas `_on_job_accepted` aan zodat een op/na-latch job fail-closed wordt afgehandeld:

```python
    def _on_job_accepted(self, event):
        if self.fence is not None and self.latch_verdict(event) == "op-of-na":
            # Fail-closed: stoppen, cancel of requeue, daarna scrub en nulbewijs.
            self.loop.submit("cancel_en_redispatch", {"event_seq": event.event_seq})
            self.state = State.DRAINING
            return
        if self.state is State.WAITING:
            self.state = State.RUNNING
```

Pas `_on_scrub_done` aan zodat een gevraagde drain niet heropent:

```python
    def _on_scrub_done(self, event):
        if not event.payload.get("ok"):
            self.state = State.QUARANTINED
            return
        if self._laatste_exitcode not in (0, None):
            self.state = State.QUARANTINED
            return
        if self.drain_gevraagd:
            self.state = State.DRAINING
            return
        self.state = State.WAITING if self.gates_groen else State.SOURCE_WAIT
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_lifecycle.py' -v`
Expected: PASS — 15 tests, 0 failures.

- [ ] **Step 5: Draai de volledige controllersuite — dit is de stap-A-harnasgate**

Run: `python3 -m unittest discover -s forgejo-runner/tests -p 'test_cycle_*.py' -v`
Expected: PASS, alle tests uit Task 11 tot en met 15 samen. §7.9 maakt deze suite de stap-A-gate: zolang hij niet groen is, is stap A niet afgerond.

- [ ] **Step 6: Leg de harnasdekking vast tegenover §8 stap A**

Schrijf `docs/forgejo-runner-pool/evidence/stap-a/testharnas-dekking.md` met een tabel die iedere eis uit stap A koppelt aan de test die haar bewijst:

| Eis uit §8 stap A | Test |
|---|---|
| transport/5xx → `SOURCE_WAIT` | `test_cycle_readiness.TestVierwegclassificatie.test_transportfout_is_source_wait`, `…test_5xx_is_source_wait` |
| authprobe 401/403 → `CREDENTIAL_ERROR` | `…test_401_en_403_op_de_authprobe_is_credential_error` |
| overige status/schemafout → `QUARANTINED` | `…test_overige_status_is_protocol`, `…test_2xx_met_verkeerd_schema_is_protocol` |
| geldige 2xx → inhoudelijke trustgate | `…test_2xx_met_geldig_schema_is_ready` plus `test_cycle_eventloop.…test_rode_gates_houden_de_controller_uit_waiting` |
| eerste afwijking zet alleen informatief event plus fence | `test_cycle_fence.TestFenceZetten.test_eerste_afwijking_logt_fence_set_en_alarmeert_niet` |
| eerste afwijking stopt een `WAITING` child | `…test_eerste_afwijking_haalt_waiting_direct_uit_de_lucht` |
| twee gelijke afwijkingen bevestigen | `test_cycle_readiness.TestBevestiging.test_twee_gelijke_waarnemingen_bevestigen` |
| klassesprong herstart bevestiging | `…test_klassesprong_herstart_de_bevestiging` |
| automatisch herstel zonder directe runnerstart | `test_cycle_fence.TestFenceWissen.…` (drie tests) |
| alleen `event_seq < fence_seq` is vóór-latch | `test_cycle_fence.TestLatchclassificatie.…` (vijf tests) |
| remote/Forgejo-tijden beslissen nooit | `…test_late_wandklok_verandert_het_oordeel_niet`, `test_cycle_eventloop.…test_event_seq_loopt_op_ook_als_de_wandklok_terugspringt` |
| unknown/late gaat naar cancel/scrub/redispatch | `test_cycle_lifecycle.TestOpNaLatchJob.…` |
| blijvende klassesprong bereikt de deadline | `test_cycle_fence.TestDeadlinewatchdog.test_zwaarste_klasse_wint_bij_een_blijvende_klassesprong` |
| blijvende valid/error-flap bereikt de deadline | `…test_valid_error_flap_bereikt_alsnog_de_deadline` |
| deadline kiest de zwaarste klasse en alarmeert | `…test_deadline_commit_gaat_naar_de_zwaarste_klasse`, `…test_deadline_commit_alarmeert` |
| gemengde startupklassen committen alleen `SOURCE_WAIT` | `test_cycle_maintenance.TestVensterGedrag.test_gemengde_startupklassen_committen_alleen_source_wait` |
| na algemene readiness gelden 401/protocol normaal | `…test_na_tweemaal_geldige_algemene_readiness_vervalt_de_uitzondering` |
| na de harde eindtijd bestaat geen uitzondering | `…test_na_de_harde_eindtijd_geldt_de_normale_regel` |
| assignment-nulbewijs vereist twee snapshots | `test_cycle_lifecycle.TestNulbewijs.…` (zes tests) |

Ontbreekt er een rij, dan is stap A niet gedekt en moet de test er alsnog komen.

- [ ] **Step 7: Commit**

```bash
git add forgejo-runner/scripts/forgejo_runner_cycle.py \
        forgejo-runner/tests/test_cycle_lifecycle.py \
        docs/forgejo-runner-pool/evidence/stap-a/testharnas-dekking.md
git commit -m "feat(controller): joblevenscyclus, drain en assignment-nulbewijs"
```

---

## Stap B — de gedeelde bundel

Vanaf hier wordt de bundel gebouwd die byte-identiek naar beide hosts gaat. Alles wordt in deze repo gemaakt en gevalideerd; er wordt in stap B nog niets uitgerold.

### Task 16: Compose, imagepins en het labelcontract

§4 eist dat runner- en DinD-image met tag **én** registry-gevalideerde manifestdigest worden vastgelegd, en dat de labellijst canoniek en digest-gepind is. De meting van 31 augustus liet zien dat de live installatie mutable tags gebruikt (`code.forgejo.org/forgejo/runner:12` en `docker:dind`); die worden hier vervangen door digests uit Task 2.

**Files:**
- Create: `forgejo-runner/compose.yaml`
- Create: `forgejo-runner/.env.example`
- Create: `forgejo-runner/labels.txt`
- Create: `forgejo-runner/allowed-job-images.txt`
- Create: `forgejo-runner/scripts/resolve-digests.sh`
- Test: `forgejo-runner/tests/test_compose_contract.bats`

**Interfaces:**
- Consumes: `images.json` en `runner-registration.json` uit Task 2
- Produces: `.env` met `RUNNER_IMAGE`, `DIND_IMAGE` en `JOB_IMAGE`, elk als `repo@sha256:…`; `labels.txt` met één regel per label in de vorm `naam:docker://image@sha256:…`; `allowed-job-images.txt` met per regel een digest en de grootte in bytes, gelezen door `preflight.sh` uit Task 10

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_compose_contract.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMPOSE="$REPO_ROOT/forgejo-runner/compose.yaml"
  LABELS="$REPO_ROOT/forgejo-runner/labels.txt"
  IMAGES="$REPO_ROOT/forgejo-runner/allowed-job-images.txt"
}

@test "dind is privileged en de runner niet" {
  run python3 -c "
import sys
tekst = open('$COMPOSE').read()
runner = tekst.split('runner:')[1].split('dind:')[0]
dind = tekst.split('dind:')[1]
sys.exit(0 if ('privileged: true' in dind and 'privileged' not in runner) else 1)
"
  [ "$status" -eq 0 ]
}

@test "er is geen host-docker-socket gemount" {
  run grep -c '/var/run/docker.sock' "$COMPOSE"
  [ "$output" = "0" ]
}

@test "er is geen poort gepubliceerd" {
  run grep -cE '^\s+ports:' "$COMPOSE"
  [ "$output" = "0" ]
}

@test "er is geen host-pid, host-ipc of host-netwerkmode" {
  run grep -cE 'pid: *host|ipc: *host|network_mode: *host' "$COMPOSE"
  [ "$output" = "0" ]
}

@test "runner heeft restart no en dind restart always" {
  grep -q 'restart: "no"' "$COMPOSE"
  grep -q 'restart: always' "$COMPOSE"
}

@test "het dind-volume heeft de expliciete naam" {
  grep -q 'name: forgejo-runner-dind-data' "$COMPOSE"
}

@test "de runner krijgt het juiste docker-endpoint" {
  grep -q 'DOCKER_HOST=tcp://dind:2375' "$COMPOSE"
}

@test "images staan als digest in het compose-bestand, niet als kale tag" {
  run grep -cE 'image: *\$\{(RUNNER|DIND)_IMAGE\}' "$COMPOSE"
  [ "$output" = "2" ]
}

@test "labels.txt is niet leeg en elke regel draagt een digest" {
  [ -s "$LABELS" ]
  while read -r regel; do
    [[ "$regel" == *"@sha256:"* ]] || { echo "geen digest: $regel"; false; }
  done < "$LABELS"
}

@test "allowed-job-images.txt bevat alleen digests met een grootte" {
  [ -s "$IMAGES" ]
  while read -r digest grootte; do
    [[ "$digest" == *"@sha256:"* ]] || { echo "geen digest: $digest"; false; }
    [[ "$grootte" =~ ^[0-9]+$ ]] || { echo "geen grootte: $grootte"; false; }
  done < "$IMAGES"
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_compose_contract.bats`
Expected: FAIL — de bestanden bestaan nog niet.

- [ ] **Step 3: Resolveer de digests vanaf de registry**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/resolve-digests.sh
# Zet een mutable tag om in een registry-gevalideerde digest.
# Een lokale image-ID telt niet: 4 van het migratieontwerp eist dat de digest
# vanaf de registry bevestigd is.
set -euo pipefail

for tag in "$@"; do
  digest="$(docker manifest inspect --verbose "$tag" 2>/dev/null \
    | python3 -c '
import json, sys
data = json.load(sys.stdin)
if isinstance(data, list):
    data = data[0]
print(data["Descriptor"]["digest"])
')"
  [ -n "$digest" ] || { printf 'kon geen digest resolven voor %s\n' "$tag" >&2 ; exit 1 ; }
  repo="${tag%%:*}"
  printf '%s\t%s@%s\n' "$tag" "$repo" "$digest"
done
```

```bash
bash forgejo-runner/scripts/resolve-digests.sh \
  code.forgejo.org/forgejo/runner:12 \
  docker:dind \
  catthehacker/ubuntu:act-latest \
  | tee docs/forgejo-runner-pool/evidence/stap-a/resolved-digests.tsv
```

Expected: drie regels met elk een `sha256:`-digest. Vergelijk de runner- en DinD-digest met de `RepoDigests` uit `images.json` van Task 2: **wijken ze af, dan is de tag sinds de inventarisatie verschoven** en moet je de digest uit `images.json` gebruiken, want dat is wat er aantoonbaar draait.

- [ ] **Step 4: Schrijf `.env.example`, `labels.txt` en `allowed-job-images.txt`**

```bash
# forgejo-runner/.env.example
# Uitsluitend imagepins en niet-geheime waarden. Nooit tokens of UUID's.
# Vul de digests uit scripts/resolve-digests.sh, gekruist met images.json uit stap A.
RUNNER_IMAGE=code.forgejo.org/forgejo/runner@sha256:VUL_IN
DIND_IMAGE=docker@sha256:VUL_IN
JOB_IMAGE=catthehacker/ubuntu@sha256:VUL_IN

# Resourcecaps. Neem deze niet handmatig over: Task 9 step 6 genereert
# evidence/stap-a/caps.env met exact deze namen naast de preflight-namen.
RUNNER_CPUS=VUL_IN
RUNNER_MEM=VUL_IN
RUNNER_PIDS=VUL_IN
DIND_CPUS=VUL_IN
DIND_MEM=VUL_IN
DIND_PIDS=VUL_IN
```

Vul het capsdeel mechanisch vanuit `caps.env`, zodat de twee naamgevingsschema's niet uit elkaar kunnen lopen:

```bash
grep -E '^(RUNNER|DIND)_(CPUS|MEM|PIDS)=' \
  docs/forgejo-runner-pool/evidence/stap-a/caps.env >> forgejo-runner/.env
```

```text
# forgejo-runner/labels.txt
# Canonieke geordende labellijst. De labelnaam blijft gelijk aan de live
# installatie; de imageverwijzing is digest-gepind (7.4).
ubuntu-latest:docker://catthehacker/ubuntu@sha256:VUL_IN
```

```text
# forgejo-runner/allowed-job-images.txt
# Digests die de scrub mag behouden, met hun grootte in bytes.
# preflight.sh telt deze groottes op bij de vereiste vrije schijfruimte.
catthehacker/ubuntu@sha256:VUL_IN	VUL_IN
```

De labelnaam en de imageverwijzing komen uit `runner-registration.json` van Task 2 — het legacy `.runner`-veld `labels` is de canonieke bron, niet het Forgejo-record, dat alleen kale labelnamen toont. Vergelijk met een YAML- of JSON-parser en een canonieke JSON-weergave, nooit met een inspringingsgevoelige `awk`-extractie.

- [ ] **Step 5: Schrijf `compose.yaml`**

```yaml
# forgejo-runner/compose.yaml
# Gedeelde runner- en DinD-stack. Byte-identiek op beide hosts.
# De runnerservice staat onder het profiel "cycle": `docker compose up -d` start
# uitsluitend DinD, en alleen de cyclecontroller maakt per job een runner aan.

services:
  dind:
    image: ${DIND_IMAGE}
    restart: always
    privileged: true          # bewuste keuze, 7.6; alleen hier, nooit op jobcontainers
    command: ["dockerd", "--host=tcp://0.0.0.0:2375", "--tls=false"]
    environment:
      - DOCKER_TLS_CERTDIR=
    networks:
      - runner-control
    volumes:
      - dind-data:/var/lib/docker
    healthcheck:
      test: ["CMD", "docker", "-H", "tcp://127.0.0.1:2375", "info"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s
    cpus: ${DIND_CPUS}
    mem_limit: ${DIND_MEM}
    pids_limit: ${DIND_PIDS}
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  runner:
    image: ${RUNNER_IMAGE}
    profiles: ["cycle"]
    restart: "no"             # de controller is de enige eigenaar van de levenscyclus
    depends_on:
      dind:
        condition: service_healthy
    environment:
      - DOCKER_HOST=tcp://dind:2375
    networks:
      - runner-control
    volumes:
      - ./runner-config.yml:/etc/forgejo-runner/config.yml:ro
      - /opt/forgejo-runner/credentials/forgejo-token:/run/forgejo-runner-credentials/forgejo-token:ro
    cpus: ${RUNNER_CPUS}
    mem_limit: ${RUNNER_MEM}
    pids_limit: ${RUNNER_PIDS}
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

networks:
  runner-control:
    driver: bridge
    internal: false           # DinD moet images kunnen pullen; geen hostpoorten

volumes:
  dind-data:
    name: forgejo-runner-dind-data
```

- [ ] **Step 6: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_compose_contract.bats`
Expected: PASS — 10 tests, 0 failures. De twee laatste tests falen zolang `VUL_IN` niet is vervangen; vul eerst de echte digests in.

- [ ] **Step 7: Valideer Compose statisch**

```bash
cd forgejo-runner && cp .env.example .env && docker compose config >/dev/null && echo "compose config OK"
```

Expected: `compose config OK`. Faalt dit, dan klopt de syntax of ontbreekt een variabele.

- [ ] **Step 8: Commit**

```bash
git add forgejo-runner/compose.yaml forgejo-runner/.env.example forgejo-runner/labels.txt \
        forgejo-runner/allowed-job-images.txt forgejo-runner/scripts/resolve-digests.sh \
        forgejo-runner/tests/test_compose_contract.bats \
        docs/forgejo-runner-pool/evidence/stap-a/resolved-digests.tsv
git commit -m "feat(stap-b): compose, digest-gepinde images en canoniek labelcontract"
```

---

### Task 17: Runnerconfig, policy en validatie tegen de echte image

§4 eist exact één `server.connections`-verbinding, `capacity: 1` en een absoluut `token_url`. §7.5 legt de configknoppen vast. Deze taak valideert dat tegen de **echte** Runner 12.10.1-image in plaats van tegen documentatie.

**Files:**
- Create: `forgejo-runner/runner-config.policy.yml`
- Create: `forgejo-runner/scripts/render-config.sh`
- Test: `forgejo-runner/tests/test_render_config.bats`

**Interfaces:**
- Consumes: `labels.txt` uit Task 16
- Produces: `runner-config.yml` per host, met de UUID van die host en zonder enige tokenwaarde

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_render_config.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/render-config.sh"
  POLICY="$REPO_ROOT/forgejo-runner/runner-config.policy.yml"
  LABELS="$BATS_TEST_TMPDIR/labels.txt"
  echo 'ubuntu-latest:docker://catthehacker/ubuntu@sha256:abc' > "$LABELS"
  OUT="$BATS_TEST_TMPDIR/runner-config.yml"
}

@test "rendert exact een connection" {
  bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 --labels "$LABELS" \
    --policy "$POLICY" --out "$OUT"
  run python3 -c "
import re
tekst = open('$OUT').read()
print(len(re.findall(r'^\s+forgejo:', tekst, re.M)))
"
  [ "$output" = "1" ]
}

@test "gebruikt het absolute token_url en geen placeholder" {
  bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 --labels "$LABELS" \
    --policy "$POLICY" --out "$OUT"
  grep -q 'token_url: file:/run/forgejo-runner-credentials/forgejo-token' "$OUT"
  run grep -c 'CREDENTIALS_DIRECTORY' "$OUT"
  [ "$output" = "0" ]
}

@test "bevat geen tokenwaarde" {
  bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 --labels "$LABELS" \
    --policy "$POLICY" --out "$OUT"
  run grep -cE '^\s+token:' "$OUT"
  [ "$output" = "0" ]
}

@test "zet capacity op 1 en docker_host op streepje" {
  bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 --labels "$LABELS" \
    --policy "$POLICY" --out "$OUT"
  grep -qE 'capacity: *1' "$OUT"
  grep -qE 'docker_host: *"-"' "$OUT"
}

@test "neemt de labels uit labels.txt over" {
  bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 --labels "$LABELS" \
    --policy "$POLICY" --out "$OUT"
  grep -q 'catthehacker/ubuntu@sha256:abc' "$OUT"
}

@test "weigert een lege labellijst" {
  : > "$BATS_TEST_TMPDIR/leeg.txt"
  run bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 \
    --labels "$BATS_TEST_TMPDIR/leeg.txt" --policy "$POLICY" --out "$OUT"
  [ "$status" -ne 0 ]
}

@test "weigert een label zonder digest" {
  echo 'ubuntu-latest:docker://catthehacker/ubuntu:act-latest' > "$BATS_TEST_TMPDIR/tag.txt"
  run bash "$SCRIPT" --uuid 11111111-2222-3333-4444-555555555555 \
    --labels "$BATS_TEST_TMPDIR/tag.txt" --policy "$POLICY" --out "$OUT"
  [ "$status" -ne 0 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_render_config.bats`
Expected: FAIL — script en policy bestaan nog niet.

- [ ] **Step 3: Schrijf de policy**

```yaml
# forgejo-runner/runner-config.policy.yml
# Gedeelde policy: geldt byte-identiek op beide hosts. Bevat nooit een UUID,
# token of hostnaam; render-config.sh voegt het hostspecifieke deel toe.
log:
  level: info

runner:
  capacity: 1                 # 4: een job tegelijk per DinD
  timeout: 3h
  shutdown_timeout: 3m
  fetch_timeout: 5s
  fetch_interval: 2s
  envs:
    DOCKER_HOST: tcp://dind.internal:2375   # 7.5, job- en stepcontainers

cache:
  enabled: false              # 7.9: geen state tussen jobs

container:
  network: ""
  privileged: false           # jobcontainers nooit privileged
  docker_host: "-"            # 7.5: gebruik DOCKER_HOST, mount geen socket
  valid_volumes: []
  options: --add-host=dind.internal:host-gateway

host:
  workdir_parent: /tmp/forgejo-runner
```

- [ ] **Step 4: Schrijf de renderer**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/render-config.sh
# Bouwt de hostconfig uit de gedeelde policy, het canonieke labelblok en de
# hostspecifieke UUID. Schrijft nooit een tokenwaarde: 6 legt het token in een
# apart bestand dat via token_url wordt gelezen.
set -euo pipefail

UUID="" ; LABELS="" ; POLICY="" ; OUT="" ; URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
while [ $# -gt 0 ]; do
  case "$1" in
    --uuid)   UUID="$2"   ; shift 2 ;;
    --labels) LABELS="$2" ; shift 2 ;;
    --policy) POLICY="$2" ; shift 2 ;;
    --out)    OUT="$2"    ; shift 2 ;;
    --url)    URL="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$UUID" ] && [ -n "$LABELS" ] && [ -n "$POLICY" ] && [ -n "$OUT" ] || {
  printf 'gebruik: --uuid UUID --labels BESTAND --policy BESTAND --out BESTAND\n' >&2 ; exit 2 ; }

# 7.4: een lege lijst of een mutabele tag zonder digest is een harde fout.
grep -qE '\S' "$LABELS" || { printf 'labels.txt is leeg\n' >&2 ; exit 3 ; }
while read -r regel; do
  case "$regel" in
    ''|'#'*) continue ;;
    *@sha256:*) : ;;
    *) printf 'label zonder digest: %s\n' "$regel" >&2 ; exit 4 ;;
  esac
done < "$LABELS"

{
  cat "$POLICY"
  printf '\nserver:\n  connections:\n    forgejo:\n'
  printf '      url: %s\n' "$URL"
  printf '      uuid: %s\n' "$UUID"
  printf '      token_url: file:/run/forgejo-runner-credentials/forgejo-token\n'
  printf '      labels:\n'
  while read -r regel; do
    case "$regel" in ''|'#'*) continue ;; esac
    printf '        - %s\n' "$regel"
  done < "$LABELS"
} > "$OUT"

printf 'config gerenderd naar %s\n' "$OUT"
```

- [ ] **Step 5: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_render_config.bats`
Expected: PASS — 7 tests, 0 failures.

- [ ] **Step 6: Valideer tegen de echte Runner 12.10.1-image**

Dit is de gate die §8 stap B eist: de opdracht en de configvorm worden tegen de image bevestigd, niet tegen documentatie.

```bash
source ~/.zshenv
bash forgejo-runner/scripts/render-config.sh \
  --uuid 00000000-0000-4000-8000-000000000000 \
  --labels forgejo-runner/labels.txt \
  --policy forgejo-runner/runner-config.policy.yml \
  --out /tmp/validate-config.yml

# 1. bestaat one-job en kent het --wait?
ssh janpeter@max2 'docker run --rm --entrypoint forgejo-runner \
  ${RUNNER_IMAGE:-code.forgejo.org/forgejo/runner:12} one-job --help' | tee /tmp/one-job-help.txt
grep -q -- '--wait' /tmp/one-job-help.txt

# 2. accepteert de binary deze config zonder legacy .runner?
scp /tmp/validate-config.yml janpeter@max2:/tmp/
ssh janpeter@max2 'docker run --rm -v /tmp/validate-config.yml:/c.yml:ro \
  --entrypoint forgejo-runner ${RUNNER_IMAGE:-code.forgejo.org/forgejo/runner:12} \
  --config /c.yml one-job --help' ; echo "exit=$?"
```

Expected: `--wait` staat letterlijk in de helptekst van `one-job`, en de configvalidatie geeft exit 0. Ontbreekt `--wait`, of weigert de binary de config, dan is dat een BLOCKER voor het ontwerp en stopt dit plan hier.

- [ ] **Step 7: Bewijs dat een ongeldige config non-zero geeft**

```bash
printf 'server:\n  connections:\n    a: {url: "x"}\n    b: {url: "y"}\n' > /tmp/twee-connections.yml
scp /tmp/twee-connections.yml janpeter@max2:/tmp/
ssh janpeter@max2 'docker run --rm -v /tmp/twee-connections.yml:/c.yml:ro \
  --entrypoint forgejo-runner ${RUNNER_IMAGE:-code.forgejo.org/forgejo/runner:12} \
  --config /c.yml one-job --wait' ; echo "exit=$?"
```

Expected: een non-zero exitcode. Dit is het bewijs dat §7.9 nodig heeft: non-zero bij `--wait` duidt op config-, initialisatie-, poller- of runtimefalen en mag nooit tot heropenen leiden. Leg de exitcode vast in `docs/forgejo-runner-pool/evidence/stap-a/exitcodecontract.md`.

- [ ] **Step 8: Commit**

```bash
git add forgejo-runner/runner-config.policy.yml forgejo-runner/scripts/render-config.sh \
        forgejo-runner/tests/test_render_config.bats \
        docs/forgejo-runner-pool/evidence/stap-a/exitcodecontract.md
git commit -m "feat(stap-b): runnerconfig, policy en validatie tegen de echte image"
```

---

### Task 18: Scrub binnen de eigen DinD

§7.9 eist na iedere job een volledige scrub binnen uitsluitend de eigen DinD: alle containers, volumes, niet-standaardnetwerken, lokaal gebouwde of niet-toegestane images en de volledige BuildKit-cache verdwijnen. Alleen jobimages waarvan de exacte digest in `allowed-job-images.txt` staat blijven behouden. De outer Runner- en DinD-images staan in de **hostdaemon** en worden door deze inner scrub niet geraakt — dat was de kern van de deels verworpen ronde-3-bevinding.

De scrub mag maximaal vijf minuten duren. Een overschrijding alarmeert, quarantaint die host en reset de stabiliteitsperiode.

**Files:**
- Create: `forgejo-runner/scripts/scrub-dind.sh`
- Test: `forgejo-runner/tests/test_scrub_dind.bats`

**Interfaces:**
- Consumes: `allowed-job-images.txt` uit Task 16
- Produces: exitcode `0` bij een bewezen schone DinD, `50` bij een resterend object, `51` bij tijdsoverschrijding; op stdout een regel per bewijscategorie

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_scrub_dind.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/scrub-dind.sh"
  ALLOW="$BATS_TEST_TMPDIR/allow.txt"
  echo "catthehacker/ubuntu@sha256:abc	2147483648" > "$ALLOW"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  STATE="$BATS_TEST_TMPDIR/state"
  mkdir -p "$STATE"
  : > "$STATE/containers" ; : > "$STATE/volumes"
  echo "bridge" > "$STATE/networks" ; echo "host" >> "$STATE/networks" ; echo "none" >> "$STATE/networks"
  echo "catthehacker/ubuntu@sha256:abc" > "$STATE/images"
  cat > "$FAKE_BIN/docker" <<EOS
#!/usr/bin/env bash
STATE="$STATE"
case "\$*" in
  *"ps -aq"*)          cat "\$STATE/containers" ;;
  *"volume ls -q"*)    cat "\$STATE/volumes" ;;
  *"network ls"*)      cat "\$STATE/networks" ;;
  *"images --digests"*|*"image ls"*) cat "\$STATE/images" ;;
  *"builder prune"*|*"rm "*|*"volume rm"*|*"network rm"*|*"rmi"*) : ;;
  *"buildx du"*)       echo "0B" ;;
esac
EOS
  chmod +x "$FAKE_BIN/docker"
  PATH="$FAKE_BIN:$PATH"
}

@test "schone dind levert exit 0" {
  run bash "$SCRIPT" --endpoint tcp://dind:2375 --allow "$ALLOW"
  [ "$status" -eq 0 ]
}

@test "een achtergebleven container faalt met 50" {
  echo "c1" > "$BATS_TEST_TMPDIR/state/containers"
  run bash "$SCRIPT" --endpoint tcp://dind:2375 --allow "$ALLOW"
  [ "$status" -eq 50 ]
  [[ "$output" == *"container"* ]]
}

@test "een achtergebleven volume faalt met 50" {
  echo "v1" > "$BATS_TEST_TMPDIR/state/volumes"
  run bash "$SCRIPT" --endpoint tcp://dind:2375 --allow "$ALLOW"
  [ "$status" -eq 50 ]
}

@test "een niet-standaardnetwerk faalt met 50" {
  echo "vreemd" >> "$BATS_TEST_TMPDIR/state/networks"
  run bash "$SCRIPT" --endpoint tcp://dind:2375 --allow "$ALLOW"
  [ "$status" -eq 50 ]
}

@test "een image buiten de allowlist faalt met 50" {
  echo "zelfgebouwd@sha256:def" >> "$BATS_TEST_TMPDIR/state/images"
  run bash "$SCRIPT" --endpoint tcp://dind:2375 --allow "$ALLOW"
  [ "$status" -eq 50 ]
  [[ "$output" == *"image"* ]]
}

@test "gebruikt nooit de host-docker-socket" {
  run grep -c 'docker.sock' "$SCRIPT"
  [ "$output" = "0" ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_scrub_dind.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de implementatie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/scrub-dind.sh
# Fenced cleanup binnen uitsluitend de eigen DinD (7.9).
# Draait terwijl er aantoonbaar geen runnerproces bestaat.
# De outer Runner- en DinD-images staan in de hostdaemon en worden hier niet geraakt.
set -euo pipefail

ENDPOINT="" ; ALLOW="" ; MAX_SECONDS="${SCRUB_MAX_SECONDS:-300}"
while [ $# -gt 0 ]; do
  case "$1" in
    --endpoint) ENDPOINT="$2" ; shift 2 ;;
    --allow)    ALLOW="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$ENDPOINT" ] && [ -f "$ALLOW" ] || {
  printf 'gebruik: scrub-dind.sh --endpoint tcp://dind:2375 --allow BESTAND\n' >&2 ; exit 2 ; }

START="$(date +%s)"
d() { docker -H "$ENDPOINT" "$@" ; }

toegestaan() {
  awk '{print $1}' "$ALLOW" | grep -Fxq "$1"
}

# Opruimen. Fouten worden genegeerd; het bewijs hieronder is wat telt.
d ps -aq | while read -r id; do [ -n "$id" ] && d rm -f "$id" || true ; done
d volume ls -q | while read -r v; do [ -n "$v" ] && d volume rm -f "$v" || true ; done
d network ls --format '{{.Name}}' | while read -r n; do
  case "$n" in bridge|host|none|'') : ;; *) d network rm "$n" || true ;; esac
done
d builder prune -af >/dev/null 2>&1 || true
d images --digests --format '{{.Repository}}@{{.Digest}}' | while read -r img; do
  [ -n "$img" ] || continue
  toegestaan "$img" || d rmi -f "$img" || true
done

# Bewijs. Vanaf hier bepaalt de meting de exitcode.
FALEN=0
melden() { printf '%s: %s\n' "$1" "$2" ; [ "$2" = "FAIL" ] && FALEN=1 ; return 0 ; }

[ -z "$(d ps -aq)" ] && melden containers OK || melden containers FAIL
[ -z "$(d volume ls -q)" ] && melden volumes OK || melden volumes FAIL

VREEMD="$(d network ls --format '{{.Name}}' | grep -vxE 'bridge|host|none' || true)"
[ -z "$VREEMD" ] && melden netwerken OK || melden netwerken FAIL

NIET_TOEGESTAAN=""
while read -r img; do
  [ -n "$img" ] || continue
  toegestaan "$img" || NIET_TOEGESTAAN="$NIET_TOEGESTAAN $img"
done < <(d images --digests --format '{{.Repository}}@{{.Digest}}')
[ -z "$NIET_TOEGESTAAN" ] && melden images OK || melden images FAIL

DUUR=$(( $(date +%s) - START ))
printf 'duur_seconden: %s\n' "$DUUR"
[ "$DUUR" -le "$MAX_SECONDS" ] || exit 51
[ "$FALEN" -eq 0 ] || exit 50
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_scrub_dind.bats`
Expected: PASS — 6 tests, 0 failures.

- [ ] **Step 5: Lint en commit**

```bash
shellcheck forgejo-runner/scripts/scrub-dind.sh
git add forgejo-runner/scripts/scrub-dind.sh forgejo-runner/tests/test_scrub_dind.bats
git commit -m "feat(stap-b): fenced scrub binnen de eigen DinD met schoonbewijs"
```

---

### Task 19: Systemd-unit

§6 legt de unit vast: `systemctl enable --now`, met minimaal `Requires=docker.service`, `After=docker.service network-online.target`, `Wants=network-online.target` en `WantedBy=multi-user.target`. Bij boot start eerst alleen DinD; pas na een groene healthcheck gaat de controller naar `SOURCE_WAIT`. De boot-SLA is vijf minuten van `docker.service=active` tot `WAITING`.

**Files:**
- Create: `forgejo-runner/forgejo-runner-cycle.service`
- Test: `forgejo-runner/tests/test_unit_contract.bats`

**Interfaces:**
- Consumes: `forgejo_runner_cycle.py` uit Task 11 tot en met 15
- Produces: een systemd-unit die op beide hosts identiek is

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_unit_contract.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  UNIT="$REPO_ROOT/forgejo-runner/forgejo-runner-cycle.service"
}

@test "unit heeft alle vier verplichte afhankelijkheden" {
  grep -q '^Requires=docker.service' "$UNIT"
  grep -q '^After=docker.service network-online.target' "$UNIT"
  grep -q '^Wants=network-online.target' "$UNIT"
  grep -q '^WantedBy=multi-user.target' "$UNIT"
}

@test "unit start de python-controller en geen shellscript" {
  grep -qE '^ExecStart=.*forgejo_runner_cycle\.py' "$UNIT"
  run grep -cE '^ExecStart=.*\.sh' "$UNIT"
  [ "$output" = "0" ]
}

@test "unit herstart niet automatisch op een manier die de gates omzeilt" {
  grep -qE '^Restart=on-failure' "$UNIT"
  grep -qE '^RestartSec=' "$UNIT"
}

@test "unit bevat geen secrets" {
  run grep -ciE 'token|password|secret' "$UNIT"
  [ "$output" = "0" ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_unit_contract.bats`
Expected: FAIL — de unit bestaat nog niet.

- [ ] **Step 3: Schrijf de unit**

```ini
# forgejo-runner/forgejo-runner-cycle.service
[Unit]
Description=Forgejo Runner cyclecontroller (een job per runnerproces)
Documentation=https://git.jp-visser.nl/janpeter/scrum4me-server/src/branch/main/docs/forgejo-runner-pool/migratieontwerp.md
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/forgejo-runner
ExecStart=/usr/bin/python3 /opt/forgejo-runner/scripts/forgejo_runner_cycle.py --config /opt/forgejo-runner/controller.toml
# De controller houdt zijn eigen toestand vast; een restart begint altijd
# opnieuw in SOURCE_WAIT en doorloopt alle gates. Een unit-restart omzeilt
# nooit een fence of een quarantaine.
Restart=on-failure
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=300
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=false

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_unit_contract.bats`
Expected: PASS — 4 tests, 0 failures.

- [ ] **Step 5: Valideer de unitsyntax zonder hem te installeren**

```bash
scp forgejo-runner/forgejo-runner-cycle.service janpeter@max2:/tmp/
ssh janpeter@max2 'systemd-analyze verify /tmp/forgejo-runner-cycle.service' ; echo "exit=$?"
```

Expected: geen fouten over onbekende directives. Waarschuwingen over het nog niet bestaande `ExecStart`-pad zijn verwacht: de bundel wordt pas in stap D uitgerold. Installeer de unit hier **niet** — dat is stap D.

- [ ] **Step 6: Commit**

```bash
git add forgejo-runner/forgejo-runner-cycle.service forgejo-runner/tests/test_unit_contract.bats
git commit -m "feat(stap-b): systemd-unit voor de cyclecontroller"
```

---

### Task 20: Verificatiescript met bundelhash en `BUNDLE_COMMIT`

§6.1 maakt dit de mechanische invulling van "byte-identiek": iedere host houdt zijn uitgerolde commit-SHA vast in `/opt/forgejo-runner/BUNDLE_COMMIT`, en `verify-stack.sh` vergelijkt die plus een canonieke hash over de bundelbestanden met de andere host.

**Files:**
- Create: `forgejo-runner/scripts/bundle-hash.sh`
- Create: `forgejo-runner/scripts/verify-stack.sh`
- Test: `forgejo-runner/tests/test_bundle_hash.bats`

**Interfaces:**
- Consumes: de bundelbestanden uit Task 16 tot en met 19
- Produces: `bundle-hash.sh` schrijft één sha256 over de gesorteerde inhoud van alle bundelbestanden; `verify-stack.sh` faalt met `60` bij een ontbrekende of afwijkende `BUNDLE_COMMIT` en met `61` bij een afwijkende bundelhash

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_bundle_hash.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/bundle-hash.sh"
  BUNDLE="$BATS_TEST_TMPDIR/bundel"
  mkdir -p "$BUNDLE/scripts"
  echo "a" > "$BUNDLE/compose.yaml"
  echo "b" > "$BUNDLE/scripts/x.sh"
}

@test "levert een stabiele hash bij gelijke inhoud" {
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" = "$h2" ]
  [ "${#h1}" -eq 64 ]
}

@test "verandert bij gewijzigde inhoud" {
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  echo "gewijzigd" > "$BUNDLE/compose.yaml"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" != "$h2" ]
}

@test "verandert bij een hernoemd bestand" {
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  mv "$BUNDLE/scripts/x.sh" "$BUNDLE/scripts/y.sh"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" != "$h2" ]
}

@test "negeert .env met echte waarden" {
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  echo "TOKEN=geheim" > "$BUNDLE/.env"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" = "$h2" ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_bundle_hash.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de hashfunctie**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/bundle-hash.sh
# Canonieke hash over de bundelbestanden (6.1). Pad en inhoud tellen allebei
# mee, zodat een hernoeming de hash verandert. .env blijft buiten de hash:
# dat bestand is hostlokaal en mag afwijken.
set -euo pipefail

BUNDLE="${1:-}"
[ -d "$BUNDLE" ] || { printf 'gebruik: bundle-hash.sh BUNDELMAP\n' >&2 ; exit 2 ; }

# Ubuntu levert sha256sum, mac shasum. Gemeten 2026-08-31: shasum bestaat op
# beide hosts en op mac, en beide commando's geven dezelfde uitvoerindeling.
# De detectie is dus geen aanname over een ontbrekend commando maar een
# garantie dat mac en host dezelfde hash produceren.
if command -v sha256sum >/dev/null 2>&1; then
  HASHER=(sha256sum)
else
  HASHER=(shasum -a 256)
fi

cd "$BUNDLE"
find . -type f ! -name '.env' ! -path './tests/*' -print0 \
  | LC_ALL=C sort -z \
  | while IFS= read -r -d '' pad; do
      printf '%s\0' "$pad"
      cat "$pad"
      printf '\0'
    done \
  | "${HASHER[@]}" \
  | awk '{print $1}'
```

De hash dekt pad én inhoud, zodat een hernoeming hem verandert. `.env` en `tests/` blijven erbuiten: het eerste is hostlokaal, het tweede draait niet mee op de hosts.

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_bundle_hash.bats`
Expected: PASS — 4 tests, 0 failures.

- [ ] **Step 5: Schrijf `verify-stack.sh`**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/verify-stack.sh
# Verifieert de uitgerolde stack op deze host (6.1, 7.5, 7.6).
# Exit 0 groen, 60 commit-drift, 61 bundelhash-drift, 62 isolatiefout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$SCRIPT_DIR/.."
VERWACHT_COMMIT="${1:-}"
VERWACHTE_HASH="${2:-}"
[ -n "$VERWACHT_COMMIT" ] && [ -n "$VERWACHTE_HASH" ] || {
  printf 'gebruik: verify-stack.sh COMMIT_SHA BUNDEL_HASH\n' >&2 ; exit 2 ; }

HUIDIG_COMMIT="$(cat /opt/forgejo-runner/BUNDLE_COMMIT 2>/dev/null || true)"
[ -n "$HUIDIG_COMMIT" ] || { printf 'BUNDLE_COMMIT ontbreekt\n' >&2 ; exit 60 ; }
[ "$HUIDIG_COMMIT" = "$VERWACHT_COMMIT" ] || {
  printf 'commit-drift: host %s, verwacht %s\n' "$HUIDIG_COMMIT" "$VERWACHT_COMMIT" >&2 ; exit 60 ; }

HUIDIGE_HASH="$(bash "$SCRIPT_DIR/bundle-hash.sh" "$BUNDLE")"
[ "$HUIDIGE_HASH" = "$VERWACHTE_HASH" ] || {
  printf 'bundelhash-drift: host %s, verwacht %s\n' "$HUIDIGE_HASH" "$VERWACHTE_HASH" >&2 ; exit 61 ; }

# Isolatie: geen hostlistener op de Docker-API-poorten (7.5).
if ss -ltn 2>/dev/null | grep -qE ':(2375|2376)\b'; then
  printf 'isolatiefout: er luistert iets op 2375 of 2376\n' >&2 ; exit 62
fi

printf 'commit: %s\nbundel_hash: %s\nisolatie: OK\n' "$HUIDIG_COMMIT" "$HUIDIGE_HASH"
```

- [ ] **Step 6: Bewijs dat drift wordt gedetecteerd**

```bash
shellcheck forgejo-runner/scripts/bundle-hash.sh forgejo-runner/scripts/verify-stack.sh
HASH="$(bash forgejo-runner/scripts/bundle-hash.sh forgejo-runner)"
COMMIT="$(git rev-parse HEAD)"
echo "bundelhash op deze commit: $HASH"
bash forgejo-runner/scripts/verify-stack.sh "$COMMIT" "afwijkende-hash" ; echo "exit=$?"
```

Expected: de laatste aanroep geeft `exit=60` of `61` — nooit 0. Een gate die niet kan falen is geen gate.

- [ ] **Step 7: Commit**

```bash
git add forgejo-runner/scripts/bundle-hash.sh forgejo-runner/scripts/verify-stack.sh \
        forgejo-runner/tests/test_bundle_hash.bats
git commit -m "feat(stap-b): bundelhash en verify-stack met driftdetectie"
```

---

### Task 21: Secret-scan en pre-commit hook

Delta-review R12 sloot §6.1 op het punt dat er vandaag géén doorlopende scan draait — alleen de eenmalige scan van stap B. Deze taak levert de scan, installeert hem, en **bewijst** dat hij een commit met een tokenpatroon blokkeert. Pas na dat bewijs mag het ontwerp beweren dat de scan draait.

**Files:**
- Create: `forgejo-runner/scripts/secret-scan.sh`
- Create: `forgejo-runner/scripts/install-git-hooks.sh`
- Test: `forgejo-runner/tests/test_secret_scan.bats`

**Interfaces:**
- Consumes: niets
- Produces: `secret-scan.sh` leest paden van de commandoregel of staged bestanden uit `git diff --cached --name-only`; exit `0` schoon, `70` bij een treffer. `install-git-hooks.sh` installeert hem als `pre-commit` in een opgegeven werkboom.

- [ ] **Step 1: Schrijf de falende test**

```bash
# forgejo-runner/tests/test_secret_scan.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/secret-scan.sh"
  WERK="$BATS_TEST_TMPDIR/werk"
  mkdir -p "$WERK"
}

@test "schone inhoud levert exit 0" {
  echo "log:\n  level: info" > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 0 ]
}

@test "een forgejo-tokenpatroon wordt geblokkeerd" {
  printf 'token: %s\n' "$(printf 'a%.0s' {1..40})" > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 70 ]
}

@test "een private sleutel wordt geblokkeerd" {
  echo "-----BEGIN OPENSSH PRIVATE KEY-----" > "$WERK/id"
  run bash "$SCRIPT" "$WERK/id"
  [ "$status" -eq 70 ]
}

@test "een secretbestandsnaam wordt geblokkeerd" {
  echo "wat dan ook" > "$WERK/forgejo-token"
  run bash "$SCRIPT" "$WERK/forgejo-token"
  [ "$status" -eq 70 ]
}

@test "een digest is geen secret" {
  echo "image: catthehacker/ubuntu@sha256:$(printf 'b%.0s' {1..64})" > "$WERK/labels.txt"
  run bash "$SCRIPT" "$WERK/labels.txt"
  [ "$status" -eq 0 ]
}

@test "een uuid is geen secret" {
  echo "uuid: 11111111-2222-3333-4444-555555555555" > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 0 ]
}

@test "de placeholder token_url is geen secret" {
  echo "token_url: file:/run/forgejo-runner-credentials/forgejo-token" > "$WERK/c.yml"
  run bash "$SCRIPT" "$WERK/c.yml"
  [ "$status" -eq 0 ]
}
```

- [ ] **Step 2: Draai de test en bevestig dat hij faalt**

Run: `bats forgejo-runner/tests/test_secret_scan.bats`
Expected: FAIL — het script bestaat nog niet.

- [ ] **Step 3: Schrijf de scan**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/secret-scan.sh
# Blokkeert secrets voordat ze in Git belanden (6.1).
# Zonder argumenten scant hij de staged bestanden.
# Exit 0 schoon, 70 bij een treffer.
set -uo pipefail

bestanden=("$@")
if [ "${#bestanden[@]}" -eq 0 ]; then
  mapfile -t bestanden < <(git diff --cached --name-only --diff-filter=ACM)
fi
[ "${#bestanden[@]}" -gt 0 ] || exit 0

TREFFER=0
for pad in "${bestanden[@]}"; do
  [ -f "$pad" ] || continue

  # 1. Bestandsnamen die per definitie een secret dragen.
  case "$(basename "$pad")" in
    forgejo-token|*.key|*.pem|.env)
      printf 'secret-scan: %s is een secretbestand en hoort niet in Git\n' "$pad" >&2
      TREFFER=1 ; continue ;;
  esac

  # 2. Private sleutels.
  if grep -qE 'BEGIN (OPENSSH|RSA|EC|PGP) PRIVATE KEY' "$pad"; then
    printf 'secret-scan: %s bevat een private sleutel\n' "$pad" >&2
    TREFFER=1 ; continue
  fi

  # 3. Een token-achtige waarde achter een sleutelnaam. Digests en UUID's
  #    vallen hier bewust buiten: die staan legitiem in de bundel.
  if grep -nE '(token|secret|password)[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9_/+-]{20,}' "$pad" \
     | grep -vE 'sha256:|token_url|[0-9a-f]{8}-[0-9a-f]{4}-' >/dev/null; then
    printf 'secret-scan: %s bevat een tokenachtige waarde\n' "$pad" >&2
    TREFFER=1 ; continue
  fi
done

[ "$TREFFER" -eq 0 ] || exit 70
```

- [ ] **Step 4: Draai de test en bevestig dat hij slaagt**

Run: `bats forgejo-runner/tests/test_secret_scan.bats`
Expected: PASS — 7 tests, 0 failures.

- [ ] **Step 5: Schrijf de installer**

```bash
#!/usr/bin/env bash
# forgejo-runner/scripts/install-git-hooks.sh
# Installeert secret-scan.sh als pre-commit hook in een werkboom.
# Respecteert core.hooksPath: staat die gezet, dan installeert hij daar.
set -euo pipefail

WERKBOOM="${1:-}"
[ -d "$WERKBOOM/.git" ] || [ -f "$WERKBOOM/.git" ] || {
  printf 'gebruik: install-git-hooks.sh WERKBOOM\n' >&2 ; exit 2 ; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_PATH="$(git -C "$WERKBOOM" config --get core.hooksPath || true)"
if [ -n "$HOOKS_PATH" ]; then
  DOEL="$WERKBOOM/$HOOKS_PATH"
else
  DOEL="$(git -C "$WERKBOOM" rev-parse --git-path hooks)"
  DOEL="$WERKBOOM/$DOEL"
fi
mkdir -p "$DOEL"

cat > "$DOEL/pre-commit" <<EOS
#!/usr/bin/env bash
# Geinstalleerd door forgejo-runner/scripts/install-git-hooks.sh
exec "$SCRIPT_DIR/secret-scan.sh"
EOS
chmod +x "$DOEL/pre-commit"
printf 'pre-commit hook geinstalleerd in %s\n' "$DOEL"
```

- [ ] **Step 6: Installeer in beide werkbomen en bewijs dat de hook blokkeert**

Dit blokkeringsbewijs is wat §6.1 eist voordat het ontwerp mag beweren dat de scan draait.

```bash
bash forgejo-runner/scripts/install-git-hooks.sh /Users/janpetervisser/Development/scrum4me-server
bash forgejo-runner/scripts/install-git-hooks.sh /Users/janpetervisser/Development/max2

cd /tmp && rm -rf hooktest && git init -q hooktest && cd hooktest
bash /Users/janpetervisser/Development/scrum4me-server/forgejo-runner/scripts/install-git-hooks.sh /tmp/hooktest
printf 'token: %s\n' "$(printf 'a%.0s' {1..40})" > geheim.yml
git add geheim.yml
git commit -m "dit hoort te falen" ; echo "exit=$?"
cd / && rm -rf /tmp/hooktest
```

Expected: de commit faalt met een non-zero exitcode en de melding `secret-scan: … bevat een tokenachtige waarde`. Slaagt de commit wél, dan is de hook niet actief en mag §6.1 niet worden aangepast; onderzoek eerst `core.hooksPath`.

Leg de uitvoer vast in `docs/forgejo-runner-pool/evidence/stap-a/secret-scan-blokkeringsbewijs.txt`.

- [ ] **Step 7: Commit**

```bash
cd /Users/janpetervisser/Development/scrum4me-server
git add forgejo-runner/scripts/secret-scan.sh forgejo-runner/scripts/install-git-hooks.sh \
        forgejo-runner/tests/test_secret_scan.bats \
        docs/forgejo-runner-pool/evidence/stap-a/secret-scan-blokkeringsbewijs.txt
git commit -m "feat(stap-b): secret-scan met bewezen blokkerende pre-commit hook"
```

---

### Task 22: Bundel-README en de afsluitende gate van stap A en B

De laatste taak. Zij levert de README uit §6 en toetst of stap A en B werkelijk af zijn, zodat stap C op vaste grond begint.

**Files:**
- Create: `forgejo-runner/README.md`
- Create: `docs/forgejo-runner-pool/evidence/stap-a/afsluitgate.md`

**Interfaces:**
- Consumes: alle voorgaande taken
- Produces: een afsluitrapport dat per eis uit §8 stap A en stap B het bewijsbestand noemt

- [ ] **Step 1: Schrijf de bundel-README**

```markdown
# forgejo-runner — gedeelde bundel

Deze map is de **canonieke bron** van de Forgejo-Runner-poolbundel. Beide hosts
(`scrum4me-server` en `max2`) rollen uit vanaf dezelfde commit-SHA van deze repo.
De `max2`-repo bevat geen kopie; zie §6.1 van het migratieontwerp.

## Uitrollen

1. `bash scripts/preflight.sh --facts … --caps … --images allowed-job-images.txt`
   moet exit 0 geven. Faalt hij, dan wordt er niets uitgerold.
2. Kopieer de bundel naar `/opt/forgejo-runner/` op de host.
3. Schrijf de commit-SHA naar `/opt/forgejo-runner/BUNDLE_COMMIT`.
4. Zet het token als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`,
   eigendom van de effectieve runner-UID:GID. Het token komt nooit uit deze repo.
5. `docker compose up -d` start uitsluitend DinD; de runner staat onder het
   profiel `cycle` en wordt alleen door de cyclecontroller gestart.
6. `systemctl enable --now forgejo-runner-cycle.service`.
7. `bash scripts/verify-stack.sh <commit> <bundelhash>` moet exit 0 geven.

## Terugdraaien

Zet de unit eerst in `DRAINING`, wacht tot een geaccepteerde job terminaal is en
leg het Forgejo-side nulbewijs voor assigned/running jobs vast. Stop en disable
daarna de unit en verwijder alleen de runner- en DinD-containers. Laat het volume
`forgejo-runner-dind-data` staan voor onderzoek. Herstart nooit de host-Dockerdaemon.

## Wat hier bewust niet gebeurt

- Geen deployment via Forgejo Actions: jobcontainers draaien in DinD zonder
  host-Docker-socket en zonder hostpadvolumes en kunnen deze stack niet wijzigen.
- Geen wijziging aan `/etc/docker/daemon.json`, geen herstart van de Docker-daemon,
  geen hostbrede `docker system prune`.
- Geen gedeeld DinD-volume of gedeelde DinD tussen de hosts.
```

- [ ] **Step 2: Draai alle tests van de hele bundel**

```bash
bats forgejo-runner/tests/*.bats
python3 -m unittest discover -s forgejo-runner/tests -p 'test_*.py' -v
shellcheck -x forgejo-runner/scripts/*.sh
```

Expected: alles groen, geen shellcheck-bevindingen. Dit is de gate: is er ook maar één test rood, dan zijn stap A en B niet af.

Controleer daarna mechanisch dat geen enkele `Expected: PASS — N tests`-regel in dit plan is achtergelopen op de tests eronder. Die tellers zijn de enige plek waar een stil weggevallen test wordt betrapt, en ze lopen precies achter wanneer een reviewbevinding tests toevoegt:

```bash
python3 - <<'PY'
import re
regels = open("docs/forgejo-runner-pool/implementatieplan-stap-a-b.md", encoding="utf-8").read().split("\n")
koppen = [i for i, r in enumerate(regels) if r.startswith("### Task ")] + [len(regels)]
fout = 0
for k in range(len(koppen) - 1):
    blok = "\n".join(regels[koppen[k]:koppen[k + 1]])
    n = len(re.findall(r"^@test ", blok, re.M)) + len(re.findall(r"^\s+def test_", blok, re.M))
    for verwacht in re.findall(r"Expected: PASS — (\d+) tests", blok):
        if int(verwacht) != n:
            print(f"AFWIJKING in {regels[koppen[k]].strip()}: verwacht {verwacht}, geteld {n}")
            fout = 1
print("tellers kloppen" if not fout else "tellers lopen achter")
raise SystemExit(fout)
PY
```

Expected: `tellers kloppen`, exit 0. Wijkt er één af, werk dan de verwachting bij vóórdat je stap A en B afgerond verklaart.

- [ ] **Step 3: Schrijf het afsluitrapport**

Maak `docs/forgejo-runner-pool/evidence/stap-a/afsluitgate.md` met een tabel die iedere eis uit §8 stap A en stap B koppelt aan het bewijsbestand of de test die haar afdekt:

| Eis | Bewijs |
|---|---|
| image-ID's, manifestdigests, Compose, netwerken, volumes, health | `evidence/stap-a/scrum4me-server/images.json`, `containers.json`, `networks.json`, `volumes.json` |
| anonieme volume-ID en omvang inner-DinD-data | `evidence/stap-a/scrum4me-server/dind-usage.txt` |
| legacy `.runner`-metadata zonder tokenwaarde, met mode | `runner-registration.json`, `runner-registration-stat.txt` |
| volledige labels en global scope | `runner-registration.json`, `evidence/stap-a/forgejo/runners-summary.tsv` |
| alle zichtbare runnerrecords | `evidence/stap-a/forgejo/runners-summary.tsv` |
| `T_requeue` | `evidence/stap-a/t-requeue.md` |
| canonieke labelnamen uit de live `.runner` | `evidence/stap-a/shared-label-names.txt` |
| machineleesbare caps voor `preflight.sh` | `evidence/stap-a/caps.env` |
| NTP-status en klokskew op beide hosts | `evidence/stap-a/clock-scrum4me-server.txt`, `max2-clock.txt` |
| trustscope-gate met `.forgejo`/`.github`-fallback en allowlist | `evidence/stap-a/trust/trust-inventory.json`, `trust-verdict.json`, `trusted-actions-scope.yml` |
| vier readinessuitkomsten met stub/testharnas | `evidence/stap-a/testharnas-dekking.md` |
| fence, latch, deadline, maintenance | idem |
| piekmeting en caps | `evidence/stap-a/workload-scrum4me-server.tsv`, `caps.md` |
| jobduurbaseline | `evidence/stap-a/jobduur-baseline.md` |
| hostfeiten en headroom op beide hosts | `host-facts-*.tsv`, `caps.md`, `preflight-*.txt` |
| productiecontainers gezond vóór aanvang | `evidence/stap-a/productiecontainers-voor.txt` |
| registry-gevalideerde digests | `evidence/stap-a/resolved-digests.tsv` |
| Compose statisch gevalideerd | `tests/test_compose_contract.bats`, `docker compose config` |
| bundel gescand op secrets | `evidence/stap-a/secret-scan-blokkeringsbewijs.txt` |
| exact één connection, absoluut `token_url`, `one-job --wait` | `tests/test_render_config.bats`, `evidence/stap-a/exitcodecontract.md` |
| exitcodecontract vastgelegd | `evidence/stap-a/exitcodecontract.md` |
| ephemeral gemeten en voorgelegd | `evidence/stap-a/ephemeral-spike.md` |

Ontbreekt er een bewijsbestand, dan is de bijbehorende eis niet afgedekt en is stap A of B niet af.

- [ ] **Step 4: Werk het Review record van het ontwerp bij**

Voeg aan `docs/forgejo-runner-pool/migratieontwerp.md` onder §13 een korte notitie toe dat stap A en B zijn uitgevoerd, met de commit-SHA van dit plan en de datum. Wijzig verder niets aan het ontwerp: iedere inhoudelijke wijziging vraagt een nieuwe delta-review.

- [ ] **Step 5: Commit**

```bash
git add forgejo-runner/README.md docs/forgejo-runner-pool/evidence/stap-a/afsluitgate.md \
        docs/forgejo-runner-pool/migratieontwerp.md
git commit -m "feat(stap-b): bundel-README en afsluitgate van stap A en B"
```

---

## Wat hierna komt

Stap C tot en met H worden pas gepland wanneer stap A de meetwaarden heeft opgeleverd. Zonder de echte digests, caps, labels, `T_requeue` en de uitkomst van de ephemeral-spike zou een plan voor die stappen waarden moeten verzinnen, en dat is precies wat deze reviewloop tweemaal heeft afgestraft.

Twee besluitpunten liggen dan bij JP:

1. **De ephemeral-afweging** uit Task 4. Wordt ephemeral registratie opgenomen, dan raakt dat §7.3 en §7.4 van het ontwerp en vraagt het een delta-review vóór stap C.
2. **De uitkomst van de headroomgate** uit Task 9 en 10. Is een host rood, dan is dat volgens §7.8 een NO-GO voor identieke caps en volgt eerst een architectuurbesluit.

## Zelfcontrole van dit plan

Uitgevoerd na het schrijven, tegen het migratieontwerp.

**Dekking van stap A.** Iedere eis uit §8 stap A is aan een taak gekoppeld: inventarisatie (Task 2), runnerrecords en scope (Task 3), `T_requeue` (Task 3 step 6 en de evidence-tabel), klokskew (Task 5), trustgate met fallback (Task 6), stub/testharnas met alle vier readinessuitkomsten plus fence, latch, deadline en maintenance (Task 11 tot en met 15, samengevat in `testharnas-dekking.md`), piekmeting en caps (Task 7 tot en met 9), hostheadroom op beide hosts (Task 8 tot en met 10). De eis "verifieer dat de bestaande productiecontainers gezond zijn voordat iets wordt toegevoegd" staat in de afsluittabel van Task 22 met `productiecontainers-voor.txt` als bewijs; die momentopname hoort vóór Task 2 te worden gemaakt met `docker ps --format` op beide hosts.

**Dekking van stap B.** Bundel met Runner 12.10.1 en DinD-pin (Task 16), registry-validatie van beide digests en de jobimage (Task 16 step 3), Compose statisch gevalideerd inclusief `restart: "no"`, `restart: always` en het benoemde volume (Task 16 step 6 en 7), scan op secrets (Task 21), validatie van exact één connection, absoluut `token_url`, connection-labels en de letterlijke opdracht `one-job --wait` zonder legacy `.runner` (Task 17 step 6), en het exitcodecontract (Task 17 step 7).

**Bewust buiten dit plan.** `capture-current.sh` staat in §6 onder `scripts/` maar wordt hier al in stap A gebruikt; dat is geen afwijking, want §8 stap A vraagt precies die inventarisatie. `render-config.sh` levert in stap B alleen een validatieconfig; de echte hostconfig met een echte UUID ontstaat in stap C en D.

**Consistentie van namen en typen.** `ro_docker` (Task 1) wordt gebruikt in Task 2, 7 en 8. `Confirmation`, `ReadinessClass` en `SEVERITY` (Task 11) worden gebruikt in Task 12 tot en met 15. `Fence` en `latch_verdict` (Task 13) in Task 15. `MaintenanceRecord` (Task 14) in `tick`. `assignment_nulbewijs` (Task 15) wordt in stap D en F aangeroepen en is hier alleen gedefinieerd en getest. `allowed-job-images.txt` (Task 16) wordt gelezen door `preflight.sh` (Task 10) en `scrub-dind.sh` (Task 18) — Task 10 is daarom geschreven met `--images` als optioneel argument, zodat hij vóór Task 16 al draaibaar is.

**Bekende volgordeafhankelijkheden.** Er zijn er twee, allebei bewust en allebei zonder blokkade:

1. Task 10 (`preflight.sh`) leest `allowed-job-images.txt` uit Task 16. Zonder dat bestand telt de schijfdrempel alleen de 20 GiB werkruimte; met dat bestand telt hij de imagegroottes erbij op. Draai `preflight.sh` daarom na Task 16 nogmaals, vóór stap C.
2. Task 6 (trustgate) heeft de gedeelde labelnamen nodig. Die komen **niet** uit `labels.txt` van Task 16, maar uit `shared-label-names.txt` dat Task 2 step 7 uit de live `.runner` haalt. Na Task 16 draait de gate nogmaals met `labels.txt`, en de namen moeten dan identiek zijn.

## Review record

### Plan-review ronde 5 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`
**Requests:** `90247e57-71ac-439a-9380-21f3388344e4`, `83a6f717-cd3c-4dd7-b075-b44663443834`
**Replies:** `75fb9d0a-9670-4972-8424-00ba5ae349a7`, `3738d457-dd30-4faf-b700-57dfb410dead`
**Beoordeelde revisie:** 5515 regels, commit `8909ae0`, SHA-256 `5146655392ab5b65a86f525e5fd6746642dacee2d048669fd4654b6f2653fc96`
**Verdicts:** Codex NO-GO; Claude **GO**
**Tellingen:** Codex 0 BLOCKER / 1 MAJOR / 0 MINOR; Claude 0 BLOCKER / 0 MAJOR / 2 MINOR

Beide reviewers bevestigden dat de twee wijzigingen uit ronde 4 standhouden, inclusief dat `repos()` niet te streng is geworden: `{"data": []}` van een lege instance slaagt gewoon.

**De drie bevindingen komen uit dezelfde familie en zijn samen verwerkt.** Codex generaliseerde het patroon een niveau dieper — niet de respons als geheel, maar **verplichte velden binnen de gemeten objecten** werden nog als `False`, leeg of overslaan geïnterpreteerd: `bool(repo.get("has_actions"))` maakt een ontbrekend veld `False` en slaat daarmee de hele inspectie over, een ontbrekende `owner.login` liet de eigenaar wegvallen, een collaborator of teamlid zonder `login` werd stil overgeslagen, en een team zonder `permission` gold als niet-schrijvend. Claude's twee MINORs waren twee exemplaren van precies dat: de ontbrekende eigenaar, en `_decodeer` dat een respons zónder `encoding`-veld als platte tekst leest — waardoor base64 zou worden gescand, geen triggernaam zou opleveren en de repository ten onrechte schoon zou heten.

Claude mat beide MINOR-paden tegen de live instance en stelde vast dat ze vandaag niet bereikbaar zijn: alle 23 repositories in `/repos/search` hebben `owner.login`, en `contents`-responses dragen `encoding: base64`. Daarom MINOR en geen MAJOR — maar de faalrichting was in beide gevallen de verkeerde.

Verwerkt:

- `_valideer_repo()` eist `full_name`, een echte boolean `has_actions`, `owner.login` en `default_branch`; een repository die dat niet levert wordt als onleesbaar vastgelegd en overgeslagen, zodat de overige repositories nog wel worden gemeten en het oordeel toch rood wordt.
- Een collaborator of teamlid zonder `login` werpt `Unreadable` in plaats van te worden overgeslagen.
- Een team moet een `id` hebben en een `permission` uit `BEKENDE_TEAMROLLEN`; ontbrekend of onbekend is onleesbaar en niet "geen schrijver".
- `_schrijvers()` werpt `Unreadable` als de eigenaar leeg is, in plaats van de toevoeging over te slaan.
- `_decodeer()` eist dat de sleutel `encoding` aanwezig is; een leeg-maar-aanwezig veld blijft platte tekst.
- Negen tests erbij, Task 6 van 33 naar 42, inclusief een positieve tegenhanger die bewijst dat een volledig object gewoon groen blijft — de strengheid mag een correcte meting niet rood maken.

**Claude's zelfreflectie is de moeite van het vastleggen waard.** Het merkte op dat het in ronde 4 de keten verticaal had getraceerd — van HTTP-status via `Unreadable` naar aggregatie, `Verdict.ok` en exitcode — en op grond daarvan concludeerde dat de andere methoden "de strenge stand erven", terwijl juist een consument tussen die uiteinden het gat bevatte. Een verticale trace door één pad bewijst niets over de andere aanroepplekken. In ronde 5 zocht het daarom mechanisch op de vórm (`or {}`, `or []`, `or ""`, brede `except`-clausules) in plaats van op het verhaal.

### Plan-review ronde 4 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`
**Requests:** `65c6e879-0b6c-458e-a7f9-308f01c2664c`, `69ede2e0-0547-4876-b5b9-09d11f16076e`
**Replies:** `dbd6ed20-120f-46af-9dd4-df265f7f4a9a`, `f839934e-0220-4bae-914a-0904fec3a37a`
**Beoordeelde revisie:** 5461 regels, commit `171b79e`, SHA-256 `f2401dd39982a0ddfd5c1acf6d3dfa5c7ff130cef56d48fce6af067107a45154`
**Verdicts:** Codex NO-GO; Claude **GO**
**Tellingen:** Codex 0 BLOCKER / 1 MAJOR / 0 MINOR; Claude 0 BLOCKER / 0 MAJOR / 0 MINOR

Claude liep de fail-closed keten end-to-end na — van HTTP-status via `Unreadable`, de aggregatie in `inventory()`, `Verdict.ok` tot exitcode 30 — en vond geen defect. Codex bevestigde dat `_get()`, de beperking van `missing_ok` tot `contents()`, de verwijderde `or []`-fallbacks, de afvang van een 404 op een workflowbestand en het herstel van `urllib.request.urlopen` in een `finally` alle houden, en dat het tellerblok groen draait.

**MAJOR (codex, geaccepteerd en nagemeten):** één fail-open pad was blijven staan. `_schrijvers()` valideerde `collaborators()`, `teams()`, `team_members()` en `branch_protections()` op `None`, maar niet `collaborator_permission()`: daar stond nog `perm = client.collaborator_permission(...) or {}`. Bij een `None`, een lege of een malformed permissierespons werd `rol` daardoor `""` en verdween de collaborator stil uit `writers` — dezelfde klasse als de ronde-3-MAJOR, één niveau dieper, en juist bij de beslissende meting voor een identiteit. Zelf nagemeten op regel 1591 van de beoordeelde revisie.

Dit was de derde keer in deze loop dat een correctie op één plek werd toegepast en elders bleef staan. Bij het verwerken is daarom niet alleen de gemelde plek gerepareerd maar de hele gate opnieuw op dat patroon doorzocht, wat een **tweede, niet-gemelde exemplaar** opleverde:

- `_schrijvers()` werpt nu `Unreadable` als de permissierespons ontbreekt of geen van beide rolvelden bevat.
- `ForgejoClient.repos()` gebruikte `items = (data or {}).get("data", [])`. Een onverwachte respons leverde daar stilzwijgend een lege repolijst op — en een lege repolijst betekent "niets te toetsen" en dus een groene trustgate zonder ook maar één gemeten repository. `repos()` eist nu een dict met een lijst onder `data` en werpt anders `Unreadable`.
- Twee tests erbij, Task 6 van 31 naar 33: een collaborator zonder permissierespons, en een permissierespons zonder rolvelden; beide moeten in `verdict.unreadable` eindigen en het oordeel rood maken.

### Plan-review ronde 3 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`
**Requests:** `a422f9d4-bda6-4acc-ac3a-c483b79a45a9`, `eaaf2f0d-3d51-4bda-9dd9-5089b580be1c`
**Replies:** `dfa861b8-fe2f-4569-8218-107f708dc2f0`, `3bd405d6-39db-4cac-a4ae-8028e35f6c81`
**Beoordeelde revisie:** 5356 regels, commit `3aee497`, SHA-256 `09c0e32d6e91ae51dddb38fef4675c214d5e72bb60fffe3494297d356964a060`
**Verdicts:** Codex NO-GO; Claude **GO**
**Tellingen:** Codex 0 BLOCKER / 1 MAJOR / 0 MINOR; Claude 0 BLOCKER / 0 MAJOR / 0 MINOR

**De weerlegging uit ronde 2 is door beide reviewers geadjudiceerd als terecht.** Beiden lazen de responsketen zelf uit: het endpoint `/repos/{owner}/{repo}/collaborators/{collaborator}/permission` verwijst via `responses.RepoCollaboratorPermission` naar de gelijknamige definitie met `permission` (string), `role_name` en `user`; het booleanschema `Permission` hangt aan `Repository.permissions`. Codex bevestigde expliciet dat zijn eigen ronde-2-fix op de echte respons niets zou hebben gevonden. Alle drie de fixes uit ronde 2 houden stand.

**Claude mat bovendien dat de valide kern zwaarder woog dan het plan zelf stelde.** Live gecontroleerd: `janpeter/scrum4me-server` en `janpeter/max2` hebben allebei **nul collaborators**, terwijl `repo.owner.login` bij beide `janpeter` is. Zonder de toegevoegde eigenaarsregel was `writers` voor de enige twee repo's in scope dus niet onvolledig maar leeg, en had de trustgate nul schrijvers geïnventariseerd. Codex vond de juiste bug met de verkeerde onderbouwing.

Codex verifieerde daarnaast dat de nieuwe tellercontrole discrimineert: een in-memory wijziging van Task 6 van 27 naar 26 wordt als afwijking gedetecteerd.

**MAJOR (codex, geaccepteerd en nagemeten):** de netwerkclient behandelde iedere HTTP 404 als "leeg" in plaats van fail-closed. `_get()` gaf bij een 404 `None` terug, en `collaborators()`, `collaborator_permission()`, `teams()`, `team_members()` en `branch_protections()` zetten dat om naar `[]` respectievelijk `{}`. Zelf nagemeten op de regels 1695 en 1723–1736 van de beoordeelde revisie. Alleen bij het aftasten van de twee workflowmappen is een 404 een geldige uitkomst; bij de overige endpoints betekent het dat de meting onvolledig is, en §7.7 eist daar fail-closed. Een 404 op collaborators of teams zou "geen schrijvers" hebben opgeleverd en de gate groen kunnen maken terwijl de identiteitenset niet is gemeten.

Verwerkt: `_get()` heeft een expliciete `missing_ok`-parameter die standaard `False` is en bij een 404 `Unreadable` opwerpt; alleen `contents()` geeft `missing_ok=True` mee. De vijf andere methoden geven de respons ongewijzigd door zonder `or []`-fallback, en `trust_scope` verheft een `None` van collaborators, teams, teamleden of branch-protection expliciet tot `Unreadable`. Vier tests erbij: drie die per endpoint bewijzen dat een ontbrekende respons in `verdict.unreadable` eindigt en het oordeel rood maakt, en één die de client zelf toetst met een gesimuleerde 404 — `missing_ok=True` geeft `None`, de standaard werpt `Unreadable`. Task 6 gaat van 27 naar 31 tests.

### Plan-review ronde 2 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`
**Requests:** `32010477-c0b0-4eab-a34e-0ba8cfded29a`, `476f9370-6d91-4f52-8aae-3032cd060ab6`
**Replies:** `3ca7cd8c-bb14-4da7-bb42-ec9d347f03c6`, `c3223bfd-a56e-4097-b8ef-a9738cb6539b`
**Beoordeelde revisie:** 5263 regels, commit `b959789`, SHA-256 `df57ee46ec2c9aeb5f961540715bf06a1974dde139f3d358f24390fd7cb253dd`
**Verdicts:** Codex NO-GO; Claude NO-GO
**Tellingen:** Codex 1 BLOCKER / 0 MAJOR / 1 MINOR; Claude 0 BLOCKER / 1 MAJOR / 1 MINOR

Beide reviewers oordeelden dat de zes fixes uit ronde 1 standhouden; codex noemde fix 1 "partially held". Beiden verifieerden de nieuwe feitelijke beweringen zelf: `docker ps -a` geeft 19 op `max2` en `shasum` bestaat op beide hosts.

**Convergent (beide reviewers, geaccepteerd):** drie `Expected: PASS — N tests`-regels waren achtergelopen op de tests eronder. Task 4 stond op 3 met vijf tests, Task 11 op 13 met veertien, Task 13 op 16 met achttien. Task 4 was een regressie uit ronde 1: de fixes voegden twee tests toe zonder de verwachting bij te werken. Zelf nageteld over alle 22 taken: achttien klopten, drie niet. Verwerkt: de drie getallen zijn gecorrigeerd, en Task 22 step 2 heeft een mechanische controle gekregen die iedere `Expected: PASS — N tests`-regel aftelt tegen de tests in diezelfde taak. Die controle draait groen op de huidige revisie. Claude's structurele voorstel is daarmee overgenomen: de teller kan niet meer stil achterlopen op een reviewfix.

**MINOR (claude, geaccepteerd):** de verwachting bij `caps.env` noemde elf regels terwijl het genererende blok er dertien produceert — drie commentaarregels en tien toewijzingen. Nageteld en gecorrigeerd.

**BLOCKER (codex): deels verworpen, met verwerking van de valide kern.**

Codex stelde dat `_schrijvers()` de verkeerde vorm interpreteert: het endpoint `/repos/{owner}/{repo}/collaborators/{collaborator}/permission` zou het `Permission`-schema met de booleans `admin`, `pull` en `push` teruggeven, waardoor schrijvers gemist worden.

*Bronbewijs tegen die stelling.* De OpenAPI-spec van de draaiende instance koppelt dat endpoint aan de response `RepoCollaboratorPermission`, en die response verwijst naar de gelijknamige definitie met exact drie properties: `permission` (string), `role_name` (string) en `user`. Het `Permission`-schema met booleans bestaat wél in de spec, maar hangt aan `Repository.permissions` en niet aan dit endpoint. Codex heeft twee losse feiten uit de spec aan elkaar geplakt. De bestaande stringvergelijking was dus juist en de voorgestelde fix — `rechten = perm.get("permissions") or perm or …` gevolgd door `rechten["admin"]` — zou op de echte respons niets opleveren.

*De valide kern is wel verwerkt,* want de onderliggende zorg — een schrijver kan onzichtbaar blijven — klopte, alleen langs een ander mechanisme:

- De rollenlijst was onvolledig. `permission` kan ook `owner` teruggeven; die rol ontbrak. Nu vastgelegd als `ROLLEN_MET_SCHRIJFRECHT = ("owner", "admin", "write")`, ook gebruikt voor teampermissies.
- **De repository-eigenaar zat helemaal niet in `writers`.** Forgejo neemt de eigenaar niet op in `/collaborators`, dus de meest bevoorrechte identiteit van elke repository was onzichtbaar voor de allowlist. Dat is het echte gat van de klasse die codex beschreef. `_schrijvers()` krijgt nu `owner_login` mee en neemt die altijd op.
- De dode fallback `collab.get("permissions")` is verwijderd: `User` heeft geen `permissions`-veld, dus die tak kon nooit iets opleveren en suggereerde dekking die er niet was.
- Drie tests erbij die dit vastpinnen: de echte `RepoCollaboratorPermission`-vorm met `permission`, `role_name` en `user`; de rol `owner`; en de eigenaar als schrijver zonder enige collaborator. Task 6 gaat van 24 naar 27 tests.

Ronde 3 moet dit bronbewijs adjudiceren: klopt de vaststelling dat het endpoint `RepoCollaboratorPermission` levert en niet `Permission`?

### Plan-review ronde 1 — 31 augustus 2026

**Reviewers:** `mac:codex` en `scrum4me-server:claude`
**Requests:** `2bc76156-3a6e-4b1e-86a9-7acb9012584a`, `7288f68f-0050-43a0-aec8-6db689be7e47`
**Replies:** `f47c4e29-a69a-4d7b-86a5-f32350283d52`, `5ece6245-bd69-4afe-ac00-cf26c56f5fb0`
**Beoordeelde revisie:** 4829 regels, commit `c386825`, SHA-256 `1a313a4b2e470f39d7ce2dca1acfa7049791f70c7204118a25a1148e659e7647`
**Verdicts:** Codex NO-GO; Claude NO-GO
**Tellingen:** Codex 1 BLOCKER / 2 MAJOR / 0 MINOR; Claude 0 BLOCKER / 1 MAJOR / 2 MINOR

Beide reviewers bevestigden de feitentabel en de API-beweringen tegen de draaiende instance. Alle zes bevindingen zijn tegen de boom nagemeten en volledig geaccepteerd; geen enkele is afgewezen.

- **BLOCKER (codex): de trustgate mat niet wat §7.7 eist.** `RISKY_TRIGGERS` was gedeclareerd maar werd nergens gevuld, `branch_protections()` bestond op de client maar werd nooit aangeroepen, en teams werden helemaal niet opgehaald. Nagemeten: `grep risky_triggers` liet alleen lege lijsten in tests en één leesplek in `classify` zien; `grep branch_protections` alleen twee clientdefinities; `def teams` bestond niet. Verwerkt: `inventory()` haalt nu workflowbestanden op, decodeert ze fail-closed, vult `risky_triggers` en `gebruikt_gedeeld_label` via `scan_workflow`, verzamelt schrijvers uit collaborators én teams via `collaborator_permission` en `team_members`, en leest branch-protection op de default branch. `classify()` maakt een risicotrigger mét gedeeld label hard en zonder gedeeld label zacht, en meldt ontbrekende branch-protection als zacht. De testsuite groeide van 9 naar 24 tests.
- **MAJOR (codex): `caps.env` werd geconsumeerd maar nooit geproduceerd.** Task 9 schreef alleen `caps.md`. Verwerkt: Task 9 heeft een nieuwe step die `caps.env` genereert met exact de namen die `preflight.sh` sourcet plus de Compose-namen, met een controle dat het bestand sourcebaar is; Task 10 kopieert het expliciet naar beide hosts en Task 16 vult `.env` er mechanisch uit.
- **MAJOR (codex): de nep-`curl` van Task 4 maakte de groene toestand onbereikbaar.** De mock gaf ook ná de DELETE een record terug, waardoor het script terecht met exit 5 stopte en de test nooit kon slagen. Verwerkt: de fake is stateful geworden en geeft na de DELETE non-zero; er zijn twee tests bij die bewijzen dat een blijvend record wél tot exit 5 leidt en dat labels tot exit 6 leiden.
- **MAJOR (claude): veiligheidskader 1 van de ephemeral-spike beschreef een mechanisme dat niet bestaat.** `RegisterRunnerOptions` kent alleen `description`, `ephemeral` en `name` — geen `labels`. De POST zette dus de naam, niet een label, en de mock verzon het label zodat de test het niet kon betrappen. Verwerkt: kader 1 beschrijft nu de werkelijke garantie (geen labels, dus geen `runs-on`-match), het script doet een harde assertie op het teruggelezen record en stopt met exit 6 als er toch labels blijken te zijn, en de mock geeft een lege labellijst.
- **MINOR (claude): het containeraantal voor `max2` klopte niet** — 20 in het plan tegenover 19 gemeten. Verwerkt: gecorrigeerd naar 19 met de uitsplitsing 11 draaiend en 8 gestopt, en de kolomkop noemt nu het commando.
- **MINOR (claude): `bundle-hash.sh` leverde de mac-variant in code en de draagbaarheidsfix alleen in proza.** De reviewer mat bovendien dat `shasum` op beide hosts bestaat, zodat de toelichting ook feitelijk misleidend was. Verwerkt: de `HASHER`-detectie staat nu in het codeblok zelf, met de meting als onderbouwing.

Daarnaast is één volgordelus gesloten die door de BLOCKER-fix ontstond: de trustgate heeft labelnamen nodig, en die komen nu uit `shared-label-names.txt` dat Task 2 uit de live `.runner` haalt, niet uit `labels.txt` van stap B.
