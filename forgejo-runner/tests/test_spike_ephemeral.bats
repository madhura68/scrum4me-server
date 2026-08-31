# forgejo-runner/tests/test_spike_ephemeral.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/spike-ephemeral.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  # De nep-curl is bewust stateful: na de DELETE moet een GET op hetzelfde
  # record falen, anders is het opruimbewijs niet te halen en kan de suite
  # per constructie nooit groen worden.
  export FAKE_STATE="$BATS_TEST_TMPDIR/verwijderd"
  cat > "$FAKE_BIN/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*)
    touch "$FAKE_STATE" ; echo '' ; exit 0 ;;
  *runners/999*)
    # Na de DELETE bestaat het record niet meer; curl --fail-with-body geeft dan non-zero.
    [ -e "$FAKE_STATE" ] && exit 22
    echo '{"id":999,"uuid":"u-999","name":"ephemeral-spike-test","ephemeral":true,"labels":[],"status":"offline"}'
    exit 0 ;;
  *runners*)
    echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
echo '{}'
EOS
  chmod +x "$FAKE_BIN/curl"
  PATH="$FAKE_BIN:$PATH"
  export FORGEJO_TOKEN="niet-echt"
}

@test "weigert een label zonder spike-prefix" {
  run bash "$SCRIPT" --label ubuntu-latest --out "$BATS_TEST_TMPDIR/ev"
  [ "$status" -ne 0 ]
  [[ "$output" == *"ephemeral-spike-"* ]]
}

@test "lekt het teruggegeven token niet naar het bewijsbestand" {
  out="$BATS_TEST_TMPDIR/ev"
  bash "$SCRIPT" --label ephemeral-spike-test --out "$out"
  run grep -r "GEHEIM" "$out"
  [ "$status" -ne 0 ]
}

@test "verwijdert het record en legt dat vast" {
  out="$BATS_TEST_TMPDIR/ev"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$out"
  [ "$status" -eq 0 ]
  grep -q "verwijderd" "$out/ephemeral-spike.md"
}

@test "faalt als het record na de DELETE blijft bestaan" {
  # Zonder state blijft de GET slagen; het script hoort dan met 5 te stoppen.
  cat > "$BATS_TEST_TMPDIR/bin/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*) echo '' ; exit 0 ;;
  *runners/999*) echo '{"id":999,"uuid":"u-999","labels":[]}' ; exit 0 ;;
  *runners*)     echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
EOS
  chmod +x "$BATS_TEST_TMPDIR/bin/curl"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$BATS_TEST_TMPDIR/ev2"
  [ "$status" -eq 5 ]
}

@test "faalt als het record toch labels blijkt te dragen" {
  cat > "$BATS_TEST_TMPDIR/bin/curl" <<'EOS'
#!/usr/bin/env bash
case "$*" in
  *"--request DELETE"*) touch "$FAKE_STATE" ; echo '' ; exit 0 ;;
  *runners/999*)
    [ -e "$FAKE_STATE" ] && exit 22
    echo '{"id":999,"uuid":"u-999","labels":["ubuntu-latest"]}' ; exit 0 ;;
  *runners*) echo '{"id":999,"uuid":"u-999","token":"GEHEIM"}' ; exit 0 ;;
esac
EOS
  chmod +x "$BATS_TEST_TMPDIR/bin/curl"
  run bash "$SCRIPT" --label ephemeral-spike-test --out "$BATS_TEST_TMPDIR/ev3"
  [ "$status" -eq 6 ]
}
