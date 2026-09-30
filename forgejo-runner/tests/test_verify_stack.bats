#!/usr/bin/env bats
# forgejo-runner/tests/test_verify_stack.bats
# De driftgate uit §6.1 en de isolatiegate uit §7.5: iedere faaltak moet
# aantoonbaar kunnen falen (60 commit-drift, 61 bundelhash-drift, 62
# hostlistener, 63 unit-drift, 64 eigendom, 65 DinD-guard), want een gate die niet kan falen
# is geen gate. Het script leest het uitrolrecord, de systemd-map en `ss` via
# overschrijfbare paden en `stat` via een stub, zodat dit zonder host (en op
# macOS) kan draaien.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/verify-stack.sh"
  HASHER="$REPO_ROOT/forgejo-runner/scripts/bundle-hash.sh"
  BUNDLE="$BATS_TEST_TMPDIR/bundel"
  mkdir -p "$BUNDLE/scripts"
  cp "$HASHER" "$BUNDLE/scripts/bundle-hash.sh"
  cp "$SCRIPT" "$BUNDLE/scripts/verify-stack.sh"
  cp "$REPO_ROOT/forgejo-runner/scripts/dind-guard.sh" "$BUNDLE/scripts/dind-guard.sh"
  echo "a" > "$BUNDLE/compose.yaml"
  export SYSTEMD_DIR="$BATS_TEST_TMPDIR/systemd"
  mkdir -p "$SYSTEMD_DIR"
  for u in forgejo-runner-cycle.service forgejo-runner-dind-guard.service forgejo-runner-trust.service forgejo-runner-trust.timer; do
    echo "unit $u" > "$BUNDLE/$u"
    cp "$BUNDLE/$u" "$SYSTEMD_DIR/$u"
  done
  export BUNDLE_COMMIT_FILE="$BATS_TEST_TMPDIR/BUNDLE_COMMIT"
  echo "abc123" > "$BUNDLE_COMMIT_FILE"
  HASH="$(bash "$HASHER" "$BUNDLE")"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  printf '#!/usr/bin/env bash\ncat "%s/ss.txt"\n' "$BATS_TEST_TMPDIR" > "$FAKE_BIN/ss"
  chmod +x "$FAKE_BIN/ss"
  printf 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n' > "$BATS_TEST_TMPDIR/ss.txt"
  # stat-stub: standaard root (uid 0) en modus 755; een bestand
  # $BATS_TEST_TMPDIR/stat/<basename> overschrijft de uitvoer ("uid modus").
  mkdir -p "$BATS_TEST_TMPDIR/stat"
  cat > "$FAKE_BIN/stat" <<EOF
#!/usr/bin/env bash
f="$BATS_TEST_TMPDIR/stat/\$(basename "\${3}")"
if [ -f "\$f" ]; then cat "\$f"; else echo "0 755"; fi
EOF
  chmod +x "$FAKE_BIN/stat"
  # DinD-guard (T-188): fake iptables (regels in een bestand), docker (container
  # met IP 172.30.0.2) en timeout (exit 0 = de verbinding lukte, 1 = geweigerd).
  export REGELS="$BATS_TEST_TMPDIR/regels"
  for p in 2375 2376; do
    echo "OUTPUT -o fr-dind0 -p tcp --dport $p -j REJECT --reject-with tcp-reset" >> "$REGELS"
  done
  cat > "$FAKE_BIN/iptables" <<'FAKE'
#!/usr/bin/env bash
[ "$1" = "-w" ] && shift
[ "$1" = "-C" ] || exit 9
shift
grep -qxF -- "$*" "$REGELS"
FAKE
  export IPTABLES="$FAKE_BIN/iptables"
  cat > "$FAKE_BIN/docker" <<FAKE
#!/usr/bin/env bash
case "\$1" in
  ps) cat "$BATS_TEST_TMPDIR/dind-id" ;;
  inspect) echo "172.30.0.2 " ;;
esac
FAKE
  echo "abc" > "$BATS_TEST_TMPDIR/dind-id"
  cat > "$FAKE_BIN/timeout" <<FAKE
#!/usr/bin/env bash
[ -f "$BATS_TEST_TMPDIR/probe-connect" ]
FAKE
  chmod +x "$FAKE_BIN/iptables" "$FAKE_BIN/docker" "$FAKE_BIN/timeout"
  PATH="$FAKE_BIN:$PATH"
}

verify() { bash "$BUNDLE/scripts/verify-stack.sh" "$@"; }

@test "groen bij juiste commit, juiste hash en geen listener" {
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"isolatie: OK"* ]]
  [[ "$output" == *"guard: OK"* ]]
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

@test "ontbrekende ss is exit 62 (isolatie niet te controleren)" {
  rm "$FAKE_BIN/ss"
  SCHOON="$BATS_TEST_TMPDIR/schoon"
  mkdir -p "$SCHOON"
  for t in bash cat cmp find sort awk grep dirname sha256sum shasum env; do
    p="$(command -v "$t" 2>/dev/null || true)"
    if [ -n "$p" ]; then ln -s "$p" "$SCHOON/$t"; fi
  done
  ln -s "$FAKE_BIN/stat" "$SCHOON/stat"
  PATH="$SCHOON" run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
  [[ "$output" == *"ss ontbreekt"* ]]
}

@test "ontbrekende geinstalleerde unit is exit 63" {
  rm "$SYSTEMD_DIR/forgejo-runner-trust.timer"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
  [[ "$output" == *"forgejo-runner-trust.timer"* ]]
}

@test "afwijkende geinstalleerde unit is exit 63" {
  echo "handmatig aangepast" >> "$SYSTEMD_DIR/forgejo-runner-cycle.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
  [[ "$output" == *"forgejo-runner-cycle.service"* ]]
}

@test "bundelbestand van een andere eigenaar is exit 64" {
  echo "1000 644" > "$BATS_TEST_TMPDIR/stat/compose.yaml"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"compose.yaml"* ]]
}

@test "groepsschrijfbaar bundelbestand is exit 64" {
  echo "0 664" > "$BATS_TEST_TMPDIR/stat/forgejo-runner-cycle.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
}

@test "wereldschrijfbaar script is exit 64" {
  echo "0 757" > "$BATS_TEST_TMPDIR/stat/bundle-hash.sh"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
}

@test "bundelmap van een andere eigenaar is exit 64" {
  echo "1000 755" > "$BATS_TEST_TMPDIR/stat/bundel"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"bundelmap"* ]]
}

@test "root-eigendom met modus 644 en 755 is groen" {
  echo "0 644" > "$BATS_TEST_TMPDIR/stat/compose.yaml"
  echo "0 755" > "$BATS_TEST_TMPDIR/stat/bundle-hash.sh"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
}

@test "ontbrekende argumenten zijn een gebruiksfout" {
  run verify abc123
  [ "$status" -eq 2 ]
}

@test "ontbrekende firewallregel is exit 65" {
  : > "$REGELS"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
  [[ "$output" == *"guardfout"* ]]
}

@test "DinD-API bereikbaar vanaf de host is exit 65" {
  touch "$BATS_TEST_TMPDIR/probe-connect"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
  [[ "$output" == *"172.30.0.2:2375"* ]]
}

@test "geen draaiende DinD-container is exit 65 (fail-closed)" {
  : > "$BATS_TEST_TMPDIR/dind-id"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
}

@test "ontbrekende dind-guard-unit op de host is exit 63" {
  rm "$SYSTEMD_DIR/forgejo-runner-dind-guard.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
}
