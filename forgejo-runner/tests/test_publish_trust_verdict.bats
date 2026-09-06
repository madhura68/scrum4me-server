setup() { TMP="$(mktemp -d)"; printf 'l' > "$TMP/labels.txt"; printf 'a' > "$TMP/allow.yml"; }
teardown() { rm -rf "$TMP"; }

@test "geeft de target door aan de CLI via FORGEJO_URL en bindt daaraan (B3)" {
  cat > "$TMP/cli.py" <<'PY'
import os, sys
out = sys.argv[sys.argv.index("--out")+1]
open(out + "/trust-verdict.json","w").write('{"ok":true}')
open(os.environ["PROBE_FILE"],"w").write(os.environ.get("FORGEJO_URL","UNSET"))
PY
  PROBE_FILE="$TMP/seen" run scripts/publish-trust-verdict.sh --cli-py "$TMP/cli.py" \
    --labels "$TMP/labels.txt" --allowlist "$TMP/allow.yml" --target https://git.jp-visser.nl --out "$TMP/v.json"
  [ "$status" -eq 0 ]
  [ "$(cat "$TMP/seen")" = "https://git.jp-visser.nl" ]      # CLI zag de target-bron
  grep -q '"forgejo_target":"https://git.jp-visser.nl"' "$TMP/v.json"
  grep -q '"measured_at":' "$TMP/v.json"
}

@test "mislukte hernieuwde meting invalideert het actieve verdict (M1/M4)" {
  printf '{"ok":true,"measured_at":%s,"forgejo_target":"https://x","labels_sha256":"L","allowlist_sha256":"A"}' \
    "$(date +%s)" > "$TMP/v.json"                            # volledig geldig, vers groen uitgangspunt
  cat > "$TMP/fail.py" <<'PY'
import sys; sys.exit(30)
PY
  run scripts/publish-trust-verdict.sh --cli-py "$TMP/fail.py" --labels "$TMP/labels.txt" \
    --allowlist "$TMP/allow.yml" --target https://x --out "$TMP/v.json"
  [ "$status" -ne 0 ]                                        # falen zichtbaar
  grep -q '"ok":false' "$TMP/v.json"                         # actief verdict geïnvalideerd → controllergate rood
}
