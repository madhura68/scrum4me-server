#!/usr/bin/env bats
# forgejo-runner/tests/test_preflight.bats
# De vier harde drempels uit §7.8. Iedere drempel heeft een eigen faaltest;
# de geheugendrempel staat er expliciet bij omdat die op scrum4me-server de
# NO-GO gaf en dus aantoonbaar moet blijven falen wanneer hij hoort te falen.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/preflight.sh"
  FACTS="$BATS_TEST_TMPDIR/facts.tsv"
  CAPS="$BATS_TEST_TMPDIR/caps.env"
  IMAGES="$BATS_TEST_TMPDIR/images.txt"
  cat > "$CAPS" <<'EOS'
RUNNER_CPU=1.0
RUNNER_MEM_BYTES=1073741824
DIND_CPU=2.0
DIND_MEM_BYTES=4294967296
EOS
  echo "catthehacker/ubuntu@sha256:abc 2147483648" > "$IMAGES"
}

ruime_host() {
  printf 'vcpu\t28\n'                          > "$FACTS"
  printf 'mem_total_bytes\t32000000000\n'     >> "$FACTS"
  printf 'mem_available_bytes\t21474836480\n' >> "$FACTS"
  printf 'docker_root_dir\t/var/lib/docker\n' >> "$FACTS"
  printf 'docker_root_free_bytes\t500000000000\n' >> "$FACTS"
  printf 'docker_root_free_pct\t60\n'         >> "$FACTS"
  printf 'docker_root_free_inodes_pct\t80\n'  >> "$FACTS"
}

@test "ruime host haalt alle vier drempels" {
  ruime_host
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 0 ]
  [[ "$output" == *"vcpu: OK"* ]]
  [[ "$output" == *"geheugen: OK"* ]]
  [[ "$output" == *"schijf: OK"* ]]
  [[ "$output" == *"inodes: OK"* ]]
}

@test "te weinig vrije schijfruimte faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_pct.*/docker_root_free_pct	9/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"schijf: FAIL"* ]]
}

@test "te weinig vrije bytes voor images plus werkruimte faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_bytes.*/docker_root_free_bytes	3000000000/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"schijf: FAIL"* ]]
}

@test "te weinig vrije inodes faalt" {
  ruime_host
  sed -i.bak 's/^docker_root_free_inodes_pct.*/docker_root_free_inodes_pct	5/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"inodes: FAIL"* ]]
}

@test "te krappe cpu-headroom faalt" {
  ruime_host
  sed -i.bak 's/^vcpu.*/vcpu	4/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"vcpu: FAIL"* ]]
}

@test "te krappe geheugen-headroom faalt" {
  ruime_host
  sed -i.bak 's/^mem_available_bytes.*/mem_available_bytes	8000000000/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"geheugen: FAIL"* ]]
}

@test "meerdere falende drempels leveren nog steeds exit 40 en melden er meer dan een" {
  ruime_host
  sed -i.bak 's/^vcpu.*/vcpu	4/' "$FACTS"
  sed -i.bak 's/^mem_available_bytes.*/mem_available_bytes	8000000000/' "$FACTS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 40 ]
  [[ "$output" == *"vcpu: FAIL"* ]]
  [[ "$output" == *"geheugen: FAIL"* ]]
}

@test "een ontbrekend factsbestand is een gebruiksfout, geen stille GO" {
  run bash "$SCRIPT" --facts "$BATS_TEST_TMPDIR/bestaat-niet.tsv" --caps "$CAPS"
  [ "$status" -eq 2 ]
}

@test "images zijn optioneel; dan telt alleen de werkruimte" {
  ruime_host
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"schijf: OK"* ]]
}
