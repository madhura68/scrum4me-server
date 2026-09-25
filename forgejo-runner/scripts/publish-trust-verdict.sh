#!/bin/sh
# forgejo-runner/scripts/publish-trust-verdict.sh
# Deploy-wrapper (§6.3). Draait de trustgate-CLI met FORGEJO_URL=<target> in een
# verse out-dir; publiceert een controller-verdict met measured_at + binding aan
# de WERKELIJK gemeten target ALLEEN bij geldige CLI-exit 0 of soft-only exit 10. Bij CLI-falen wordt het
# actieve verdict fail-closed geïnvalideerd (ok=false) → controllergate rood.
# Exit: 0 gepubliceerd, 3 meting mislukt, 2 gebruik.
set -eu

CLI_PY=""; LABELS=""; ALLOWLIST=""; TARGET=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cli-py) CLI_PY="$2"; shift 2;; --labels) LABELS="$2"; shift 2;;
    --allowlist) ALLOWLIST="$2"; shift 2;; --target) TARGET="$2"; shift 2;;
    --out) OUT="$2"; shift 2;; *) echo "onbekend: $1" >&2; exit 2;;
  esac
done
[ -n "$CLI_PY" ] && [ -n "$LABELS" ] && [ -n "$ALLOWLIST" ] && [ -n "$TARGET" ] && [ -n "$OUT" ] || {
  echo "gebruik: --cli-py P --labels L --allowlist A --target T --out O" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
# De CLI meet de bron uit FORGEJO_URL (trust_scope_cli.py); bind het verdict daaraan.
CLI_RC=0
if [ -f "$LABELS" ] && [ -r "$LABELS" ] && [ -f "$ALLOWLIST" ] && [ -r "$ALLOWLIST" ]; then
  FORGEJO_URL="$TARGET" python3 "$CLI_PY" --allowlist "$ALLOWLIST" --labels "$LABELS" --out "$WORK" || CLI_RC=$?
else
  CLI_RC=30
  echo "trustmeting mislukt: labels/allowlist ontbreken of zijn geen leesbare reguliere bestanden" >&2
fi
PUB_RC=0
python3 - "$WORK/trust-verdict.json" "$CLI_RC" "$LABELS" "$ALLOWLIST" "$TARGET" "$OUT" <<'PY' || PUB_RC=$?
import hashlib
import json
import os
from pathlib import Path
import sys
import time

source, rc, labels, allowlist, target, output = sys.argv[1:]
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("dubbele JSON-key")
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError("ongeldige JSON-constante")

doc = {"ok": False, "measured_at": int(time.time()), "forgejo_target": target}
try:
    if rc not in ("0", "10"):
        raise ValueError("CLI-exit " + rc)
    verdict = json.loads(Path(source).read_text(encoding="utf-8"),
                         object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(verdict, dict) or verdict.get("ok") is not True:
        raise ValueError("ongeldig ok-veld")
    for key in ("hard", "unreadable", "soft"):
        value = verdict.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ongeldige lijst: " + key)
    if verdict["hard"] or verdict["unreadable"] or bool(verdict["soft"]) != (rc == "10"):
        raise ValueError("exitcode en resultaat spreken elkaar tegen")
    doc["labels_sha256"] = hashlib.sha256(Path(labels).read_bytes()).hexdigest()
    doc["allowlist_sha256"] = hashlib.sha256(Path(allowlist).read_bytes()).hexdigest()
    doc["ok"] = True
except (OSError, ValueError, RecursionError) as exc:
    doc["reason"] = "meting mislukt"
    print("trustmeting mislukt; actief verdict wordt geïnvalideerd: " + str(exc), file=sys.stderr)

tmp = Path(output + ".tmp." + str(os.getpid()))
try:
    tmp.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, output)
except OSError as exc:
    print("verdictpublicatie mislukt: " + str(exc), file=sys.stderr)
    sys.exit(3)
if doc["ok"] and rc == "10":
    print("trustmeting groen met zachte afwijkingen; binnen 24 uur beoordelen", file=sys.stderr)
sys.exit(0 if doc["ok"] else 3)
PY
if [ "$PUB_RC" -ne 0 ]; then
  # Ook als python3 zelf uitvalt moet oud groen verdwijnen. Bij normale exit3
  # is dit een tweede, veilige rode vervanging; de detailreden staat in stderr.
  ITMP="$OUT.tmp.$$"
  if printf '{"ok":false,"measured_at":%s,"reason":"meting of publicatie mislukt"}\n' \
    "$(date +%s)" > "$ITMP" && mv -f "$ITMP" "$OUT"; then
    echo "trustmeting/publicatie mislukt; actief verdict geïnvalideerd" >&2
  else
    echo "FOUT: actief verdict kon niet worden geïnvalideerd" >&2
  fi
  exit 3
fi
