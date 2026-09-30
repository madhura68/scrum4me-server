#!/usr/bin/env bash
# forgejo-mirror-lib.sh — herbruikbare functies voor forgejo-mirror-sync.sh
# Geen 'set' hier; main script bepaalt strict-mode. Source dit bestand,
# roep functies aan, en gebruik return-codes (0 = ok, niet-0 = fout).
#
# Vereiste env (uit /etc/forgejo-mirror/*.env):
#   FORGEJO_BASE_URL  FORGEJO_USERNAME  FORGEJO_TOKEN
#   GH_API_URL        GH_USERNAME       GH_TOKEN
# Optioneel:
#   DRY_RUN=1                — alleen GET's; geen POST/DELETE/PATCH
#   STATE_FILE=<pad>         — default /var/lib/forgejo-mirror/state.json
#   MIRROR_CLONE_DIR=<pad>   — default /srv/scrum4me/repos/mirrors
#   MIRROR_INTERVAL=<dur>    — default 24h (Forgejo push_mirror interval)

# ───────────────────────────── logging ─────────────────────────────

log() {
  # Schrijf naar stderr (stdout is voor parseable data). Geen tokens loggen.
  local lvl="INFO" msg
  if [ "${1:-}" = "-l" ]; then lvl="$2"; shift 2; fi
  msg="$*"
  printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$lvl" "$msg" >&2
}

die() { log -l ERROR "$*"; exit 1; }

# ─────────────────────── HTTP wrappers (curl + jq) ──────────────────

# Schrijft response-body naar stdout, http-code naar fd 3 (gevangen).
# Args:  <method> <full-url> [auth-header] [data-string]
# Echoes: body
# Returns 0 als 2xx, 1 als 4xx/5xx (body bevat error-info uit API).
_http() {
  local method="$1" url="$2" auth="${3:-}" data="${4:-}"
  local tmp; tmp=$(mktemp) || return 2
  local code
  # shellcheck disable=SC2086  # we willen 'auth' als losse header-arg of niet
  if [ -n "$data" ]; then
    code=$(curl -sS -m 30 -o "$tmp" -w '%{http_code}' \
      -X "$method" -H "$auth" -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      --data "$data" "$url")
  else
    code=$(curl -sS -m 30 -o "$tmp" -w '%{http_code}' \
      -X "$method" -H "$auth" -H "Accept: application/json" \
      "$url")
  fi
  cat "$tmp"
  rm -f "$tmp"
  case "$code" in
    2*) return 0 ;;
    *) log -l WARN "HTTP $code on $method $url"; return 1 ;;
  esac
}

# Forgejo API helper.  fj <method> <path-zonder-base> [data]
fj() {
  local method="$1" path="$2" data="${3:-}"
  _http "$method" "${FORGEJO_BASE_URL%/}/api/v1${path}" \
    "Authorization: token $FORGEJO_TOKEN" "$data"
}

# Forgejo HTTP-code only (geen body).  fj_code <method> <path> [data]
fj_code() {
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS -m 30 -o /dev/null -w '%{http_code}' \
      -X "$method" -H "Authorization: token $FORGEJO_TOKEN" \
      -H "Accept: application/json" -H "Content-Type: application/json" \
      --data "$data" "${FORGEJO_BASE_URL%/}/api/v1${path}"
  else
    curl -sS -m 30 -o /dev/null -w '%{http_code}' \
      -X "$method" -H "Authorization: token $FORGEJO_TOKEN" \
      -H "Accept: application/json" \
      "${FORGEJO_BASE_URL%/}/api/v1${path}"
  fi
}

# Per-repo GitHub token-override. Geeft env-var GH_TOKEN_<REPO_UPPER> terug
# als die gezet is, anders de default $GH_TOKEN. Conventie: '-' en lowercase
# in repo-naam → '_' en uppercase in env-var (bv. "Scrum4Me" → GH_TOKEN_SCRUM4ME,
# "scrum4me-docker" → GH_TOKEN_SCRUM4ME_DOCKER). Gebruik in callers via:
#   local _repo_token; _repo_token=$(gh_token_for_repo "$repo")
#   local GH_TOKEN="$_repo_token"
# Resolve VÓÓR de local-shadow: `local GH_TOKEN; GH_TOKEN=$(gh_token_for_repo ...)`
# is fout onder `set -u` — de lege local GH_TOKEN schaduwt de global, dus de
# ${!key:-$GH_TOKEN}-fallback in de functie leest leeg → unbound → 401.
# Bash dynamic scoping zorgt dat gh()/gh_code() daarna de override pakken.
gh_token_for_repo() {
  local repo="$1"
  local key="GH_TOKEN_$(printf '%s' "$repo" | tr '[:lower:]-' '[:upper:]_')"
  printf '%s' "${!key:-$GH_TOKEN}"
}

# GitHub API helper.  gh <method> <path-zonder-base> [data]
gh() {
  local method="$1" path="$2" data="${3:-}"
  _http "$method" "${GH_API_URL%/}${path}" \
    "Authorization: Bearer $GH_TOKEN" "$data"
}

gh_code() {
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS -m 30 -o /dev/null -w '%{http_code}' \
      -X "$method" -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "Content-Type: application/json" \
      --data "$data" "${GH_API_URL%/}${path}"
  else
    curl -sS -m 30 -o /dev/null -w '%{http_code}' \
      -X "$method" -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "${GH_API_URL%/}${path}"
  fi
}

# ───────────────────────────── preflight ────────────────────────────

preflight() {
  # 1. Forgejo bereikbaar + versie ≥ 13.0
  local ver major
  ver=$(curl -sS -m 10 "${FORGEJO_BASE_URL%/}/api/v1/version" | jq -r '.version // ""')
  [ -n "$ver" ] || die "preflight: kan Forgejo version niet ophalen"
  major=$(printf '%s' "$ver" | cut -d. -f1)
  [ "$major" -ge 13 ] 2>/dev/null || die "preflight: Forgejo $ver < 13.0 (zie T-1078/T-1107)"
  log "Forgejo version: $ver"

  # 2. swagger schema bevat branch_filter
  local has_bf
  has_bf=$(curl -sS -m 15 "${FORGEJO_BASE_URL%/}/swagger.v1.json" \
    | jq -r '.definitions.CreatePushMirrorOption.properties | has("branch_filter")')
  [ "$has_bf" = "true" ] || die "preflight: branch_filter ontbreekt in swagger (upgrade Forgejo)"
  log "swagger.CreatePushMirrorOption.branch_filter: present"

  # 3. Forgejo token werkt
  local code
  code=$(fj_code GET /user)
  [ "$code" = "200" ] || die "preflight: Forgejo token check faalt (HTTP $code)"
  log "Forgejo token: OK"

  # 4. GitHub token werkt
  code=$(gh_code GET /user)
  [ "$code" = "200" ] || die "preflight: GitHub token check faalt (HTTP $code)"
  log "GitHub token: OK"
}

# ───────────────────────── repo enumeration ─────────────────────────

# Geeft per regel één Forgejo-repo-JSON-object (compact). Filter: alleen
# repos die door FORGEJO_USERNAME owned worden (geen org-/fork-repos).
enumerate_repos() {
  local page=1 limit=50 body
  while :; do
    body=$(fj GET "/users/${FORGEJO_USERNAME}/repos?limit=${limit}&page=${page}") || return 1
    local count
    count=$(printf '%s' "$body" | jq 'length')
    [ "$count" -eq 0 ] && break
    printf '%s' "$body" | jq -c --arg u "$FORGEJO_USERNAME" \
      '.[] | select(.owner.login == $u)'
    [ "$count" -lt "$limit" ] && break
    page=$((page + 1))
  done
}

# ───────────────────────── workflow detection ───────────────────────

has_workflows() {
  local owner="$1" repo="$2" code
  code=$(fj_code GET "/repos/${owner}/${repo}/contents/.github/workflows")
  [ "$code" = "200" ]
}

# ───────────────────── GitHub counterpart bestaat ───────────────────

# Vereist dat counterpart al handmatig op GitHub is aangemaakt (zie T-1077
# deviation: fine-grained PAT kan POST /user/repos niet). Returnt 0 als
# counterpart bestaat, 1 als 'ie ontbreekt (+log met instructie).
ensure_github_counterpart() {
  local owner="$1" repo="$2" code
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"
  code=$(gh_code GET "/repos/${GH_USERNAME}/${repo}")
  if [ "$code" = "200" ]; then
    return 0
  elif [ "$code" = "404" ]; then
    log -l ERROR "GitHub counterpart ontbreekt: ${GH_USERNAME}/${repo} — maak handmatig aan op GitHub (private, leeg) en run opnieuw"
    return 1
  else
    log -l ERROR "GitHub counterpart-check faalt voor ${repo} (HTTP $code)"
    return 1
  fi
}

# GitHub's default branch must equal Forgejo's. The push mirror mirrors all refs, so it deletes a
# branch on GitHub that no longer exists in Forgejo; GitHub refuses to delete its default branch
# ("refusing to delete the current branch"), which Forgejo reports as a 500 on push_mirrors-sync.
# Seen on 2026-09-30 for When2Watch (GitHub default still codex/when2watch-increment-1).
ensure_github_default_branch() {
  local owner="$1" repo="$2" expected="$3" actual
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"
  actual=$(gh GET "/repos/${GH_USERNAME}/${repo}" | jq -r '.default_branch // empty') || actual=""
  if [ -z "$actual" ]; then
    log -l WARN "default branch van GitHub ${GH_USERNAME}/${repo} niet leesbaar; check overgeslagen"
    return 0
  fi
  [ "$actual" = "$expected" ] && return 0
  log -l ERROR "GitHub ${GH_USERNAME}/${repo}: default branch '${actual}' ≠ Forgejo '${expected}' — de push-mirror kan '${actual}' niet verwijderen; zet op GitHub de default branch op '${expected}' (Settings → Default branch) en run opnieuw"
  return 1
}

# ─────────────────── push-mirror config (idempotent) ────────────────

# Maakt/herbevestigt push_mirror in Forgejo. Bij mismatch op interval of
# branch_filter: DELETE + recreate (review-finding #5).
ensure_push_mirror() {
  local owner="$1" repo="$2" branch="$3"
  local interval="${MIRROR_INTERVAL:-24h}"
  local remote="https://github.com/${GH_USERNAME}/${repo}.git"
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"

  # Forgejo normaliseert "24h" → "24h0m0s" intern; vergelijk in genormaliseerde vorm.
  local interval_norm
  case "$interval" in
    *h)     interval_norm="${interval%h}h0m0s" ;;
    *h*m)   interval_norm="${interval}0s" ;;
    *h*m*s) interval_norm="$interval" ;;
    *)      interval_norm="$interval" ;;
  esac

  local existing matches names_to_delete
  existing=$(fj GET "/repos/${owner}/${repo}/push_mirrors") || return 1

  # Zoek alle entries die naar onze remote wijzen (vaak meer dan 1 bij eerdere bugs).
  matches=$(printf '%s' "$existing" \
    | jq -c --arg ra "$remote" '[.[] | select(.remote_address==$ra)]')
  local match_count
  match_count=$(printf '%s' "$matches" | jq 'length')

  if [ "$match_count" = "1" ]; then
    local cur_int cur_bf
    cur_int=$(printf '%s' "$matches" | jq -r '.[0].interval')
    cur_bf=$(printf '%s'  "$matches" | jq -r '.[0].branch_filter // ""')
    if [ "$cur_int" = "$interval_norm" ] && [ "$cur_bf" = "$branch" ]; then
      log "push_mirror OK voor ${owner}/${repo}"
      return 0
    fi
    log "push_mirror config-mismatch voor ${owner}/${repo}: int='$cur_int'->'$interval_norm' bf='$cur_bf'->'$branch' — recreate"
  elif [ "$match_count" -gt 1 ]; then
    log -l WARN "push_mirror: ${match_count} duplicaten voor ${owner}/${repo} — alle weghalen + recreate"
  fi

  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: zou DELETE (${match_count}x) + POST push_mirror doen voor ${owner}/${repo}"
    return 0
  fi

  # DELETE per remote_name (Forgejo's identifier voor push_mirror endpoints — er is geen .id field).
  names_to_delete=$(printf '%s' "$matches" | jq -r '.[].remote_name')
  if [ -n "$names_to_delete" ]; then
    local rn
    while IFS= read -r rn; do
      [ -z "$rn" ] && continue
      local code; code=$(fj_code DELETE "/repos/${owner}/${repo}/push_mirrors/${rn}")
      [ "$code" = "204" ] || log -l WARN "DELETE push_mirror ${rn} → HTTP $code"
    done <<<"$names_to_delete"
  fi

  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: zou POST /push_mirrors doen voor ${owner}/${repo} (remote=$remote interval=$interval branch_filter=$branch)"
    return 0
  fi

  local payload
  payload=$(jq -n \
    --arg ra "$remote" --arg user "$GH_USERNAME" --arg pw "$GH_TOKEN" \
    --arg int "$interval" --arg bf "$branch" \
    '{remote_address:$ra, remote_username:$user, remote_password:$pw,
      interval:$int, sync_on_commit:false, branch_filter:$bf}')
  fj POST "/repos/${owner}/${repo}/push_mirrors" "$payload" >/dev/null || return 1
  log "push_mirror aangemaakt voor ${owner}/${repo}"
}

# ─────────────────────── sync trigger + poll ────────────────────────

trigger_sync() {
  local owner="$1" repo="$2"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: zou push_mirrors-sync triggeren voor ${owner}/${repo}"
    return 0
  fi
  local code attempt=1
  while [ $attempt -le 3 ]; do
    code=$(fj_code POST "/repos/${owner}/${repo}/push_mirrors-sync")
    case "$code" in
      200|204) log "sync getriggerd voor ${owner}/${repo}"; return 0 ;;
    esac
    log -l WARN "trigger_sync ${owner}/${repo} attempt=$attempt http=$code; backoff"
    sleep $((2 ** attempt))
    attempt=$((attempt + 1))
  done
  return 1
}

poll_sync_completion() {
  local owner="$1" repo="$2" max="${3:-60}"
  [ "${DRY_RUN:-0}" = "1" ] && return 0
  local started end body last
  started=$(date +%s)
  end=$((started + max))
  while [ "$(date +%s)" -lt "$end" ]; do
    body=$(fj GET "/repos/${owner}/${repo}/push_mirrors") || return 1
    last=$(printf '%s' "$body" | jq -r '[.[].last_update] | max // ""')
    if [ -n "$last" ] && [ "$last" != "null" ]; then
      # Forgejo zet last_update bij succesvolle sync; controleer dat 'ie na 'started' is
      local ts; ts=$(date -d "$last" +%s 2>/dev/null || echo 0)
      if [ "$ts" -ge "$started" ]; then
        log "sync klaar voor ${owner}/${repo} (last_update=$last)"
        return 0
      fi
    fi
    sleep 3
  done
  return 1
}

# ─────────────────────────── verificatie ────────────────────────────

verify_sha() {
  local owner="$1" repo="$2" branch="$3" fjsha ghsha
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: skip verify_sha ${owner}/${repo}@${branch} (geen echte push gedaan)"
    return 0
  fi
  fjsha=$(fj GET "/repos/${owner}/${repo}/branches/${branch}" \
    | jq -r '.commit.id // ""')
  ghsha=$(gh GET "/repos/${GH_USERNAME}/${repo}/commits/${branch}" \
    | jq -r '.sha // ""')
  if [ -z "$fjsha" ] || [ -z "$ghsha" ]; then
    log -l ERROR "verify_sha ${owner}/${repo}: lege SHA (fj='$fjsha' gh='$ghsha')"
    return 1
  fi
  if [ "$fjsha" = "$ghsha" ]; then
    log "SHA-match ${owner}/${repo}@${branch}: $fjsha"
    return 0
  fi
  log -l ERROR "SHA-mismatch ${owner}/${repo}@${branch}: forgejo=$fjsha github=$ghsha"
  return 1
}

verify_tags() {
  local owner="$1" repo="$2" fjtags ghtags
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: skip verify_tags ${owner}/${repo}"
    return 0
  fi
  fjtags=$(fj GET "/repos/${owner}/${repo}/tags" | jq -r '[.[].name] | sort | join(",")')
  ghtags=$(gh GET "/repos/${GH_USERNAME}/${repo}/tags" | jq -r '[.[].name] | sort | join(",")')
  if [ "$fjtags" = "$ghtags" ]; then
    log "tags-match ${owner}/${repo} ($(echo "$fjtags" | tr ',' '\n' | wc -l) tags)"
    return 0
  fi
  log -l WARN "tags-mismatch ${owner}/${repo}: forgejo=[$fjtags] github=[$ghtags]"
  return 1
}

# ─────────────────────── tags-fallback (T-1080) ─────────────────────

# Bare-clone lokaal + git push --tags --force naar GitHub. Vereist dat
# git op host het kan; geen Forgejo-API nodig.
tags_fallback() {
  local owner="$1" repo="$2"
  local _repo_token; _repo_token=$(gh_token_for_repo "$repo")  # resolve VÓÓR de local-shadow
  local GH_TOKEN="$_repo_token"
  local clonedir="${MIRROR_CLONE_DIR:-/srv/scrum4me/repos/mirrors}/${owner}-${repo}.git"
  mkdir -p "$(dirname "$clonedir")"
  if [ ! -d "$clonedir" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      log "DRY_RUN: zou bare-clone $clonedir aanmaken vanaf Forgejo"
      return 0
    fi
    log "bare-clonen ${owner}/${repo} → $clonedir"
    git clone --bare --quiet \
      "https://${FORGEJO_USERNAME}:${FORGEJO_TOKEN}@${FORGEJO_BASE_URL#https://}/${owner}/${repo}.git" \
      "$clonedir" || return 1
  else
    if [ "${DRY_RUN:-0}" = "1" ]; then
      log "DRY_RUN: zou git fetch in $clonedir doen"
      return 0
    fi
    log "git fetch in $clonedir"
    git -C "$clonedir" fetch --tags --quiet origin '+refs/heads/*:refs/heads/*' || return 1
  fi
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: zou git push --tags --force naar GitHub doen voor ${owner}/${repo}"
    return 0
  fi
  git -C "$clonedir" push --tags --force --quiet \
    "https://${GH_USERNAME}:${GH_TOKEN}@github.com/${GH_USERNAME}/${repo}.git" || return 1
  log "tags-fallback OK voor ${owner}/${repo}"
}

# ─────────────────────────── state-file ─────────────────────────────

update_state() {
  local key="$1" ts="$2"
  local sf="${STATE_FILE:-/var/lib/forgejo-mirror/state.json}"
  local dir; dir=$(dirname "$sf")
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || true
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN: zou state-file updaten ($key → $ts)"
    return 0
  fi
  local cur tmp
  cur=$( [ -f "$sf" ] && cat "$sf" || echo '{}' )
  tmp=$(mktemp)
  printf '%s' "$cur" | jq --arg k "$key" --arg t "$ts" '.[$k] = $t' > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$sf"
}
