#!/usr/bin/env bats
# forgejo-runner/tests/test_bundle_hash.bats
# De canonieke bundelhash uit §6.1: stabiel, gevoelig voor inhoud én pad, en
# blind voor alles wat hostlokaal is (anders is "byte-identiek op beide hosts"
# per definitie onhaalbaar).

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

@test "negeert de hostlokale bestanden die op een uitgerolde host naast de bundel staan" {
  # §6.1: de hash moet op beide hosts gelijk zijn. runner-config.yml draagt de
  # per-host UUID, BUNDLE_COMMIT is het uitrolrecord, controller.toml en
  # credentials/ zijn hostconfig, __pycache__ ontstaat zodra Python draait.
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  echo "uuid: 11111111-2222-3333-4444-555555555555" > "$BUNDLE/runner-config.yml"
  echo "deadbeef" > "$BUNDLE/BUNDLE_COMMIT"
  echo "x = 1" > "$BUNDLE/controller.toml"
  mkdir -p "$BUNDLE/credentials" "$BUNDLE/scripts/__pycache__"
  echo "geheim" > "$BUNDLE/credentials/forgejo-token"
  echo "bytecode" > "$BUNDLE/scripts/__pycache__/forgejo_runner_cycle.cpython-312.pyc"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" = "$h2" ]
}

@test "hasht als niet-root ondanks een onleesbare credentials/-map (prune, geen pipefail)" {
  # Regressie (max2 stap-D bring-up): bundle-hash gebruikte `! -path` i.p.v.
  # `-prune`, dus find daalde af in de 0700 credentials/-map en gaf als niet-root
  # "Permission denied" -> onder set -o pipefail faalde de HELE hash, en daarmee
  # verify-stack.sh op een uitgerolde host. -prune lost dit op.
  [ "$(id -u)" -ne 0 ] || skip "root leest een 000-map sowieso; deze regressie is non-root"
  mkdir -p "$BUNDLE/credentials"
  echo "geheim" > "$BUNDLE/credentials/forgejo-token"
  chmod 000 "$BUNDLE/credentials"
  run bash "$SCRIPT" "$BUNDLE"
  chmod 755 "$BUNDLE/credentials"   # herstel zodat BATS de tmpdir kan opruimen
  [ "$status" -eq 0 ]
  [ "${#output}" -eq 64 ]
  [[ "$output" != *"Permission denied"* ]]
}

@test "negeert tests/ maar telt .env.example en de unit wel mee" {
  mkdir -p "$BUNDLE/tests"
  h1="$(bash "$SCRIPT" "$BUNDLE")"
  echo "@test" > "$BUNDLE/tests/t.bats"
  h2="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h1" = "$h2" ]
  echo "RUNNER_IMAGE=x@sha256:abc" > "$BUNDLE/.env.example"
  h3="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h2" != "$h3" ]
  echo "[Unit]" > "$BUNDLE/forgejo-runner-cycle.service"
  h4="$(bash "$SCRIPT" "$BUNDLE")"
  [ "$h3" != "$h4" ]
}

@test "de echte bundel in de repo hasht en de hash is reproduceerbaar" {
  h1="$(bash "$SCRIPT" "$REPO_ROOT/forgejo-runner")"
  h2="$(bash "$SCRIPT" "$REPO_ROOT/forgejo-runner")"
  [ "$h1" = "$h2" ]
  [ "${#h1}" -eq 64 ]
}

@test "een ontbrekende map is een gebruiksfout" {
  run bash "$SCRIPT" "$BATS_TEST_TMPDIR/bestaat-niet"
  [ "$status" -eq 2 ]
}
