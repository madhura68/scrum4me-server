#!/usr/bin/env bash
# forgejo-runner/scripts/bundle-hash.sh
# Canonieke hash over de bundelbestanden (§6.1). Pad en inhoud tellen allebei
# mee, zodat een hernoeming de hash verandert.
#
# Buiten de hash blijft alles wat hostlokaal is en dus op de twee hosts mág
# afwijken zonder dat de bundel afwijkt: .env, de gerenderde runner-config.yml
# (draagt de per-host UUID), BUNDLE_COMMIT (het uitrolrecord), controller.toml,
# credentials/ en Python-bytecode. tests/ draait niet mee op de hosts.
set -euo pipefail

BUNDLE="${1:-}"
[ -d "$BUNDLE" ] || { printf 'gebruik: bundle-hash.sh BUNDELMAP\n' >&2 ; exit 2 ; }

# Ubuntu levert sha256sum, mac shasum. Gemeten 2026-08-31: shasum bestaat op
# beide hosts en op mac, en beide commando's geven dezelfde uitvoerindeling.
# De detectie is dus geen aanname over een ontbrekend commando maar een
# garantie dat mac en host dezelfde hash produceren.
if command -v sha256sum >/dev/null 2>&1; then
  HASHER=(sha256sum)
else
  HASHER=(shasum -a 256)
fi

cd "$BUNDLE"
find . -type f \
  ! -name '.env' \
  ! -name 'runner-config.yml' \
  ! -name 'BUNDLE_COMMIT' \
  ! -name 'controller.toml' \
  ! -name '*.pyc' \
  ! -path './tests/*' \
  ! -path './credentials/*' \
  ! -path '*/__pycache__/*' \
  -print0 \
  | LC_ALL=C sort -z \
  | while IFS= read -r -d '' pad; do
      printf '%s\0' "$pad"
      cat "$pad"
      printf '\0'
    done \
  | "${HASHER[@]}" \
  | awk '{print $1}'
