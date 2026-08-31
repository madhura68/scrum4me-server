#!/usr/bin/env bash
# forgejo-runner/scripts/capture-clock-skew.sh
# Legt tijdsynchronisatie en wandklokskew vast. Read-only.
# Deze meting is uitsluitend audit/corroboratie; event_seq blijft de enige
# voor/na-fencebeslisser volgens 7.7 van het migratieontwerp.
set -euo pipefail

HOSTNAME_LABEL="" ; URL="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOSTNAME_LABEL="$2" ; shift 2 ;;
    --url)  URL="$2"            ; shift 2 ;;
    --out)  OUT="$2"            ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$HOSTNAME_LABEL" ] && [ -n "$URL" ] && [ -n "$OUT" ] || {
  printf 'gebruik: --host NAAM --url URL --out MAP\n' >&2 ; exit 2 ; }

mkdir -p "$OUT"
DEST="$OUT/clock-$HOSTNAME_LABEL.txt"

{
  printf 'host\t%s\n' "$HOSTNAME_LABEL"
  printf 'doel\taudit en corroboratie; event_seq blijft de enige voor/na-fencebeslisser (7.7)\n'
  printf '\n## timedatectl\n'
  timedatectl 2>&1 || printf 'timedatectl niet beschikbaar\n'
  printf '\n## chrony\n'
  if command -v chronyc >/dev/null 2>&1; then chronyc tracking 2>&1; else printf 'chronyc niet aanwezig\n'; fi
  printf '\n## skew tegen de Forgejo Date-header\n'
} > "$DEST"

LOCAL_BEFORE_MS="$(python3 -c 'import time;print(int(time.time()*1000))')"
REMOTE_DATE="$(curl --silent --show-error --head --max-time 20 "$URL" 2>/dev/null \
  | tr '[:upper:]' '[:lower:]' | awk -F': ' '/^date: /{print $2; exit}')"
LOCAL_AFTER_MS="$(python3 -c 'import time;print(int(time.time()*1000))')"

if [ -z "$REMOTE_DATE" ]; then
  printf 'skew_ms\tONBEKEND — geen Date-header ontvangen\n' >> "$DEST"
else
  python3 - "$REMOTE_DATE" "$LOCAL_BEFORE_MS" "$LOCAL_AFTER_MS" >> "$DEST" <<'PY'
import sys
from email.utils import parsedate_to_datetime
remote, before, after = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
remote_ms = int(parsedate_to_datetime(remote).timestamp() * 1000)
midpoint = (before + after) // 2
print("remote_date\t%s" % remote)
print("lokaal_midden_ms\t%d" % midpoint)
print("rondreis_ms\t%d" % (after - before))
print("skew_ms\t%d" % (midpoint - remote_ms))
print("let_op\tde Date-header heeft secondeprecisie; een skew onder 1000 ms is niet betekenisvol")
PY
fi

printf 'klokbewijs geschreven naar %s\n' "$DEST"
