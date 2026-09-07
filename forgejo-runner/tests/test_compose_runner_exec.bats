#!/usr/bin/env bats
# forgejo-runner/tests/test_compose_runner_exec.bats
# Het runnercommando moet in de ÉCHTE gepinde image starten. De statische
# compose-contracttest grept alleen de gerenderde YAML en zag daarom niet dat
# `command: ["one-job", "--wait"]` op een image zonder entrypoint exit 127 geeft
# ("exec: one-job: executable file not found in $PATH") — stap D zou daarop
# bij de eerste bring-up op max2 zijn stukgelopen. Deze test voert het door
# compose gerenderde command uit tegen de image uit .env.example.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  BUNDLE="$REPO_ROOT/forgejo-runner"
  docker info >/dev/null 2>&1 || skip "geen bereikbare docker-daemon; deze test heeft de echte runnerimage nodig"
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

@test "het gerenderde runnercommando start in de gepinde image (geen exec-fout in \$PATH)" {
  mapfile -t regels < <(render_runner)
  image="${regels[0]}"
  command=("${regels[@]:1}")
  [ -n "$image" ]
  [ "${#command[@]}" -gt 0 ]

  docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null

  # Precies zoals compose het doet: geen entrypoint-override, command als argv.
  # --network none: er is geen config gemount, de runner mag nergens bij kunnen.
  run docker run --rm --network none "$image" "${command[@]}"

  echo "exit=$status"
  echo "$output"
  [ "$status" -ne 127 ]
  [[ "$output" != *"executable file not found"* ]]
  # Het proces bereikte forgejo-runner zelf: zonder gemounte config klaagt
  # one-job over het ontbreken van een connection, niet over het binary.
  [[ "$output" == *"one-job"* ]]
}
