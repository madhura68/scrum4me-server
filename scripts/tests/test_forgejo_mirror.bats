# scripts/tests/test_forgejo_mirror.bats
# Hermetische tests voor scripts/forgejo-mirror/*: fake curl/git/flock/date/sleep
# vooraan op PATH, echte jq. Geen netwerk, geen ssh.

FJ="https://forgejo.test"
GH="https://gh.test"

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/scripts/forgejo-mirror/forgejo-mirror-sync.sh"
  LIB="$REPO_ROOT/scripts/forgejo-mirror/forgejo-mirror-lib.sh"
  T="$BATS_TEST_TMPDIR"
  FAKE_BIN="$T/bin"; FIX="$T/fix"; LOGDIR="$T/log"
  mkdir -p "$FAKE_BIN" "$FIX" "$LOGDIR"
  : > "$LOGDIR/curl.log"; : > "$LOGDIR/calls.log"; : > "$LOGDIR/stdin.log"
  : > "$LOGDIR/config.log"; : > "$LOGDIR/git.log"

  # Distinctieve proefwaarden (bewust kort; geen echte credentials).
  FJTOK="fjdummy7Q2x"; GHTOK="ghdummy4Kp9"
  printf 'FORGEJO_BASE_URL=%s\nFORGEJO_USERNAME=janpeter\nFORGEJO_TOKEN=%s\n' "$FJ" "$FJTOK" > "$T/forgejo.env"
  printf 'GH_API_URL=%s\nGH_USERNAME=ghuser\nGH_TOKEN=%s\n' "$GH" "$GHTOK" > "$T/github.env"

  export FAKE_FIX="$FIX" FAKE_LOG="$LOGDIR"
  export ENV_FORGEJO="$T/forgejo.env" ENV_GITHUB="$T/github.env"
  export STATE_FILE="$T/state/state.json" LOCK_FILE="$T/lock/mirror.lock"
  export MIRROR_CLONE_DIR="$T/clones"
  unset DRY_RUN REPOS_FILTER FAKE_FLOCK_BUSY

  cat > "$FAKE_BIN/curl" <<'EOS'
#!/usr/bin/env bash
# Antwoordt op METHOD+URL uit $FAKE_FIX; logt argv, stdin en config.
method=GET out="" wfmt="" data="" url="" cfg=""
args=("$@")
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    -w) wfmt="$2"; shift 2 ;;
    -m|-H) shift 2 ;;
    --data|--data-binary) data="$2"; shift 2 ;;
    -K|--config) cfg="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\n' "${args[*]}" >> "$FAKE_LOG/curl.log"
printf '%s %s\n' "$method" "$url" >> "$FAKE_LOG/calls.log"
if [ "$data" = "@-" ]; then cat >> "$FAKE_LOG/stdin.log"; printf '\n' >> "$FAKE_LOG/stdin.log"; fi
if [ -n "$cfg" ] && [ -r "$cfg" ]; then cat "$cfg" >> "$FAKE_LOG/config.log"; fi
norm() { printf '%s_%s' "$method" "$1" | tr -c 'A-Za-z0-9\n' _; }
full=$(norm "${url#*://}")
q="${url%%\?*}"; bkey=$(norm "${q#*://}")
if [ -f "$FAKE_FIX/$full.body" ] || [ -f "$FAKE_FIX/$full.code" ]; then key="$full"; else key="$bkey"; fi
body='{}'; code=404
[ -f "$FAKE_FIX/$key.body" ] && { body=$(cat "$FAKE_FIX/$key.body"); code=200; }
[ -f "$FAKE_FIX/$key.code" ] && code=$(cat "$FAKE_FIX/$key.code")
if [ -n "$out" ]; then printf '%s' "$body" > "$out"; else printf '%s' "$body"; fi
[ -n "$wfmt" ] && printf '%s' "$code"
exit 0
EOS
  cat > "$FAKE_BIN/git" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG/git.log"
printf 'ASKPASS=%s\n' "${GIT_ASKPASS:-}" >> "$FAKE_LOG/git-env.log"
if [ -n "${GIT_ASKPASS:-}" ] && [ -x "${GIT_ASKPASS:-}" ]; then
  { "$GIT_ASKPASS" Username; "$GIT_ASKPASS" Password; } >> "$FAKE_LOG/askpass.log" 2>&1
fi
for a in "$@"; do last="$a"; done
case " $* " in *" clone "*) mkdir -p "$last" ;; esac
exit "${FAKE_GIT_RC:-0}"
EOS
  cat > "$FAKE_BIN/flock" <<'EOS'
#!/usr/bin/env bash
[ "${FAKE_FLOCK_BUSY:-0}" = "1" ] && exit 1
exit 0
EOS
  cat > "$FAKE_BIN/sleep" <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  cat > "$FAKE_BIN/date" <<'EOS'
#!/usr/bin/env bash
# `date -d <ts>` (GNU) bestaat niet op macOS: geef een ver-toekomstige epoch.
if [ "${1:-}" = "-d" ]; then echo 99999999999; exit 0; fi
exec /bin/date "$@"
EOS
  chmod +x "$FAKE_BIN"/*
  PATH="$FAKE_BIN:$PATH"

  fx GET "$FJ/api/v1/version" '{"version":"15.0.9"}'
  fx GET "$FJ/swagger.v1.json" '{"definitions":{"CreatePushMirrorOption":{"properties":{"branch_filter":{}}}}}'
  fx GET "$FJ/api/v1/user" '{}'
  fx GET "$GH/user" '{}'
}

# fx METHOD URL BODY [CODE]
fx() {
  local key; key=$(printf '%s_%s' "$1" "${2#*://}" | tr -c 'A-Za-z0-9\n' _)
  printf '%s' "$3" > "$FIX/$key.body"
  if [ -n "${4:-}" ]; then printf '%s' "$4" > "$FIX/$key.code"; fi
  return 0
}

# set_repos naam...  (enumeratie)
set_repos() {
  local json='[' sep='' n
  for n in "$@"; do
    json+="$sep{\"name\":\"$n\",\"default_branch\":\"main\",\"owner\":{\"login\":\"janpeter\"}}"; sep=','
  done
  fx GET "$FJ/api/v1/users/janpeter/repos?limit=50&page=1" "$json]"
}

# healthy_repo naam: alles groen, push-mirror al correct.
healthy_repo() {
  local r="$1"
  fx GET "$GH/repos/ghuser/$r" '{"default_branch":"main"}'
  fx GET "$FJ/api/v1/repos/janpeter/$r/push_mirrors" \
    "[{\"remote_address\":\"https://github.com/ghuser/$r.git\",\"remote_name\":\"m1\",\"interval\":\"24h0m0s\",\"branch_filter\":\"main\",\"last_update\":\"2026-09-30T00:00:00Z\"}]"
  fx POST "$FJ/api/v1/repos/janpeter/$r/push_mirrors-sync" '' 204
  fx GET "$FJ/api/v1/repos/janpeter/$r/branches/main" '{"commit":{"id":"abc123"}}'
  fx GET "$GH/repos/ghuser/$r/commits/main" '{"sha":"abc123"}'
  fx GET "$FJ/api/v1/repos/janpeter/$r/tags" '[{"name":"v1"}]'
  fx GET "$GH/repos/ghuser/$r/tags" '[{"name":"v1"}]'
}

mutations() { grep -cE '^(POST|PATCH|DELETE|PUT) ' "$LOGDIR/calls.log" || true; }

@test "happy path: twee repos gespiegeld" {
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"total=2 mirrored=2 skipped_workflow=0 skipped_other=0 errors=0"* ]]
  [ -f "$STATE_FILE" ]
  jq -e 'has("janpeter/alpha") and has("janpeter/beta")' "$STATE_FILE"
}

@test "een repo faalt in ensure_push_mirror: de andere wordt toch gespiegeld" {
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  fx GET "$FJ/api/v1/repos/janpeter/alpha/push_mirrors" '{}' 500
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"mirrored=1"* ]]
  [[ "$output" == *"errors=1"* ]]
  grep -q 'janpeter/beta/branches/main' "$LOGDIR/calls.log"
}

@test "GitHub default branch wijkt af: ERROR en errors=1, geen sync" {
  set_repos alpha; healthy_repo alpha
  fx GET "$GH/repos/ghuser/alpha" '{"default_branch":"codex/oud"}'
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"default branch 'codex/oud' ≠ Forgejo 'main'"* ]]
  [[ "$output" == *"errors=1"* ]]
  ! grep -q 'push_mirrors-sync' "$LOGDIR/calls.log"
}

@test "repo met .github/workflows en zonder override-token: SKIP" {
  set_repos alpha; healthy_repo alpha
  fx GET "$FJ/api/v1/repos/janpeter/alpha/contents/.github/workflows" '[]' 200
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP janpeter/alpha: bevat .github/workflows"* ]]
  [[ "$output" == *"skipped_workflow=1"* ]]
  ! grep -q 'gh.test/repos/ghuser/alpha' "$LOGDIR/calls.log"
}

@test "DRY_RUN=1: geen POST/PATCH/DELETE en geen git push" {
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  fx GET "$FJ/api/v1/repos/janpeter/alpha/push_mirrors" '[]'
  fx GET "$FJ/api/v1/repos/janpeter/beta/tags" '[{"name":"v1"},{"name":"v2"}]'
  DRY_RUN=1 run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"DRY_RUN"* ]]
  [ "$(mutations)" -eq 0 ]
  ! grep -q ' push ' "$LOGDIR/git.log"
  [ ! -e "$STATE_FILE" ]
}

@test "tweede instantie terwijl de lock vastzit: weigert" {
  set_repos alpha; healthy_repo alpha
  FAKE_FLOCK_BUSY=1 run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"andere instantie draait al"* ]]
  [ ! -s "$LOGDIR/calls.log" ]
}

@test "tags-mismatch: tags_fallback kloont en pusht via git" {
  set_repos alpha; healthy_repo alpha
  fx GET "$GH/repos/ghuser/alpha/tags" '[]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'clone --bare' "$LOGDIR/git.log"
  grep -q 'push --tags --force' "$LOGDIR/git.log"
}

# ───────────────────── token-hygiene (T-169) ─────────────────────

@test "tokens staan niet in curl-argv; auth gaat via -K config" {
  set_repos alpha; healthy_repo alpha
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -s "$LOGDIR/curl.log" ]
  ! grep -qF "$FJTOK" "$LOGDIR/curl.log"
  ! grep -qF "$GHTOK" "$LOGDIR/curl.log"
  ! grep -q -- '-H Authorization' "$LOGDIR/curl.log"
  grep -q -- '-K ' "$LOGDIR/curl.log"
  # de credentials komen wél (alleen) via de config-pipe binnen
  grep -qF "token $FJTOK" "$LOGDIR/config.log"
  grep -qF "Bearer $GHTOK" "$LOGDIR/config.log"
}

@test "push-mirror-payload gaat via stdin met de token, niet via argv" {
  set_repos alpha; healthy_repo alpha
  fx GET "$FJ/api/v1/repos/janpeter/alpha/push_mirrors" '[]'
  fx POST "$FJ/api/v1/repos/janpeter/alpha/push_mirrors" '{}' 201
  run bash "$SCRIPT"
  grep -q 'POST https://forgejo.test/api/v1/repos/janpeter/alpha/push_mirrors$' "$LOGDIR/calls.log"
  ! grep -qF "$GHTOK" "$LOGDIR/curl.log"
  ! grep -qF "$FJTOK" "$LOGDIR/curl.log"
  grep -q -- '--data-binary @-' "$LOGDIR/curl.log"
  [ "$(jq -r '.remote_password' "$LOGDIR/stdin.log")" = "$GHTOK" ]
  [ "$(jq -r '.remote_username' "$LOGDIR/stdin.log")" = "ghuser" ]
}

@test "tags_fallback: URL's zonder userinfo, credentials via GIT_ASKPASS, tempdir opgeruimd" {
  set_repos alpha; healthy_repo alpha
  fx GET "$GH/repos/ghuser/alpha/tags" '[]'
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'clone --bare' "$LOGDIR/git.log"
  grep -q 'push --tags --force' "$LOGDIR/git.log"
  ! grep -qF "$FJTOK" "$LOGDIR/git.log"
  ! grep -qF "$GHTOK" "$LOGDIR/git.log"
  ! grep -Eq '://[^/ ]*@' "$LOGDIR/git.log"
  # de helper leverde de credentials aan git (clone: Forgejo, push: GitHub)
  grep -qF "$FJTOK" "$LOGDIR/askpass.log"
  grep -qF "$GHTOK" "$LOGDIR/askpass.log"
  # helper-dir is na afloop weg
  ap=$(grep -m1 '^ASKPASS=/' "$LOGDIR/git-env.log" | cut -d= -f2-)
  [ -n "$ap" ]
  [ ! -e "$ap" ]
  [ ! -e "$(dirname "$ap")" ]
}

@test "tags_fallback: bestaande clone krijgt remote set-url zonder userinfo" {
  set_repos alpha; healthy_repo alpha
  fx GET "$GH/repos/ghuser/alpha/tags" '[]'
  mkdir -p "$MIRROR_CLONE_DIR/janpeter-alpha.git"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'remote set-url origin https://forgejo.test/janpeter/alpha.git$' "$LOGDIR/git.log"
  grep -q 'fetch --tags' "$LOGDIR/git.log"
  ! grep -Eq '://[^/ ]*@' "$LOGDIR/git.log"
}

# ───────────────────── logica-fixes (T-171) ─────────────────────

@test "kapotte state-file: alle repos worden toch verwerkt; warning + errors" {
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  mkdir -p "$(dirname "$STATE_FILE")"; printf 'geen json' > "$STATE_FILE"
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"total=2 mirrored=2"* ]]
  [[ "$output" == *"errors=2"* ]]
  [[ "$output" == *"state-update voor janpeter/alpha mislukt"* ]]
  grep -q 'janpeter/beta/branches/main' "$LOGDIR/calls.log"
  [ "$(cat "$STATE_FILE")" = "geen json" ]
}

@test "onschrijfbare state-map: alle repos worden toch verwerkt" {
  [ "$(id -u)" -ne 0 ] || skip "root negeert directory-permissies"
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  mkdir -p "$(dirname "$STATE_FILE")"; chmod 555 "$(dirname "$STATE_FILE")"
  run bash "$SCRIPT"
  chmod 755 "$(dirname "$STATE_FILE")"
  [ "$status" -ne 0 ]
  [[ "$output" == *"mirrored=2"* ]]
  [[ "$output" == *"errors=2"* ]]
}

@test "state-update is atomair: geen tempfile-restanten in de state-map" {
  set_repos alpha; healthy_repo alpha
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$STATE_FILE" ]
  [ -z "$(ls -A "$(dirname "$STATE_FILE")" | grep -v '^state.json$')" ]
}

@test "workflow-check geeft 500: die repo is een fout, de andere loopt door" {
  set_repos alpha beta; healthy_repo alpha; healthy_repo beta
  fx GET "$FJ/api/v1/repos/janpeter/alpha/contents/.github/workflows" '{}' 500
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"workflow-check janpeter/alpha faalt (HTTP 500)"* ]]
  [[ "$output" == *"mirrored=1"* ]]
  [[ "$output" == *"errors=1"* ]]
  ! grep -q 'gh.test/repos/ghuser/alpha' "$LOGDIR/calls.log"
  grep -q 'janpeter/beta/branches/main' "$LOGDIR/calls.log"
}

@test "workflow-check 404 telt als 'geen workflows' (repo wordt gespiegeld)" {
  set_repos alpha; healthy_repo alpha
  fx GET "$FJ/api/v1/repos/janpeter/alpha/contents/.github/workflows" '{}' 404
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"mirrored=1"* ]]
}

@test "verify_tags pagineert: >1 pagina aan weerszijden geeft tags-match, geen fallback" {
  set_repos alpha; healthy_repo alpha
  all=$(jq -nc '[range(1;102) | {name: ("v" + tostring)}]')
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=1" "$(jq -c '.[0:50]' <<<"$all")"
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=2" "$(jq -c '.[50:100]' <<<"$all")"
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=3" "$(jq -c '.[100:]' <<<"$all")"
  fx GET "$GH/repos/ghuser/alpha/tags?per_page=100&page=1" "$(jq -c '.[0:100]' <<<"$all")"
  fx GET "$GH/repos/ghuser/alpha/tags?per_page=100&page=2" "$(jq -c '.[100:]' <<<"$all")"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"tags-match janpeter/alpha (101 tags)"* ]]
  ! grep -q 'push --tags' "$LOGDIR/git.log"
  grep -q 'janpeter/alpha/tags?limit=50&page=3' "$LOGDIR/calls.log"
  grep -q 'ghuser/alpha/tags?per_page=100&page=2' "$LOGDIR/calls.log"
}

@test "verify_tags pagineert: tag alleen op pagina 2 van GitHub ontbreekt aan Forgejo-kant -> fallback" {
  set_repos alpha; healthy_repo alpha
  all=$(jq -nc '[range(1;102) | {name: ("v" + tostring)}]')
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=1" "$(jq -c '.[0:50]' <<<"$all")"
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=2" "$(jq -c '.[50:100]' <<<"$all")"
  fx GET "$FJ/api/v1/repos/janpeter/alpha/tags?limit=50&page=3" '[]'
  fx GET "$GH/repos/ghuser/alpha/tags?per_page=100&page=1" "$(jq -c '.[0:100]' <<<"$all")"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'push --tags' "$LOGDIR/git.log"
}

@test "repo-naam met punt: per repo geweigerd, de rest loopt door" {
  set_repos foo.bar beta; healthy_repo beta
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"repo-naam 'foo.bar' bevat tekens buiten [A-Za-z0-9_-]"* ]]
  [[ "$output" == *"mirrored=1"* ]]
  [[ "$output" == *"errors=1"* ]]
  ! grep -q 'gh.test/repos/ghuser/foo.bar' "$LOGDIR/calls.log"
}

@test "gh_token_for_repo: override, default en ongeldige naam" {
  run bash -c "source '$LIB'; export GH_TOKEN=def GH_TOKEN_MY_REPO=ovr; gh_token_for_repo my-repo; echo; gh_token_for_repo other"
  [ "$status" -eq 0 ]
  [[ "${lines[0]}" == "ovr" ]]
  [[ "${lines[1]}" == "def" ]]
  run bash -c "source '$LIB'; GH_TOKEN=def; gh_token_for_repo 'a b'"
  [ "$status" -eq 1 ]
  [[ "$output" == *"bevat tekens buiten [A-Za-z0-9_-]"* ]]
}
