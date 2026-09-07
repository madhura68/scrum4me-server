#!/bin/sh
# forgejo-runner/scripts/publish-trust-verdict.sh
# Deploy-wrapper (§6.3). Draait de trustgate-CLI met FORGEJO_URL=<target> in een
# verse out-dir; publiceert een controller-verdict met measured_at + binding aan
# de WERKELIJK gemeten target ALLEEN bij CLI-exit 0. Bij CLI-falen wordt het
# actieve verdict fail-closed geïnvalideerd (ok=false) → controllergate rood.
# Exit: 0 gepubliceerd, 3 meting mislukt, 2 gebruik.
set -eu

hashtool() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo "geen sha256-tool" >&2; exit 2; fi
}

CLI_PY=""; LABELS=""; ALLOWLIST=""; TARGET=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cli-py) CLI_PY="$2"; shift 2;; --labels) LABELS="$2"; shift 2;;
    --allowlist) ALLOWLIST="$2"; shift 2;; --target) TARGET="$2"; shift 2;;
    --out) OUT="$2"; shift 2;; *) echo "onbekend: $1" >&2; exit 2;;
  esac
done
[ -n "$CLI_PY" ] && [ -f "$LABELS" ] && [ -f "$ALLOWLIST" ] && [ -n "$TARGET" ] && [ -n "$OUT" ] || {
  echo "gebruik: --cli-py P --labels L --allowlist A --target T --out O" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
# De CLI meet de bron uit FORGEJO_URL (trust_scope_cli.py); bind het verdict daaraan.
if ! FORGEJO_URL="$TARGET" python3 "$CLI_PY" --allowlist "$ALLOWLIST" --labels "$LABELS" --out "$WORK"; then
  # M1/§6.3: een mislukte hernieuwde validatie mag oud groen niet laten gelden.
  # Invalideer het actieve verdict fail-closed (ok=false) zodat de controllergate rood wordt.
  ITMP="$OUT.tmp.$$"
  printf '{"ok":false,"measured_at":%s,"forgejo_target":"%s","reason":"meting mislukt"}\n' \
    "$(date +%s)" "$TARGET" > "$ITMP"; mv -f "$ITMP" "$OUT"
  echo "trustmeting mislukt; actief verdict geïnvalideerd (ok=false)" >&2; exit 3
fi
OKVAL="$(grep -o '"ok"[[:space:]]*:[[:space:]]*\(true\|false\)' "$WORK/trust-verdict.json" | grep -o 'true\|false' | head -1)"
LS="$(hashtool "$LABELS")"; AS="$(hashtool "$ALLOWLIST")"
TMP="$OUT.tmp.$$"
printf '{"ok":%s,"measured_at":%s,"forgejo_target":"%s","labels_sha256":"%s","allowlist_sha256":"%s"}\n' \
  "${OKVAL:-false}" "$(date +%s)" "$TARGET" "$LS" "$AS" > "$TMP"
mv -f "$TMP" "$OUT"
