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
    echo '[{"Name":"/scrum4me-forgejo-runner","State":{"Health":{"Status":"healthy"}},"Config":{"Env":["RUNNER_REGISTRATION_TOKEN=SECRETTESTTOKEN1234567890","DOCKER_HOST=tcp://dind:2376"],"Cmd":["/bin/sh","-c","forgejo-runner register --instance https://x --token SECRETTESTTOKEN1234567890"]},"Args":["-c","forgejo-runner register --token SECRETTESTTOKEN1234567890"],"Mounts":[{"Type":"volume","Name":"anon123","Source":"/var/lib/docker/volumes/anon123/_data","Destination":"/data"}]}]' ;;  # secret-scan: fixture
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

@test "redigeert secrets uit de container-inspect" {
  out="$BATS_TEST_TMPDIR/evidence"
  bash "$SCRIPT" --runner scrum4me-forgejo-runner --dind scrum4me-forgejo-dind --out "$out"
  # de token uit env EN de inline --token in het commando moeten weg zijn
  grep -q '<GEREDIGEERD>' "$out/containers.json"
  ! grep -q 'SECRETTESTTOKEN1234567890' "$out/containers.json"
}
