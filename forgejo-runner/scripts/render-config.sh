#!/usr/bin/env bash
# forgejo-runner/scripts/render-config.sh
# Bouwt de hostconfig uit de gedeelde policy, het canonieke labelblok en de
# hostspecifieke UUID. Schrijft nooit een tokenwaarde: §6 legt het token in een
# apart bestand dat via token_url wordt gelezen.
#
# Exitcodes: 2 gebruiksfout, 3 lege labellijst, 4 label zonder digest,
# 5 UUID niet in UUID-vorm.
set -euo pipefail

UUID="" ; LABELS="" ; POLICY="" ; OUT="" ; URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
while [ $# -gt 0 ]; do
  case "$1" in
    --uuid)   UUID="$2"   ; shift 2 ;;
    --labels) LABELS="$2" ; shift 2 ;;
    --policy) POLICY="$2" ; shift 2 ;;
    --out)    OUT="$2"    ; shift 2 ;;
    --url)    URL="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$UUID" ] && [ -n "$LABELS" ] && [ -n "$POLICY" ] && [ -n "$OUT" ] || {
  printf 'gebruik: --uuid UUID --labels BESTAND --policy BESTAND --out BESTAND [--url URL]\n' >&2 ; exit 2 ; }
[ -f "$LABELS" ] && [ -f "$POLICY" ] || { printf 'labels- of policybestand ontbreekt\n' >&2 ; exit 2 ; }

# Een verschreven UUID faalt anders pas op de host als CREDENTIAL_ERROR.
[[ "$UUID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || {
  printf 'uuid heeft niet de UUID-vorm: %s\n' "$UUID" >&2 ; exit 5 ; }

# Alleen regels die een label zijn; commentaar en lege regels tellen niet.
labels() { grep -vE '^[[:space:]]*(#|$)' "$LABELS" || true ; }

# §7.4: een lege lijst of een mutabele tag zonder digest is een harde fout.
[ -n "$(labels)" ] || { printf 'labellijst is leeg: %s\n' "$LABELS" >&2 ; exit 3 ; }
while read -r regel; do
  case "$regel" in
    *@sha256:*) : ;;
    *) printf 'label zonder digest: %s\n' "$regel" >&2 ; exit 4 ;;
  esac
done < <(labels)

{
  cat "$POLICY"
  printf '\nserver:\n  connections:\n    forgejo:\n'
  printf '      url: %s\n' "$URL"
  printf '      uuid: %s\n' "$UUID"
  printf '      token_url: file:/run/forgejo-runner-credentials/forgejo-token\n'
  printf '      labels:\n'
  while read -r regel; do
    printf '        - %s\n' "$regel"
  done < <(labels)
} > "$OUT"

printf 'config gerenderd naar %s\n' "$OUT"
