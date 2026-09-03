#!/usr/bin/env bats
# forgejo-runner/tests/test_secret_scan.bats
# De doorlopende secret-scan uit §6.1: blokkeert tokens, private sleutels en
# secretbestanden, en laat digests, UUID's en de token_url-placeholder door.
# De sleutelfixtures worden met printf opgebouwd: de regel voor private
# sleutels kent bewust geen ontsnapping, dus de letterlijke marker mag niet in
# dit bestand staan -- anders blokkeert de hook de test van de hook.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/secret-scan.sh"
  INSTALLER="$REPO_ROOT/forgejo-runner/scripts/install-git-hooks.sh"
  WERK="$BATS_TEST_TMPDIR/werk"
  mkdir -p "$WERK"
  TOKEN40="$(printf 'a%.0s' {1..40})"
}

@test "schone inhoud levert exit 0" {
  printf 'log:\n  level: info\n' > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 0 ]
}

@test "een forgejo-tokenpatroon wordt geblokkeerd" {
  printf 'token: %s\n' "$TOKEN40" > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 70 ]
  [[ "$output" == *"tokenachtige waarde"* ]]
}

@test "een private sleutel wordt geblokkeerd" {
  printf -- "-----BEGIN %s PRIVATE KEY-----\n" OPENSSH > "$WERK/id"
  run bash "$SCRIPT" "$WERK/id"
  [ "$status" -eq 70 ]
}

@test "een secretbestandsnaam wordt geblokkeerd" {
  echo "wat dan ook" > "$WERK/forgejo-token"
  run bash "$SCRIPT" "$WERK/forgejo-token"
  [ "$status" -eq 70 ]
}

@test "een digest is geen secret" {
  echo "image: catthehacker/ubuntu@sha256:$(printf 'b%.0s' {1..64})" > "$WERK/labels.txt"
  run bash "$SCRIPT" "$WERK/labels.txt"
  [ "$status" -eq 0 ]
}

@test "een uuid is geen secret" {
  echo "uuid: 11111111-2222-3333-4444-555555555555" > "$WERK/config.yml"
  run bash "$SCRIPT" "$WERK/config.yml"
  [ "$status" -eq 0 ]
}

@test "de placeholder token_url is geen secret" {
  echo "token_url: file:/run/forgejo-runner-credentials/forgejo-token" > "$WERK/c.yml"
  run bash "$SCRIPT" "$WERK/c.yml"
  [ "$status" -eq 0 ]
}

@test "een token in env-vorm met hoofdletters wordt geblokkeerd (het ISS-8-patroon)" {
  # Het lek van 31 augustus was RUNNER_REGISTRATION_TOKEN=<40 hex> in de
  # container-env. Een case-sensitive scan op 'token' ziet dat niet.
  printf 'RUNNER_REGISTRATION_TOKEN=%s\n' "$(printf '0123456789abcdef%.0s' {1..3})01234567" > "$WERK/env.txt"
  run bash "$SCRIPT" "$WERK/env.txt"
  [ "$status" -eq 70 ]
}

@test "een token in json-vorm wordt geblokkeerd" {
  printf '{"token": "%s"}\n' "$TOKEN40" > "$WERK/inspect.json"
  run bash "$SCRIPT" "$WERK/inspect.json"
  [ "$status" -eq 70 ]
}

@test ".env wordt geblokkeerd maar .env.example niet" {
  echo "RUNNER_IMAGE=x@sha256:abc" > "$WERK/.env"
  run bash "$SCRIPT" "$WERK/.env"
  [ "$status" -eq 70 ]
  echo "RUNNER_IMAGE=x@sha256:abc" > "$WERK/.env.example"
  run bash "$SCRIPT" "$WERK/.env.example"
  [ "$status" -eq 0 ]
}

@test "meerdere bestanden: een treffer ergens is genoeg voor 70, en alle treffers worden gemeld" {
  printf 'token: %s\n' "$TOKEN40" > "$WERK/a.yml"
  echo "schoon" > "$WERK/b.yml"
  printf -- "-----BEGIN %s PRIVATE KEY-----\n" RSA > "$WERK/c.pem.txt"
  run bash "$SCRIPT" "$WERK/a.yml" "$WERK/b.yml" "$WERK/c.pem.txt"
  [ "$status" -eq 70 ]
  [[ "$output" == *"a.yml"* ]]
  [[ "$output" == *"c.pem.txt"* ]]
  [[ "$output" != *"b.yml"* ]]
}

@test "de marker secret-scan: fixture verleent GEEN bypass: een echte token blijft geblokkeerd" {
  # Regressie voor de MAJOR uit reviewronde 1 (mac:codex): de marker zat in een
  # globale line-exclusie, waardoor 'TOKEN=<40 hex>  # secret-scan: fixture' in
  # een willekeurig bestand de gate passeerde. De marker-uitzondering is
  # verwijderd; de tokenregel wordt ongeacht een bijgevoegde marker geblokkeerd.
  printf 'RUNNER_REGISTRATION_TOKEN=%s  # secret-scan: fixture\n' "$TOKEN40" > "$WERK/marker.env"
  run bash "$SCRIPT" "$WERK/marker.env"
  [ "$status" -eq 70 ]
}

@test "een korte, duidelijk-nep tokenwaarde (<20 tekens) is geen secret" {
  # De redactor-fixtures gebruiken voortaan zo'n waarde i.p.v. een marker.
  printf 'RUNNER_REGISTRATION_TOKEN=%s\n' "FAKE-TEST-TOKEN" > "$WERK/fixture.env"
  run bash "$SCRIPT" "$WERK/fixture.env"
  [ "$status" -eq 0 ]
}

@test "de echte bundel en het stap-A-bewijs zijn schoon" {
  # Dit is de eenmalige scan van stap B uit §8, mechanisch.
  cd "$REPO_ROOT"
  run bash "$SCRIPT" $(git ls-files forgejo-runner docs/forgejo-runner-pool/evidence)
  [ "$status" -eq 0 ]
}

@test "zonder argumenten scant hij de staged bestanden" {
  REPO="$BATS_TEST_TMPDIR/repo"
  git init -q "$REPO"
  printf 'token: %s\n' "$TOKEN40" > "$REPO/geheim.yml"
  git -C "$REPO" add geheim.yml
  run bash -c "cd '$REPO' && bash '$SCRIPT'"
  [ "$status" -eq 70 ]
  git -C "$REPO" reset -q
  echo "schoon" > "$REPO/ok.yml"
  git -C "$REPO" add ok.yml
  run bash -c "cd '$REPO' && bash '$SCRIPT'"
  [ "$status" -eq 0 ]
}

@test "de installer zet een pre-commit hook die een tokencommit blokkeert" {
  REPO="$BATS_TEST_TMPDIR/hookrepo"
  git init -q "$REPO"
  git -C "$REPO" config user.email t@example.invalid
  git -C "$REPO" config user.name t
  run bash "$INSTALLER" "$REPO"
  [ "$status" -eq 0 ]
  [ -x "$REPO/.git/hooks/pre-commit" ]
  printf 'token: %s\n' "$TOKEN40" > "$REPO/geheim.yml"
  git -C "$REPO" add geheim.yml
  run git -C "$REPO" commit -q -m "hoort te falen"
  [ "$status" -ne 0 ]
  [[ "$output" == *"tokenachtige waarde"* ]]
  git -C "$REPO" reset -q
  echo "schoon" > "$REPO/ok.yml"
  git -C "$REPO" add ok.yml
  run git -C "$REPO" commit -q -m "hoort te slagen"
  [ "$status" -eq 0 ]
}

@test "de installer respecteert core.hooksPath" {
  REPO="$BATS_TEST_TMPDIR/hookpathrepo"
  git init -q "$REPO"
  git -C "$REPO" config core.hooksPath .githooks
  run bash "$INSTALLER" "$REPO"
  [ "$status" -eq 0 ]
  [ -x "$REPO/.githooks/pre-commit" ]
  [ ! -e "$REPO/.git/hooks/pre-commit" ]
}

@test "de installer weigert een map die geen werkboom is" {
  run bash "$INSTALLER" "$WERK"
  [ "$status" -eq 2 ]
}
