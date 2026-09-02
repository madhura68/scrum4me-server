#!/usr/bin/env bash
# forgejo-runner/scripts/verify-stack.sh
# Verifieert de uitgerolde stack op deze host (§6.1, §7.5, §7.6).
# Exit 0 groen, 60 commit-drift, 61 bundelhash-drift, 62 isolatiefout,
# 2 gebruiksfout.
#
# BUNDLE_COMMIT_FILE is overschrijfbaar zodat de faaltakken zonder host
# getest kunnen worden; op de hosts is het /opt/forgejo-runner/BUNDLE_COMMIT.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$SCRIPT_DIR/.."
BUNDLE_COMMIT_FILE="${BUNDLE_COMMIT_FILE:-/opt/forgejo-runner/BUNDLE_COMMIT}"
VERWACHT_COMMIT="${1:-}"
VERWACHTE_HASH="${2:-}"
[ -n "$VERWACHT_COMMIT" ] && [ -n "$VERWACHTE_HASH" ] || {
  printf 'gebruik: verify-stack.sh COMMIT_SHA BUNDEL_HASH\n' >&2 ; exit 2 ; }

HUIDIG_COMMIT="$(cat "$BUNDLE_COMMIT_FILE" 2>/dev/null || true)"
[ -n "$HUIDIG_COMMIT" ] || { printf 'BUNDLE_COMMIT ontbreekt: %s\n' "$BUNDLE_COMMIT_FILE" >&2 ; exit 60 ; }
[ "$HUIDIG_COMMIT" = "$VERWACHT_COMMIT" ] || {
  printf 'commit-drift: host %s, verwacht %s\n' "$HUIDIG_COMMIT" "$VERWACHT_COMMIT" >&2 ; exit 60 ; }

HUIDIGE_HASH="$(bash "$SCRIPT_DIR/bundle-hash.sh" "$BUNDLE")"
[ "$HUIDIGE_HASH" = "$VERWACHTE_HASH" ] || {
  printf 'bundelhash-drift: host %s, verwacht %s\n' "$HUIDIGE_HASH" "$VERWACHTE_HASH" >&2 ; exit 61 ; }

# Isolatie: geen hostlistener op de Docker-API-poorten (§7.5). Het patroon
# eist een poortgrens, zodat 23750 niet als 2375 telt.
if ss -ltn 2>/dev/null | grep -qE ':(2375|2376)([^0-9]|$)'; then
  printf 'isolatiefout: er luistert iets op 2375 of 2376\n' >&2 ; exit 62
fi

printf 'commit: %s\nbundel_hash: %s\nisolatie: OK\n' "$HUIDIG_COMMIT" "$HUIDIGE_HASH"
