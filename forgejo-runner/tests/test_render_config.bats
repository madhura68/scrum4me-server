#!/usr/bin/env bats
# forgejo-runner/tests/test_render_config.bats
# Het configcontract uit §4, §6 en §7.5: exact één connection, absoluut
# token_url zonder placeholder, nooit een tokenwaarde, capacity 1, docker_host
# "-", canonieke digest-gepinde labels, en fail-closed op een lege of
# tag-gebaseerde labellijst (§7.4).

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/render-config.sh"
  POLICY="$REPO_ROOT/forgejo-runner/runner-config.policy.yml"
  LABELS="$BATS_TEST_TMPDIR/labels.txt"
  echo 'ubuntu-latest:docker://catthehacker/ubuntu@sha256:abc' > "$LABELS"
  OUT="$BATS_TEST_TMPDIR/runner-config.yml"
  UUID=11111111-2222-3333-4444-555555555555
}

render() { bash "$SCRIPT" --uuid "$UUID" --labels "$LABELS" --policy "$POLICY" --out "$OUT" "$@"; }

@test "rendert exact een connection" {
  render
  run python3 -c "
import re
tekst = open('$OUT').read()
print(len(re.findall(r'^\s+forgejo:', tekst, re.M)))
"
  [ "$output" = "1" ]
}

@test "gebruikt het absolute token_url en geen placeholder" {
  render
  grep -q 'token_url: file:/run/forgejo-runner-credentials/forgejo-token' "$OUT"
  run grep -c 'CREDENTIALS_DIRECTORY' "$OUT"
  [ "$output" = "0" ]
}

@test "bevat geen tokenwaarde" {
  render
  run grep -cE '^\s+token:' "$OUT"
  [ "$output" = "0" ]
}

@test "zet capacity op 1 en docker_host op streepje" {
  render
  grep -qE 'capacity: *1' "$OUT"
  grep -qE 'docker_host: *"-"' "$OUT"
}

@test "neemt de labels uit labels.txt over" {
  render
  grep -q 'catthehacker/ubuntu@sha256:abc' "$OUT"
}

@test "weigert een lege labellijst" {
  : > "$BATS_TEST_TMPDIR/leeg.txt"
  run bash "$SCRIPT" --uuid "$UUID" --labels "$BATS_TEST_TMPDIR/leeg.txt" --policy "$POLICY" --out "$OUT"
  [ "$status" -eq 3 ]
}

@test "weigert een label zonder digest" {
  echo 'ubuntu-latest:docker://catthehacker/ubuntu:act-latest' > "$BATS_TEST_TMPDIR/tag.txt"
  run bash "$SCRIPT" --uuid "$UUID" --labels "$BATS_TEST_TMPDIR/tag.txt" --policy "$POLICY" --out "$OUT"
  [ "$status" -eq 4 ]
}

@test "een labellijst met alleen commentaar telt als leeg" {
  # De echte labels.txt draagt uitleg bovenin; die regels zijn geen labels.
  printf '# alleen uitleg\n\n' > "$BATS_TEST_TMPDIR/commentaar.txt"
  run bash "$SCRIPT" --uuid "$UUID" --labels "$BATS_TEST_TMPDIR/commentaar.txt" --policy "$POLICY" --out "$OUT"
  [ "$status" -eq 3 ]
}

@test "commentaarregels in labels.txt komen niet in de config terecht" {
  printf '# uitleg\nubuntu-latest:docker://catthehacker/ubuntu@sha256:abc\n' > "$LABELS"
  render
  run grep -c '# uitleg' "$OUT"
  [ "$output" = "0" ]
  run grep -c -- '- ubuntu-latest:docker://catthehacker/ubuntu@sha256:abc' "$OUT"
  [ "$output" = "1" ]
}

@test "weigert een UUID die niet de UUID-vorm heeft" {
  # Een verschreven UUID levert een config die pas op de host faalt met een
  # CREDENTIAL_ERROR; beter hier al fail-closed.
  run bash "$SCRIPT" --uuid niet-een-uuid --labels "$LABELS" --policy "$POLICY" --out "$OUT"
  [ "$status" -eq 5 ]
}

@test "de gedeelde policy bevat geen uuid, token of hostnaam" {
  # §6: de policy is byte-identiek op beide hosts; alles hostspecifieks komt
  # uit render-config.sh.
  # Toets de inhoud, niet de uitleg: commentaar mag die woorden noemen.
  run grep -iE 'uuid|token|scrum4me-server|max2' <(sed 's/#.*$//' "$POLICY")
  [ "$status" -ne 0 ]
}

@test "de policy staat letterlijk in de gerenderde config" {
  render
  python3 - "$POLICY" "$OUT" <<'PY'
import sys
policy, out = open(sys.argv[1]).read(), open(sys.argv[2]).read()
assert policy in out, "policy niet letterlijk overgenomen"
PY
}

@test "--url overschrijft de standaard-Forgejo-url" {
  render --url https://voorbeeld.invalid
  grep -q 'url: https://voorbeeld.invalid' "$OUT"
  run grep -c 'git.jp-visser.nl' "$OUT"
  [ "$output" = "0" ]
}
