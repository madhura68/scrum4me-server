#!/usr/bin/env bats
# forgejo-runner/tests/test_compose_runner_exec.bats
# Het runnercommando moet in de ÉCHTE gepinde image (a) starten zonder $PATH-fout
# en (b) de gemounte config DAADWERKELIJK laden. Twee bugs ontsnapten aan de
# statische contracttest en werden pas bij de max2-bring-up zichtbaar:
#   1. command ["one-job","--wait"] op een image zonder entrypoint -> exit 127
#      ("exec: one-job: executable file not found in $PATH");
#   2. command zonder -c -> forgejo-runner laadt de config niet
#      ("No configuration file specified") -> "0 connections are configured" ->
#      exit 1 -> de runner komt nooit online; de oude test las die fout als succes.
# Deze test voert het gerenderde command uit tegen de image uit .env.example, mét
# een minimale dummy-config, en eist dat de config geladen wordt.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  BUNDLE="$REPO_ROOT/forgejo-runner"
  docker info >/dev/null 2>&1 || skip "geen bereikbare docker-daemon; deze test heeft de echte runnerimage nodig"
  # timeout(1) begrenst de --wait-poll; macOS heeft het als gtimeout (coreutils) of niet.
  TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
  [ -n "$TIMEOUT_BIN" ] || skip "geen timeout(1)/gtimeout beschikbaar voor de --wait-begrenzing"
}

# Rendert compose met de échte pins uit .env.example en geeft image + command
# van de runnerservice terug als shell-array-regels (eerste regel image, daarna
# ieder command-element op een eigen regel).
render_runner() {
  env COMPOSE_PROFILES=cycle docker compose -f "$BUNDLE/compose.yaml" --env-file "$BUNDLE/.env.example" config --format json \
    | python3 -c '
import json, sys
runner = json.load(sys.stdin)["services"]["runner"]
print(runner["image"])
for deel in runner["command"]:
    print(deel)
'
}

@test "het gerenderde runnercommando start in de gepinde image EN laadt de config" {
  mapfile -t regels < <(render_runner)
  image="${regels[0]}"
  command=("${regels[@]:1}")
  [ -n "$image" ]
  [ "${#command[@]}" -gt 0 ]

  docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null

  # Minimale dummy-config met precies EEN connection, op het containerpad dat het
  # command met -c aanwijst, plus een dummy-token zodat token_url iets vindt. De
  # waarden zijn nep en onbereikbaar: het gaat er alleen om dat forgejo-runner de
  # config LAADT (>=1 connection), niet dat hij een echte Forgejo bereikt.
  cfg="$BATS_TEST_TMPDIR/config.yml"
  cat > "$cfg" <<'YAML'
log:
  level: info
runner:
  capacity: 1
server:
  connections:
    forgejo:
      url: https://invalid.invalid
      uuid: 00000000-0000-0000-0000-000000000000
      token_url: file:/run/forgejo-runner-credentials/forgejo-token
      labels:
        - ubuntu-latest
YAML
  tok="$BATS_TEST_TMPDIR/forgejo-token"
  printf %s dummy > "$tok"

  # Precies zoals compose het doet: geen entrypoint-override, command als argv.
  # --network none: de dummy-URL is toch onbereikbaar; het startpad (config lezen
  # + connections tellen) draait vóór netwerk-IO. timeout vangt --wait af.
  run "$TIMEOUT_BIN" 20 docker run --rm --network none \
    -v "$cfg:/etc/forgejo-runner/config.yml:ro" \
    -v "$tok:/run/forgejo-runner-credentials/forgejo-token:ro" \
    "$image" "${command[@]}"

  echo "exit=$status"
  echo "$output"
  # (a) het binary is bereikt: geen $PATH-fout.
  [ "$status" -ne 127 ]
  [[ "$output" != *"executable file not found"* ]]
  # (b) de config is DAADWERKELIJK geladen: geen default-settings en >=1 connection.
  # Dit is de regressie die de max2-bring-up ving; zonder -c faalt precies dit.
  [[ "$output" != *"No configuration file specified"* ]]
  [[ "$output" != *"0 connections are configured"* ]]
}
