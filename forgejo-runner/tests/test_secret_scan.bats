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

# --- Bypassen uit de audit van 2026-09-30 (T-151) ---------------------------
# Elke test bouwt een wegwerprepo en laat het script de index beoordelen.

maak_repo() {
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
  REPO="$BATS_TEST_TMPDIR/auditrepo"
  git init -q "$REPO"
  git -C "$REPO" config user.email t@example.invalid
  git -C "$REPO" config user.name t
}

scan_index() {
  run bash -c "cd '$REPO' && bash '$SCRIPT'"
}

@test "audit 1: een hernoemd en bewerkt bestand (R) met een token wordt geblokkeerd" {
  maak_repo
  printf 'log:\n  level: info\n  regel: een\n  regel2: twee\n  regel3: drie\n  regel4: vier\n' > "$REPO/a.yml"
  git -C "$REPO" add a.yml
  git -C "$REPO" commit -q -m basis
  git -C "$REPO" mv a.yml b.yml
  printf 'token: %s\n' "$TOKEN40" >> "$REPO/b.yml"
  git -C "$REPO" add b.yml
  [[ "$(git -C "$REPO" diff --cached --name-status)" == R* ]]
  scan_index
  [ "$status" -eq 70 ]
}

@test "audit 2: onder bash 3.2 faalt de scan niet open" {
  case "$(/bin/bash -c 'echo ${BASH_VERSINFO[0]}')" in
    3) : ;;
    *) skip "/bin/bash is geen 3.x op deze host" ;;
  esac
  maak_repo
  printf 'token: %s\n' "$TOKEN40" > "$REPO/geheim.yml"
  git -C "$REPO" add geheim.yml
  run /bin/bash -c "cd '$REPO' && /bin/bash '$SCRIPT'"
  [ "$status" -eq 70 ]
}

@test "audit 3: een uuid, digest of token_url op dezelfde regel maskeert een echte token niet" {
  maak_repo
  printf '{"uuid":"11111111-2222-3333-4444-555555555555","token":"%s"}\n' "$TOKEN40" > "$REPO/a.json"
  printf 'token: %s # sha256:%s\n' "$TOKEN40" "$(printf 'b%.0s' {1..64})" > "$REPO/b.yml"
  printf 'token_url: x token: %s\n' "$TOKEN40" > "$REPO/c.yml"
  for f in a.json b.yml c.yml; do
    git -C "$REPO" add "$f"
    scan_index
    [ "$status" -eq 70 ]
    git -C "$REPO" reset -q
  done
}

@test "audit 4: PKCS#8 en versleutelde private sleutels worden geblokkeerd" {
  maak_repo
  for soort in "" "ENCRYPTED "; do
    printf -- '-----BEGIN %sPRIVATE KEY-----\n' "$soort" > "$REPO/sleutel.txt"
    git -C "$REPO" add sleutel.txt
    scan_index
    [ "$status" -eq 70 ]
    git -C "$REPO" reset -q
  done
}

@test "audit 5: een waarde tussen enkele aanhalingstekens wordt geblokkeerd" {
  maak_repo
  printf "token: '%s'\n" "$TOKEN40" > "$REPO/a.yml"
  git -C "$REPO" add a.yml
  scan_index
  [ "$status" -eq 70 ]
}

@test "audit 6: sleutelnamen zonder token/secret/password worden herkend" {
  maak_repo
  printf 'API_KEY=%s\n' "$TOKEN40" > "$REPO/a.txt"
  printf 'DB_PASSWD=%s\n' "$TOKEN40" > "$REPO/b.txt"
  for f in a.txt b.txt; do
    git -C "$REPO" add "$f"
    scan_index
    [ "$status" -eq 70 ]
    git -C "$REPO" reset -q
  done
}

@test "audit 7: .env.local, prod.env en x.token zijn secretbestanden" {
  maak_repo
  for f in .env.local prod.env x.token; do
    echo "schoon" > "$REPO/$f"
    git -C "$REPO" add -f "$f"
    scan_index
    [ "$status" -eq 70 ]
    git -C "$REPO" reset -q
  done
}

@test "audit 8: de scan beoordeelt de staged blob, niet het werkbestand" {
  maak_repo
  printf 'token: %s\n' "$TOKEN40" > "$REPO/a.yml"
  git -C "$REPO" add a.yml
  echo "schoon" > "$REPO/a.yml"
  scan_index
  [ "$status" -eq 70 ]
}
