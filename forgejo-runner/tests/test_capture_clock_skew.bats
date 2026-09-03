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
