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

@test "commentaar- en lege regels in de allowlist tellen niet mee" {
  # De echte allowed-job-images.txt draagt uitleg bovenin. Een commentaarregel
  # met een getal als tweede veld mag de schijfgate niet vervuilen.
  ruime_host
  sed -i.bak 's/^docker_root_free_bytes.*/docker_root_free_bytes	23622320128/' "$FACTS"  # 22 GiB
  printf '# allowlist 999999999999 bytes\n\n%s\n' "catthehacker/ubuntu@sha256:abc 1073741824" > "$IMAGES"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 0 ]
  [[ "$output" == *"schijf: OK"* ]]
  [[ "$output" == *">= 22548578304 nodig"* ]]   # 1 GiB image + 20 GiB werkruimte
}

@test "images zijn optioneel; dan telt alleen de werkruimte" {
  ruime_host
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"schijf: OK"* ]]
}

# ---------------------------------------------------------------------------
# --stacks N (R17 §7.8, M52 T6): de som en de schijfregel worden N x per stack
# ---------------------------------------------------------------------------

# Stap-A-gegevens van max2 (28 vCPU, 21.029.359.616 bytes beschikbaar) met de caps van de
# bundel (runner 1,0 vCPU/1 GiB, DinD 11,5 vCPU/5 GiB).
max2_stap_a() {
  printf 'vcpu\t28\n'                              > "$FACTS"
  printf 'mem_total_bytes\t32000000000\n'         >> "$FACTS"
  printf 'mem_available_bytes\t21029359616\n'     >> "$FACTS"
  printf 'docker_root_dir\t/var/lib/docker\n'     >> "$FACTS"
  printf 'docker_root_free_bytes\t500000000000\n' >> "$FACTS"
  printf 'docker_root_free_pct\t60\n'             >> "$FACTS"
  printf 'docker_root_free_inodes_pct\t80\n'      >> "$FACTS"
  cat > "$CAPS" <<'EOS'
RUNNER_CPU=1.0
RUNNER_MEM_BYTES=1073741824
DIND_CPU=11.5
DIND_MEM_BYTES=5368709120
EOS
}

@test "zonder --stacks is de uitvoer byte-gelijk aan die van vóór R17" {
  max2_stap_a
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  [ "$status" -eq 0 ]
  [ "$output" = "vcpu: OK — som 12.5 binnen 50% van 28
geheugen: OK — som 6442450944 binnen 50% van 21029359616
schijf: OK — 60% vrij en 500000000000 bytes >= 23622320128 nodig
inodes: OK — 80% vrij" ]
}

@test "--stacks 1 geeft dezelfde uitvoer als zonder --stacks" {
  max2_stap_a
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES"
  zonder="$output"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES" --stacks 1
  [ "$status" -eq 0 ]
  [ "$output" = "$zonder" ]
}

@test "max2 met twee stacks is rood op vCPU én geheugen (exit 40, beide redenen genoemd)" {
  max2_stap_a
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES" --stacks 2
  [ "$status" -eq 40 ]
  [[ "$output" == *"vcpu: FAIL"* ]]
  [[ "$output" == *"geheugen: FAIL"* ]]
  [[ "$output" == *"(2 stacks)"* ]]
  [[ "$output" == *"schijf: OK"* ]]
}

@test "max2 met drie stacks is rood" {
  max2_stap_a
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES" --stacks 3
  [ "$status" -eq 40 ]
  [[ "$output" == *"vcpu: FAIL"* ]]
  [[ "$output" == *"geheugen: FAIL"* ]]
}

@test "de schijfregel is N x (images plus 20 GiB): twee stacks vragen het dubbele" {
  max2_stap_a
  # Vrij 30 GB: genoeg voor een stack (23,6 GB nodig), te weinig voor twee (47,2 GB).
  sed -i.bak 's/^docker_root_free_bytes.*/docker_root_free_bytes	30000000000/' "$FACTS"
  # Ruime caps zodat alleen de schijfregel kan falen.
  printf 'RUNNER_CPU=0.1\nRUNNER_MEM_BYTES=1000\nDIND_CPU=0.1\nDIND_MEM_BYTES=1000\n' > "$CAPS"
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES" --stacks 1
  [ "$status" -eq 0 ]
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --images "$IMAGES" --stacks 2
  [ "$status" -eq 40 ]
  [[ "$output" == *"schijf: FAIL"* ]]
  [[ "$output" == *"47244640256 nodig"* ]]
}

@test "een ongeldige waarde voor --stacks is een gebruiksfout" {
  max2_stap_a
  for waarde in 0 -1 abc 1.5 ""; do
    run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --stacks "$waarde"
    [ "$status" -eq 2 ]
  done
  run bash "$SCRIPT" --facts "$FACTS" --caps "$CAPS" --stacks
  [ "$status" -eq 2 ]
}
