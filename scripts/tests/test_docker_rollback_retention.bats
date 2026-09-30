#!/usr/bin/env bats
# scripts/tests/test_docker_rollback_retention.bats
# docker-rollback-retention.sh met een nep-`docker`: geen echte daemon nodig.
# Statebestanden sturen het gedrag; iedere rmi-aanroep wordt gelogd.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/scripts/docker-rollback-retention/docker-rollback-retention.sh"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  STATE="$BATS_TEST_TMPDIR/state"
  mkdir -p "$FAKE_BIN" "$STATE"
  # repo TAB tag TAB id TAB created. norollback-x is het nieuwst: matcht het
  # ten onrechte, dan schuift rollback-3 uit de keep-2.
  {
    printf 'app\trollback-1\tsha256:a1\t2026-09-01 12:00:00 +0200 CEST\n'
    printf 'app\trollback-2\tsha256:a2\t2026-09-02 12:00:00 +0200 CEST\n'
    printf 'app\trollback-3\tsha256:a3\t2026-09-03 12:00:00 +0200 CEST\n'
    printf 'app\trollback-4\tsha256:a4\t2026-09-04 12:00:00 +0200 CEST\n'
    printf 'app\tlatest\tsha256:a0\t2026-09-05 12:00:00 +0200 CEST\n'
    printf 'app\tnorollback-x\tsha256:a9\t2026-09-06 12:00:00 +0200 CEST\n'
    printf 'web\trollback-1\tsha256:w1\t2026-09-01 08:00:00 +0200 CEST\n'
    printf 'web\trollback-2\tsha256:w2\t2026-09-02 08:00:00 +0200 CEST\n'
    printf 'web\tidea-rollback-3\tsha256:w3\t2026-09-03 08:00:00 +0200 CEST\n'
    printf 'web\trollback-4\tsha256:w4\t2026-09-04 08:00:00 +0200 CEST\n'
  } > "$STATE/images"
  # a2 wordt gebruikt door een gestopte container.
  echo c1 > "$STATE/ps"
  echo sha256:a2 > "$STATE/inspect_images"
  for i in a0 a1 a2 a3 a4 a9 w1 w2 w3 w4; do echo "sha256:$i 2400000000"; done > "$STATE/sizes"
  : > "$STATE/rmi_calls"; : > "$STATE/refuse"; : > "$STATE/fail_sub"

  cat > "$FAKE_BIN/docker" <<EOS
#!/usr/bin/env bash
STATE="$STATE"
sub="\$1"
[ "\$sub" = image ] && sub="image \$2"
if grep -qxF "\$sub" "\$STATE/fail_sub"; then echo "fake: \$sub failed" >&2; exit 1; fi
case "\$sub" in
  ps) cat "\$STATE/ps" ;;
  inspect) cat "\$STATE/inspect_images" ;;
  images) cat "\$STATE/images" ;;
  "image inspect")
    id="\${@: -1}"
    line=\$(grep -F "\$id " "\$STATE/sizes") || { echo "Error: no such image" >&2; exit 1; }
    echo "\${line#* }" ;;
  rmi)
    echo "\$2" >> "\$STATE/rmi_calls"
    if grep -qxF "\$2" "\$STATE/refuse"; then exit 1; fi ;;
  *) echo "fake docker: unexpected \$*" >&2; exit 99 ;;
esac
EOS
  chmod +x "$FAKE_BIN/docker"
  PATH="$FAKE_BIN:$PATH"
}

run_script() { run bash "$SCRIPT" "$@"; }

@test "default is dry-run: nothing removed, would_remove reported" {
  run_script
  [ "$status" -eq 0 ]
  [ ! -s "$STATE/rmi_calls" ]
  [[ "$output" == *"mode=dry-run keep=2 kept=4 in_use=1 would_remove=3 refused=0"* ]]
}

@test "--apply --keep 2 untags exactly the old unused rollback tags" {
  run_script --apply --keep 2
  [ "$status" -eq 0 ]
  sort "$STATE/rmi_calls" > "$BATS_TEST_TMPDIR/got"
  printf 'app:rollback-1\nweb:idea-rollback-3\nweb:rollback-1\n' > "$BATS_TEST_TMPDIR/want"
  run diff "$BATS_TEST_TMPDIR/got" "$BATS_TEST_TMPDIR/want"
  [ "$status" -eq 0 ]
}

@test "--apply summary counts" {
  run_script --apply --keep 2
  [[ "$output" == *"mode=apply keep=2 kept=4 in_use=1 removed=3 refused=0"* ]]
}

@test "in-use tag is skipped and reported as in-use" {
  run_script --apply --keep 2
  ! grep -qx 'app:rollback-2' "$STATE/rmi_calls"
  [[ "$output" == *"in-use"*"app"*"rollback-2"* ]]
}

@test "refused rmi counts as refused, run continues" {
  echo 'app:rollback-1' > "$STATE/refuse"
  run_script --apply --keep 2
  [ "$status" -eq 0 ]
  [[ "$output" == *"refused=1"* ]]
  [[ "$output" == *"removed=2"* ]]
  grep -qx 'web:rollback-1' "$STATE/rmi_calls"
}

@test "--keep abc exits 2" {
  run_script --keep abc
  [ "$status" -eq 2 ]
  [[ "$output" == *"--keep needs a number"* ]]
}

@test "unknown argument exits 2" {
  run_script --bogus
  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown argument"* ]]
}

# --- audit defects (AUDIT-016/018) ---

@test "norollback-x and latest are ignored" {
  run_script --apply --keep 2
  ! grep -q 'norollback' "$STATE/rmi_calls"
  [[ "$output" != *"norollback-x"* ]]
  [[ "$output" != *"latest"* ]]
}

@test "failed docker inspect: exit non-zero and nothing removed" {
  echo inspect > "$STATE/fail_sub"
  run_script --apply --keep 2
  [ "$status" -ne 0 ]
  [ ! -s "$STATE/rmi_calls" ]
}

@test "failed docker ps: exit non-zero and nothing removed" {
  echo ps > "$STATE/fail_sub"
  run_script --apply --keep 2
  [ "$status" -ne 0 ]
  [ ! -s "$STATE/rmi_calls" ]
}

@test "failed docker images: exit non-zero, no normal summary" {
  echo images > "$STATE/fail_sub"
  run_script --apply --keep 2
  [ "$status" -ne 0 ]
  [ ! -s "$STATE/rmi_calls" ]
  [[ "$output" != *"mode=apply"* ]]
}

@test "image vanished during size lookup: run continues" {
  grep -v 'sha256:a1 ' "$STATE/sizes" > "$STATE/sizes.new"
  mv "$STATE/sizes.new" "$STATE/sizes"
  run_script --apply --keep 2
  [ "$status" -eq 0 ]
  grep -qx 'app:rollback-1' "$STATE/rmi_calls"
  grep -qx 'web:rollback-1' "$STATE/rmi_calls"
  [[ "$output" == *"removed=3"* ]]
}

@test "no rollback tags at all: clean exit with zero counts" {
  grep -v rollback "$STATE/images" > "$STATE/images.new"
  mv "$STATE/images.new" "$STATE/images"
  run_script --apply
  [ "$status" -eq 0 ]
  [[ "$output" == *"kept=0 in_use=0 removed=0 refused=0"* ]]
}
