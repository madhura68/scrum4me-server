# forgejo-runner/tests/test_capture_host_facts.bats
setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/capture-host-facts.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  cat > "$FAKE_BIN/docker" <<'EOS'
#!/usr/bin/env bash
echo "/var/lib/docker"
EOS
  cat > "$FAKE_BIN/nproc" <<'EOS'
#!/usr/bin/env bash
echo 28
EOS
  chmod +x "$FAKE_BIN"/*
  PATH="$FAKE_BIN:$PATH"
}

@test "schrijft alle zeven sleutels" {
  out="$BATS_TEST_TMPDIR/facts.tsv"
  run bash "$SCRIPT" --out "$out"
  [ "$status" -eq 0 ]
  for k in vcpu mem_total_bytes mem_available_bytes docker_root_dir \
           docker_root_free_bytes docker_root_free_pct docker_root_free_inodes_pct; do
    grep -q "^$k	" "$out" || { echo "ontbreekt: $k"; false; }
  done
}

@test "vcpu komt uit nproc" {
  out="$BATS_TEST_TMPDIR/facts.tsv"
  bash "$SCRIPT" --out "$out"
  grep -q "^vcpu	28$" "$out"
}
