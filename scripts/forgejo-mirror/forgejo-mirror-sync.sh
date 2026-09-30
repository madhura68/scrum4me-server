#!/usr/bin/env bash
# forgejo-mirror-sync.sh — nightly mirror van Forgejo → GitHub.
#
# Per repo: skip als .github/workflows aanwezig is (PAT mist Workflows-scope,
# zie T-1077). Anders: counterpart-check (T-1077-deviation: handmatig pre-
# aangemaakt), push_mirror ensure (T-1078 + T-1080 features), trigger-sync,
# poll, SHA/tags-verify, eventueel tags-fallback (T-1080), state-update.
#
# Env-files (verplicht):
#   /etc/forgejo-mirror/forgejo.env
#   /etc/forgejo-mirror/github.env
#
# Env-overrides:
#   DRY_RUN=1                  alleen GET's; geen POST/DELETE/PATCH
#   LOCK_FILE=<pad>            default /var/lock/forgejo-mirror-sync.lock
#   STATE_FILE=<pad>           default /var/lib/forgejo-mirror/state.json
#   MIRROR_CLONE_DIR=<pad>     default /srv/scrum4me/repos/mirrors
#   MIRROR_INTERVAL=<dur>      default 24h  (Forgejo push_mirror interval)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=forgejo-mirror-lib.sh
source "$SCRIPT_DIR/forgejo-mirror-lib.sh"

ENV_FORGEJO="${ENV_FORGEJO:-/etc/forgejo-mirror/forgejo.env}"
ENV_GITHUB="${ENV_GITHUB:-/etc/forgejo-mirror/github.env}"
LOCK_FILE="${LOCK_FILE:-/var/lock/forgejo-mirror-sync.lock}"

load_env() {
  [ -r "$ENV_FORGEJO" ] || die "kan $ENV_FORGEJO niet lezen (perms? sudo?)"
  [ -r "$ENV_GITHUB" ]  || die "kan $ENV_GITHUB niet lezen (perms? sudo?)"
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FORGEJO"
  # shellcheck source=/dev/null
  . "$ENV_GITHUB"
  set +a
  : "${FORGEJO_BASE_URL:?FORGEJO_BASE_URL niet gezet}"
  : "${FORGEJO_USERNAME:?FORGEJO_USERNAME niet gezet}"
  : "${FORGEJO_TOKEN:?FORGEJO_TOKEN niet gezet}"
  : "${GH_API_URL:?GH_API_URL niet gezet}"
  : "${GH_USERNAME:?GH_USERNAME niet gezet}"
  : "${GH_TOKEN:?GH_TOKEN niet gezet}"
}

run() {
  load_env
  preflight

  local repos
  repos=$(enumerate_repos)
  [ -n "$repos" ] || { log "geen repos gevonden voor $FORGEJO_USERNAME"; return 0; }

  # Optioneel: filter op één enkele repo-naam voor testing (REPOS_FILTER=foo)
  if [ -n "${REPOS_FILTER:-}" ]; then
    log "REPOS_FILTER actief: alleen repo '$REPOS_FILTER'"
    repos=$(printf '%s' "$repos" | jq -c --arg f "$REPOS_FILTER" 'select(.name == $f)')
    [ -n "$repos" ] || die "REPOS_FILTER='$REPOS_FILTER' matched geen enkele repo"
  fi

  local total=0 mirrored=0 skipped_wf=0 skipped_other=0 errors=0
  local repo_json owner repo default_branch wf repo_token

  while IFS= read -r repo_json; do
    [ -z "$repo_json" ] && continue
    total=$((total + 1))
    owner=$(printf '%s' "$repo_json" | jq -r '.owner.login')
    repo=$(printf '%s'  "$repo_json" | jq -r '.name')
    default_branch=$(printf '%s' "$repo_json" | jq -r '.default_branch')

    log "─── ${owner}/${repo} (branch=${default_branch}) ───"

    # Ongeldige repo-naam (geen geldige GH_TOKEN_<REPO>-variabelenaam): alleen deze repo weigeren.
    repo_token=$(gh_token_for_repo "$repo") || { errors=$((errors + 1)); continue; }

    wf=0; has_workflows "$owner" "$repo" || wf=$?
    if [ "$wf" -ge 2 ]; then
      errors=$((errors + 1)); continue
    fi
    if [ "$wf" -eq 0 ]; then
      if [ "$repo_token" = "$GH_TOKEN" ]; then
        log "SKIP ${owner}/${repo}: bevat .github/workflows (default PAT mist Workflows-scope; zet GH_TOKEN_$(printf '%s' "$repo" | tr '[:lower:]-' '[:upper:]_') om dit te overrulen)"
        skipped_wf=$((skipped_wf + 1)); continue
      fi
      log "${owner}/${repo}: workflows aanwezig, override-token actief"
    fi

    if ! ensure_github_counterpart "$owner" "$repo"; then
      skipped_other=$((skipped_other + 1)); continue
    fi
    if ! ensure_github_default_branch "$owner" "$repo" "$default_branch"; then
      errors=$((errors + 1)); continue
    fi
    if ! ensure_push_mirror "$owner" "$repo" "$default_branch"; then
      errors=$((errors + 1)); continue
    fi
    if ! trigger_sync "$owner" "$repo"; then
      errors=$((errors + 1)); continue
    fi
    if ! poll_sync_completion "$owner" "$repo" 60; then
      log -l WARN "poll-timeout op ${owner}/${repo} (sync wellicht nog bezig)"
    fi

    if verify_sha "$owner" "$repo" "$default_branch"; then
      if ! verify_tags "$owner" "$repo"; then
        if ! tags_fallback "$owner" "$repo"; then
          errors=$((errors + 1)); continue
        fi
      fi
      mirrored=$((mirrored + 1))
      # State is informatief (niets leest state.json): een schrijffout mag de run niet afbreken.
      update_state "${owner}/${repo}" "$(date -u +%FT%TZ)" \
        || { log -l WARN "state-update voor ${owner}/${repo} mislukt (${STATE_FILE:-/var/lib/forgejo-mirror/state.json})"; errors=$((errors + 1)); }
    else
      errors=$((errors + 1))
    fi
  done <<<"$repos"

  log "Summary: total=$total mirrored=$mirrored skipped_workflow=$skipped_wf skipped_other=$skipped_other errors=$errors"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN-noot: 'mirrored' = aantal repos die de happy path zouden doorlopen; verify_sha/verify_tags zijn in DRY_RUN niet bewijzend."
  fi
  [ "$errors" -eq 0 ]
}

main() {
  # flock voorkomt dubbele uitvoer (timer + handmatige systemctl start).
  # Gebruikt fd 9, file zelf bevat geen state.
  local lock_dir; lock_dir=$(dirname "$LOCK_FILE")
  [ -d "$lock_dir" ] || mkdir -p "$lock_dir" 2>/dev/null || true
  exec 9>"$LOCK_FILE" || die "kan $LOCK_FILE niet openen"
  if ! flock -n 9; then
    die "andere instantie draait al (flock $LOCK_FILE)"
  fi

  [ "${DRY_RUN:-0}" = "1" ] && log "── DRY_RUN modus actief: geen mutating calls ──"

  run
}

main "$@"
