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
