#!/usr/bin/env bash
# forgejo-runner/scripts/capture-forgejo-records.sh
# Read-only inventarisatie van Forgejo-runnerrecords. Draait op mac.
# Het token gaat via curl --config zodat het niet in argv of shellhistory staat.
set -euo pipefail

FORGEJO_URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
SCOPE="global" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2" ; shift 2 ;;
    --out)   OUT="$2"   ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { printf 'gebruik: --scope global|org:NAAM|repo:OWNER/NAAM --out MAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt in de omgeving\n' >&2 ; exit 3 ; }

case "$SCOPE" in
  global)   PATH_SEG="/api/v1/admin/actions/runners" ; SLUG="global" ;;
  org:*)    PATH_SEG="/api/v1/orgs/${SCOPE#org:}/actions/runners" ; SLUG="org-${SCOPE#org:}" ;;
  repo:*)   PATH_SEG="/api/v1/repos/${SCOPE#repo:}/actions/runners" ; SLUG="repo-$(printf '%s' "${SCOPE#repo:}" | tr '/' '-')" ;;
  *) printf 'onbekende scope: %s\n' "$SCOPE" >&2 ; exit 2 ;;
esac

mkdir -p "$OUT"
RAW="$OUT/runners-$SLUG.json"

curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
     --silent --show-error --fail-with-body --max-time 30 \
     "$FORGEJO_URL$PATH_SEG" > "$RAW"

SUMMARY="$OUT/runners-summary.tsv"
# version is een bevestigd ActionRunner-veld en is nodig voor het stap-A-bewijs
# dat er een online runner met versie 12.x draait; het staat daarom in de samenvatting.
[ -f "$SUMMARY" ] || printf 'scope\tid\tuuid\tname\tstatus\tversion\tephemeral\towner_id\trepo_id\tlabels\n' > "$SUMMARY"

python3 - "$RAW" "$SCOPE" >> "$SUMMARY" <<'PY'
import json, sys
raw, scope = sys.argv[1], sys.argv[2]
data = json.load(open(raw))
records = data if isinstance(data, list) else data.get("runners", [])
for r in records:
    print("\t".join([
        scope,
        str(r.get("id", "")),
        str(r.get("uuid", "")),
        str(r.get("name", "")),
        str(r.get("status", "")),
        str(r.get("version", "")),
        str(r.get("ephemeral", "")),
        str(r.get("owner_id", "")),
        str(r.get("repo_id", "")),
        ",".join(r.get("labels") or []),
    ]))
PY

printf 'records voor scope %s geschreven naar %s\n' "$SCOPE" "$OUT"
