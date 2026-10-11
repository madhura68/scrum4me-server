#!/usr/bin/env bats
# forgejo-runner/tests/test_compose_contract.bats
# Het Compose-contract uit §4, §7.5 en §7.6: privileged uitsluitend op DinD,
# geen host-socket, geen poorten, geen host-namespaces, expliciet volume,
# digest-gepinde images en een digest op iedere label- en allowlistregel.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMPOSE="$REPO_ROOT/forgejo-runner/compose.yaml"
  LABELS="$REPO_ROOT/forgejo-runner/labels.txt"
  IMAGES="$REPO_ROOT/forgejo-runner/allowed-job-images.txt"
  ENV_EXAMPLE="$REPO_ROOT/forgejo-runner/.env.example"
  # Compose van vóór R17, bevroren: de referentie voor Gate G1 (byte-gelijke config).
  FIXTURE_OLD="$REPO_ROOT/forgejo-runner/tests/fixtures/compose.pre-n-stacks.yaml"
  # De vier per-stack-waarden van stack 02 (R17 §5). In compose.yaml zijn ze
  # verplicht en hebben ze geen standaardwaarde; stack 02 zet ze in zijn .env.
  STACK02=(STACK_BRIDGE=fr-dind0 STACK_VOLUME=forgejo-runner-dind-data
           STACK_CONFIG=./runner-config.yml
           STACK_TOKEN=/opt/forgejo-runner/credentials/forgejo-token)
}

# Regels zonder commentaar of lege regels; de bestanden dragen uitleg bovenin.
inhoud() { grep -vE '^\s*(#|$)' "$1"; }

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

@test "het dind-volume heeft een expliciete naam uit STACK_VOLUME, zonder standaardwaarde" {
  grep -qE 'name: \$\{STACK_VOLUME:\?' "$COMPOSE"
}

@test "de vier per-stack-variabelen zijn verplicht en hebben geen standaardwaarde (R17 §5)" {
  # Een standaardwaarde zou een vergeten variabele bij een nieuwe stack stil op
  # het volume, de bridge of het token van stack 02 laten uitkomen.
  run grep -cE '\$\{STACK_(BRIDGE|VOLUME|CONFIG|TOKEN):\?' "$COMPOSE"
  [ "$output" = "4" ]
  run grep -E '\$\{STACK_[A-Z]+(:-|-|:=|=)' "$COMPOSE"
  [ "$status" -ne 0 ]
}

@test "met de vier stack-02-waarden is config byte-gelijk aan die van het compose-bestand van vóór R17 (Gate G1)" {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || skip "docker compose ontbreekt"
  D="$BATS_TEST_TMPDIR/proj"
  mkdir -p "$D"
  cp "$FIXTURE_OLD" "$D/compose.old.yaml"
  cp "$COMPOSE" "$D/compose.new.yaml"
  cp "$ENV_EXAMPLE" "$D/.env"
  for profiel in none cycle; do
    args=(-p forgejo-runner --project-directory "$D")
    [ "$profiel" = none ] || args+=(--profile "$profiel")
    oud="$(docker compose "${args[@]}" -f "$D/compose.old.yaml" config)"
    nieuw="$(docker compose "${args[@]}" -f "$D/compose.new.yaml" config)"
    [ -n "$oud" ]
    [ "$oud" = "$nieuw" ] || { diff <(echo "$oud") <(echo "$nieuw") || true; false; }
  done
}

@test "ontbreekt een van de vier per-stack-variabelen, dan faalt config en noemt de variabele" {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || skip "docker compose ontbreekt"
  D="$BATS_TEST_TMPDIR/proj"
  mkdir -p "$D"
  cp "$COMPOSE" "$D/compose.yaml"
  # Ook als de projectmap een volledige .env heeft: met --env-file wordt die niet gelezen.
  cp "$ENV_EXAMPLE" "$D/.env"
  for var in STACK_BRIDGE STACK_VOLUME STACK_CONFIG STACK_TOKEN; do
    grep -v "^$var=" "$ENV_EXAMPLE" > "$D/zonder.env"
    run docker compose --profile cycle -p forgejo-runner-03 -f "$D/compose.yaml" --env-file "$D/zonder.env" config -q
    [ "$status" -ne 0 ]
    [[ "$output" == *"$var"* ]] || { echo "$var niet genoemd: $output"; false; }
  done
}

@test "de env-example draagt de vier waarden van stack 02" {
  grep -qxF 'STACK_BRIDGE=fr-dind0' "$ENV_EXAMPLE"
  grep -qxF 'STACK_VOLUME=forgejo-runner-dind-data' "$ENV_EXAMPLE"
  grep -qxF 'STACK_CONFIG=./runner-config.yml' "$ENV_EXAMPLE"
  grep -qxF 'STACK_TOKEN=/opt/forgejo-runner/credentials/forgejo-token' "$ENV_EXAMPLE"
}

@test "de runner krijgt het juiste docker-endpoint" {
  grep -q 'DOCKER_HOST=tcp://dind:2375' "$COMPOSE"
}

@test "images staan als digest in het compose-bestand, niet als kale tag" {
  run grep -cE 'image: *\$\{(RUNNER|DIND)_IMAGE\}' "$COMPOSE"
  [ "$output" = "2" ]
}

@test "labels.txt is niet leeg en elke regel draagt een digest" {
  [ -n "$(inhoud "$LABELS")" ]
  while read -r regel; do
    [[ "$regel" == *"@sha256:"* ]] || { echo "geen digest: $regel"; false; }
  done < <(inhoud "$LABELS")
}

@test "allowed-job-images.txt bevat alleen digests met een grootte" {
  [ -n "$(inhoud "$IMAGES")" ]
  while read -r digest grootte; do
    [[ "$digest" == *"@sha256:"* ]] || { echo "geen digest: $digest"; false; }
    [[ "$grootte" =~ ^[0-9]+$ ]] || { echo "geen grootte: $grootte"; false; }
  done < <(inhoud "$IMAGES")
}

@test "de runner staat onder het profiel cycle zodat compose up alleen DinD start" {
  # §6: uitsluitend de cyclecontroller maakt een runnerproces aan.
  run python3 -c "
import sys
tekst = open('$COMPOSE').read()
runner = tekst.split('runner:')[1].split('dind:')[0]
sys.exit(0 if 'profiles:' in runner and 'cycle' in runner else 1)
"
  [ "$status" -eq 0 ]
}

@test "de runner mount het tokenbestand read-only op het absolute containerpad" {
  # §6: token_url verwijst naar file:/run/forgejo-runner-credentials/forgejo-token.
  grep -q '/run/forgejo-runner-credentials/forgejo-token:ro' "$COMPOSE"
}

@test "de jobimage in labels.txt staat ook in de allowlist met dezelfde digest" {
  # §7.9 stap 7: alleen digests uit allowed-job-images.txt overleven de scrub.
  # Een label dat naar een image wijst die de scrub verwijdert is een dode label.
  while read -r regel; do
    image="${regel#*docker://}"
    grep -qF "$image" "$IMAGES" || { echo "label-image niet in allowlist: $image"; false; }
  done < <(inhoud "$LABELS")
}

@test "geen enkel bundelbestand bevat een VUL_IN-placeholder" {
  run grep -l 'VUL_IN' "$COMPOSE" "$LABELS" "$IMAGES" "$ENV_EXAMPLE"
  [ "$status" -ne 0 ]
}

@test "de env-example bevat geen tokens, wachtwoorden of UUID's" {
  # Toets de WAARDEN, niet de uitleg: commentaar mag het woord "token" noemen.
  # STACK_TOKEN is het PAD van het tokenbestand (R17 §5), geen token: alleen
  # dat ene pad is toegestaan, iedere andere waarde blijft een bevinding.
  run grep -iE '^[A-Z_]*(TOKEN|PASSWORD|SECRET|UUID)[A-Z_]*=|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <(inhoud "$ENV_EXAMPLE" | grep -vxF 'STACK_TOKEN=/opt/forgejo-runner/credentials/forgejo-token')
  [ "$status" -ne 0 ]
  # En alleen imagepins, caps en de vier per-stack-waarden mogen erin staan.
  run grep -vE '^(RUNNER_IMAGE|DIND_IMAGE|JOB_IMAGE|RUNNER_CPUS|RUNNER_MEM|RUNNER_PIDS|DIND_CPU_QUOTA|DIND_MEM|DIND_PIDS|STACK_BRIDGE|STACK_VOLUME|STACK_CONFIG|STACK_TOKEN)=' <(inhoud "$ENV_EXAMPLE")
  [ "$status" -ne 0 ]
}

@test "runner draagt one-job --wait; dind mount de allowlist read-only" {
  run env "${STACK02[@]}" COMPOSE_PROFILES=cycle RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPU_QUOTA=100000 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "one-job"
  echo "$output" | grep -q -- "--wait"                                           # command compleet
  echo "$output" | grep -A3 "target: /etc/forgejo-runner/allowed-job-images.txt" | grep -q "read_only: true"  # juist DEZE mount read-only
}

@test "runner laadt de config via -c in het command (anders 0 connections, komt niet online)" {
  # De max2-bring-up (8 sep 2026) liep hierop vast: zonder -c laadt forgejo-runner
  # geen config ("No configuration file specified") -> "0 connections are
  # configured" -> exit 1 -> de runner komt nooit online. De oude exec-test las die
  # "0 connections"-fout juist als succes. Dit contract eist -c + het configpad IN
  # het command (niet enkel in de volume-mount).
  run env "${STACK02[@]}" COMPOSE_PROFILES=cycle RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPU_QUOTA=100000 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config --format json
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
cmd = json.load(sys.stdin)["services"]["runner"]["command"]
flag = "-c" if "-c" in cmd else ("--config" if "--config" in cmd else None)
assert flag, f"runner-command mist -c/--config: {cmd}"
assert cmd[cmd.index(flag) + 1] == "/etc/forgejo-runner/config.yml", f"verkeerd configpad na {flag}: {cmd}"
assert "one-job" in cmd and "--wait" in cmd, f"one-job/--wait ontbreekt: {cmd}"
'
}

@test "de dind-cap gebruikt cpu_period/cpu_quota, niet cpus/NanoCpus (create op <cap-core hosts)" {
  # Regressie (stap-G plan-review ronde 1, geverifieerd): `cpus: 11.5` = NanoCpus,
  # en Docker weigert NanoCpus > aantal cores bij container-create (11,5 > 8 op
  # scrum4me-server → "range of CPUs is from 0.01 to 8.00"). cpu_period/cpu_quota
  # wordt niet tegen NumCPU gevalideerd en is dus host-portabel.
  run env "${STACK02[@]}" COMPOSE_PROFILES=cycle RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPU_QUOTA=1150000 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config --format json
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
dind = json.load(sys.stdin)["services"]["dind"]
q = int(dind.get("cpu_quota", 0))
p = int(dind.get("cpu_period", 0))
assert q == 1150000, f"dind cpu_quota verkeerd/afwezig: {q}"
assert p == 100000, f"dind cpu_period verkeerd/afwezig: {p}"
bad = sorted(k for k in dind if "cpu" in k.lower() and k not in ("cpu_quota", "cpu_period"))
assert not bad, f"dind gebruikt nog een NanoCpus-vorm (cpus/nano_cpus): {bad}"
'
}

@test "het runner-control-netwerk heeft de vaste bridgenaam fr-dind0 (dind-guard, T-188)" {
  run env "${STACK02[@]}" COMPOSE_PROFILES=cycle RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPU_QUOTA=100000 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config --format json
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c '
import json, sys
net = json.load(sys.stdin)["networks"]["runner-control"]
naam = net["driver_opts"]["com.docker.network.bridge.name"]
assert naam == "fr-dind0", naam
assert len(naam) <= 15, "Linux-interfacenaam maximaal 15 tekens"
'
}
