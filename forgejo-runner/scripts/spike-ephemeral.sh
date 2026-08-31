#!/usr/bin/env bash
# forgejo-runner/scripts/spike-ephemeral.sh
# Meet of ephemeral runnerregistratie werkt op deze Forgejo-instance.
# Maakt exact een record aan met een canary-label en verwijdert het weer.
# Start nooit een runnerproces en raakt de bestaande runner niet aan.
#
# De printf-formaatstrings bevatten bewust letterlijke markdown-backticks (`...`);
# die horen niet te expanderen, dus single quotes zijn correct. SC2016 hierover is
# een false positive voor dit hele script.
# shellcheck disable=SC2016
set -euo pipefail

FORGEJO_URL="${FORGEJO_URL:-https://git.jp-visser.nl}"
LABEL="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$2" ; shift 2 ;;
    --out)   OUT="$2"   ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$LABEL" ] && [ -n "$OUT" ] || { printf 'gebruik: --label ephemeral-spike-<datum> --out MAP\n' >&2 ; exit 2 ; }
[ -n "${FORGEJO_TOKEN:-}" ] || { printf 'FORGEJO_TOKEN ontbreekt\n' >&2 ; exit 3 ; }

# Veiligheidskader 1: alleen een canary-label, nooit een productielabel.
case "$LABEL" in
  ephemeral-spike-*) : ;;
  *) printf 'geweigerd: het label moet met ephemeral-spike- beginnen, kreeg %s\n' "$LABEL" >&2 ; exit 4 ;;
esac

mkdir -p "$OUT"
DOC="$OUT/ephemeral-spike.md"
api() { curl --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
             --silent --show-error --fail-with-body --max-time 30 "$@" ; }

{
  printf '# Ephemeral-spike\n\n'
  printf 'Instance: %s\n\n' "$FORGEJO_URL"
  printf 'Canary-label: `%s`\n\n' "$LABEL"
} > "$DOC"

# Registreren met ephemeral: true.
CREATE_JSON="$(api --request POST --header 'Content-Type: application/json' \
  --data "$(printf '{"name":"%s","description":"stap-A ephemeral spike","ephemeral":true}' "$LABEL")" \
  "$FORGEJO_URL/api/v1/admin/actions/runners")"

RUNNER_ID="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
RUNNER_UUID="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("uuid",""))')"
HAS_TOKEN="$(printf '%s' "$CREATE_JSON" | python3 -c 'import json,sys; print("ja" if json.load(sys.stdin).get("token") else "nee")')"

{
  printf '## 1. Registratie accepteert `ephemeral: true`\n\n'
  printf -- '- record-id: `%s`\n' "$RUNNER_ID"
  printf -- '- uuid: `%s`\n' "$RUNNER_UUID"
  printf -- '- respons bevatte een token: %s (waarde bewust niet vastgelegd)\n\n' "$HAS_TOKEN"
} >> "$DOC"

# Terugleesbewijs: staat ephemeral echt op het record, en draagt het geen labels?
READ_JSON="$(api "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID")"

# Veiligheidskader 1: RegisterRunnerOptions kent geen labels en er verbindt geen
# daemon, dus het record hoort labelloos te zijn. Blijkt dat niet zo, dan klopt
# de aanname niet en stoppen we voordat er iets op dit record kan landen.
LABELS_AANTAL="$(printf '%s' "$READ_JSON" | python3 -c '
import json,sys
print(len(json.load(sys.stdin).get("labels") or []))
')"
if [ "$LABELS_AANTAL" != "0" ]; then
  printf 'FOUT: record %s draagt %s label(s); veiligheidskader 1 klopt niet. Verwijder het record handmatig.\n' \
    "$RUNNER_ID" "$LABELS_AANTAL" >&2
  api --request DELETE "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null || true
  exit 6
fi

{
  printf '## 2. Het record toont ephemeral en draagt geen labels\n\n```json\n'
  printf '%s' "$READ_JSON" | python3 -c '
import json,sys
d=json.load(sys.stdin)
d.pop("token",None)
json.dump(d,sys.stdout,indent=2,sort_keys=True,ensure_ascii=False)
print()
'
  printf '```\n\n'
} >> "$DOC"

# Veiligheidskader 3: opruimen en bewijzen.
api --request DELETE "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null
if api "$FORGEJO_URL/api/v1/admin/actions/runners/$RUNNER_ID" >/dev/null 2>&1; then
  printf '## 3. Opruimen\n\nFOUT: record %s bestaat na DELETE nog steeds. Handmatig opruimen vereist.\n' "$RUNNER_ID" >> "$DOC"
  exit 5
fi
printf '## 3. Opruimen\n\nRecord `%s` is verwijderd; een GET erop geeft geen record meer terug.\n' "$RUNNER_ID" >> "$DOC"

printf 'spike afgerond, bewijs in %s\n' "$DOC"
