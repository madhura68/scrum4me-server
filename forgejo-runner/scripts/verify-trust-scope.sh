#!/usr/bin/env bash
# forgejo-runner/scripts/verify-trust-scope.sh
# Entry point van de trustscope-gate (7.7). De logica staat in trust_scope.py.
# Exit 0 groen, 10 zachte afwijking, 20 harde afwijking, 30 onleesbaar.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOWLIST="${ALLOWLIST:-$SCRIPT_DIR/../trusted-actions-scope.yml}"
LABELS="${LABELS:-$SCRIPT_DIR/../labels.txt}"
OUT="${1:-}"
[ -n "$OUT" ] || { printf 'gebruik: verify-trust-scope.sh UITVOERMAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt\n' >&2 ; exit 30 ; }

mkdir -p "$OUT"
exec python3 "$SCRIPT_DIR/trust_scope_cli.py" --allowlist "$ALLOWLIST" \
  --labels "$LABELS" --out "$OUT"
