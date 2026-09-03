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
