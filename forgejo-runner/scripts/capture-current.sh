#!/usr/bin/env bash
# forgejo-runner/scripts/capture-current.sh
# Read-only inventarisatie van de live runnerstack. Draait OP de host.
# Muteert niets: schrijft uitsluitend naar de opgegeven uitvoermap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

RUNNER="" ; DIND="" ; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --runner) RUNNER="$2" ; shift 2 ;;
    --dind)   DIND="$2"   ; shift 2 ;;
    --out)    OUT="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$RUNNER" ] && [ -n "$DIND" ] && [ -n "$OUT" ] || {
  printf 'gebruik: capture-current.sh --runner NAAM --dind NAAM --out MAP\n' >&2
  exit 2
}

mkdir -p "$OUT"

# Images met hun RepoDigests. De tag alleen is niet reproduceerbaar (Global Constraints).
ro_docker image inspect \
  "$(ro_docker container inspect "$RUNNER" --format '{{.Config.Image}}')" \
  "$(ro_docker container inspect "$DIND" --format '{{.Config.Image}}')" \
  > "$OUT/images.json" 2>/dev/null \
  || ro_docker image inspect "$RUNNER" "$DIND" > "$OUT/images.json"

# container inspect draagt Config.Env en het entrypoint-commando; die kunnen een
# RUNNER_REGISTRATION_TOKEN o.i.d. bevatten. Nooit onveranderd wegschrijven: eerst
# door de redactor, die env-secrets en inline --token-waarden vervangt.
ro_docker container inspect "$RUNNER" "$DIND" \
  | python3 "$SCRIPT_DIR/lib/redact_inspect.py" > "$OUT/containers.json"
ro_docker network ls --format '{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}' > "$OUT/networks.json"
ro_docker volume ls --format '{{.Name}}\t{{.Driver}}\t{{.Mountpoint}}' > "$OUT/volumes.json"

# Omvang van de inner-DinD-data. Kan bij ~121 GB enkele minuten duren.
DIND_SRC="$(ro_docker container inspect "$DIND" \
  --format '{{range .Mounts}}{{if eq .Destination "/var/lib/docker"}}{{.Source}}{{end}}{{end}}')"
if [ -n "$DIND_SRC" ]; then
  printf 'mountpoint\t%s\n' "$DIND_SRC" > "$OUT/dind-usage.txt"
  # sudo alleen voor de privileged read (root-owned pad); de append schrijft bewust
  # als de gewone gebruiker naar het zelf aangemaakte $OUT.
  # shellcheck disable=SC2024
  sudo -n du -sb "$DIND_SRC" >> "$OUT/dind-usage.txt"
else
  printf 'mountpoint\tONBEKEND — geen mount op /var/lib/docker gevonden\n' > "$OUT/dind-usage.txt"
fi

# Legacy .runner: metadata bewaren, tokenwaarde nooit.
RUNNER_SRC="$(ro_docker container inspect "$RUNNER" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
if [ -n "$RUNNER_SRC" ] && sudo -n test -f "$RUNNER_SRC/.runner"; then
  # sudo alleen voor de privileged read; de redirect schrijft als de gewone gebruiker.
  # shellcheck disable=SC2024
  sudo -n stat -c '%a %U:%G %n' "$RUNNER_SRC/.runner" > "$OUT/runner-registration-stat.txt"
  sudo -n cat "$RUNNER_SRC/.runner" | python3 -c '
import json, sys
d = json.load(sys.stdin)
d.pop("token", None)
d["token"] = "<GEREDIGEERD>"
json.dump(d, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
print()
' > "$OUT/runner-registration.json"
else
  printf '{"fout":"geen .runner gevonden"}\n' > "$OUT/runner-registration.json"
fi

printf 'inventarisatie geschreven naar %s\n' "$OUT"
