#!/usr/bin/env bats
# forgejo-runner/tests/test_verify_stack.bats
# De driftgate uit §6.1 en de isolatiegate uit §7.5: iedere faaltak moet
# aantoonbaar kunnen falen (60 commit-drift, 61 bundelhash-drift, 62
# hostlistener), want een gate die niet kan falen is geen gate. Het script
# leest het uitrolrecord en `ss` via overschrijfbare paden zodat dit zonder
# host kan draaien.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/verify-stack.sh"
  HASHER="$REPO_ROOT/forgejo-runner/scripts/bundle-hash.sh"
  BUNDLE="$BATS_TEST_TMPDIR/bundel"
  mkdir -p "$BUNDLE/scripts"
  cp "$HASHER" "$BUNDLE/scripts/bundle-hash.sh"
  cp "$SCRIPT" "$BUNDLE/scripts/verify-stack.sh"
  echo "a" > "$BUNDLE/compose.yaml"
  export BUNDLE_COMMIT_FILE="$BATS_TEST_TMPDIR/BUNDLE_COMMIT"
  echo "abc123" > "$BUNDLE_COMMIT_FILE"
  HASH="$(bash "$HASHER" "$BUNDLE")"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  printf '#!/usr/bin/env bash\ncat "%s/ss.txt"\n' "$BATS_TEST_TMPDIR" > "$FAKE_BIN/ss"
  chmod +x "$FAKE_BIN/ss"
  printf 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n' > "$BATS_TEST_TMPDIR/ss.txt"
  PATH="$FAKE_BIN:$PATH"
}

verify() { bash "$BUNDLE/scripts/verify-stack.sh" "$@"; }

@test "groen bij juiste commit, juiste hash en geen listener" {
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"isolatie: OK"* ]]
  [[ "$output" == *"commit: abc123"* ]]
}

@test "ontbrekend BUNDLE_COMMIT is exit 60" {
  rm -f "$BUNDLE_COMMIT_FILE"
  run verify abc123 "$HASH"
  [ "$status" -eq 60 ]
}

@test "afwijkende commit is exit 60 en noemt beide waarden" {
  echo "def456" > "$BUNDLE_COMMIT_FILE"
  run verify abc123 "$HASH"
  [ "$status" -eq 60 ]
  [[ "$output" == *"def456"* ]]
  [[ "$output" == *"abc123"* ]]
}

@test "afwijkende bundelhash is exit 61" {
  run verify abc123 "afwijkende-hash"
  [ "$status" -eq 61 ]
}

@test "gewijzigde bundelinhoud op de host is exit 61" {
  echo "gemuteerd op de host" >> "$BUNDLE/compose.yaml"
  run verify abc123 "$HASH"
  [ "$status" -eq 61 ]
}

@test "hostlistener op 2375 is exit 62" {
  printf 'LISTEN 0 128 0.0.0.0:2375 0.0.0.0:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
}

@test "hostlistener op 2376 is exit 62 en een poort als 23750 niet" {
  printf 'LISTEN 0 128 [::]:23750 [::]:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  printf 'LISTEN 0 128 [::]:2376 [::]:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
}

@test "commit-drift gaat voor hash-drift: eerst weten welke commit er staat" {
  echo "def456" > "$BUNDLE_COMMIT_FILE"
  run verify abc123 "afwijkende-hash"
  [ "$status" -eq 60 ]
}

@test "ontbrekende argumenten zijn een gebruiksfout" {
  run verify abc123
  [ "$status" -eq 2 ]
}
