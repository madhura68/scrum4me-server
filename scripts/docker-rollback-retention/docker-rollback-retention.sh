#!/usr/bin/env bash
#
# docker-rollback-retention.sh - keep the N newest rollback tags per image
#                                repository; list or remove the older ones.
#
# Why this exists: deploys keep `<repo>:rollback-*` (and `idea-rollback-*`)
# tags so a bad rollout can be reverted. They pile up (10+ per image, ~2.4 GB
# each) and show as "reclaimable" in `docker system df`, which invited
# `docker image prune -a` -- that would drop every rollback tag at once. This
# script only ever untags rollback tags beyond the newest N per repository and
# never touches an image a container (running or stopped) still uses.
#
# Usage: docker-rollback-retention.sh [--dry-run|--apply] [--keep N]
#   default --dry-run, --keep 2. Removal is `docker rmi <repo:tag>` without -f:
#   an image with other tags is only untagged; a refusal is reported, not forced.

set -euo pipefail

mode=dry-run keep=2
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) mode=dry-run ;;
    --apply) mode=apply ;;
    --keep) keep="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "$keep" =~ ^[0-9]+$ ]] || { echo "--keep needs a number" >&2; exit 2; }

die() { echo "docker-rollback-retention: $*" >&2; exit 1; }

# Enumeration fails closed: output is captured with its exit status checked,
# because a failure inside a process substitution never reaches this shell and
# would silently yield an empty in-use set or zero rows.

# Image IDs referenced by any container, running or stopped.
declare -A in_use=()
container_ids=$(docker ps -aq) || die "docker ps failed; refusing to continue"
if [ -n "$container_ids" ]; then
  cids=()
  while IFS= read -r cid; do [ -n "$cid" ] && cids+=("$cid"); done <<<"$container_ids"
  used_ids=$(docker inspect --format '{{.Image}}' "${cids[@]}") ||
    die "docker inspect failed; in-use set unknown, refusing to continue"
  while IFS= read -r id; do [ -n "$id" ] && in_use["$id"]=1; done <<<"$used_ids"
fi

# repo <TAB> tag <TAB> full id <TAB> created (sortable), rollback tags only
all_images=$(docker images --no-trunc --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}') ||
  die "docker images failed; refusing to continue"
rows=$(printf '%s\n' "$all_images" |
  awk -F'\t' '$2 ~ /^(idea-)?rollback-/' | sort -t$'\t' -k1,1 -k4,4r)

printf '%-7s %-28s %-48s %-12s %s\n' ACTION REPOSITORY TAG SIZE CREATED
removed=0 kept=0 skipped=0 failed=0 prev_repo="" n=0
while IFS= read -r row; do
  [ -n "$row" ] || continue
  IFS=$'\t' read -r repo tag id created <<<"$row"
  [ "$repo" = "$prev_repo" ] || { prev_repo=$repo; n=0; }
  n=$((n + 1))
  size=$(docker image inspect --format '{{.Size}}' "$id" 2>/dev/null | awk '{printf "%.2fGB", $1/1e9}') || size='?'
  [ -n "$size" ] || size='?'
  if [ "$n" -le "$keep" ]; then
    action=keep; kept=$((kept + 1))
  elif [ -n "${in_use[$id]:-}" ]; then
    action=in-use; skipped=$((skipped + 1))
  elif [ "$mode" = apply ]; then
    if docker rmi "$repo:$tag" >/dev/null 2>&1; then action=removed; removed=$((removed + 1))
    else action=refused; failed=$((failed + 1)); fi
  else
    action=remove; removed=$((removed + 1))
  fi
  printf '%-7s %-28s %-48s %-12s %s\n' "$action" "$repo" "$tag" "$size" "${created%% +*}"
done <<<"$rows"
echo "mode=$mode keep=$keep kept=$kept in_use=$skipped $([ "$mode" = apply ] && echo removed || echo would_remove)=$removed refused=$failed"
