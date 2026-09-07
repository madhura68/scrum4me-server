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
  run grep -iE '^[A-Z_]*(TOKEN|PASSWORD|SECRET|UUID)[A-Z_]*=|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' <(inhoud "$ENV_EXAMPLE")
  [ "$status" -ne 0 ]
  # En alleen imagepins en caps mogen erin staan.
  run grep -vE '^(RUNNER_IMAGE|DIND_IMAGE|JOB_IMAGE|RUNNER_CPUS|RUNNER_MEM|RUNNER_PIDS|DIND_CPUS|DIND_MEM|DIND_PIDS)=' <(inhoud "$ENV_EXAMPLE")
  [ "$status" -ne 0 ]
}

@test "runner draagt one-job --wait; dind mount de allowlist read-only" {
  run env COMPOSE_PROFILES=cycle RUNNER_IMAGE=x DIND_IMAGE=y RUNNER_CPUS=1 RUNNER_MEM=1g RUNNER_PIDS=100 \
      DIND_CPUS=1 DIND_MEM=1g DIND_PIDS=100 docker compose -f compose.yaml config
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "one-job"
  echo "$output" | grep -q -- "--wait"                                           # command compleet
  echo "$output" | grep -A3 "target: /etc/forgejo-runner/allowed-job-images.txt" | grep -q "read_only: true"  # juist DEZE mount read-only
}
