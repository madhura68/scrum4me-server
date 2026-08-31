#!/usr/bin/env bash
# forgejo-runner/scripts/capture-host-facts.sh
# Legt de hostfeiten vast waarop preflight.sh toetst. Read-only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { printf 'gebruik: capture-host-facts.sh --out BESTAND\n' >&2 ; exit 2 ; }

ROOT="$(ro_docker info --format '{{.DockerRootDir}}')"

{
  printf 'vcpu\t%s\n' "$(nproc)"
  printf 'mem_total_bytes\t%s\n' "$(awk '/MemTotal/{print $2 * 1024; exit}' /proc/meminfo)"
  printf 'mem_available_bytes\t%s\n' "$(awk '/MemAvailable/{print $2 * 1024; exit}' /proc/meminfo)"
  printf 'docker_root_dir\t%s\n' "$ROOT"
  printf 'docker_root_free_bytes\t%s\n' "$(df -B1 --output=avail "$ROOT" | tail -1 | tr -d ' ')"
  printf 'docker_root_free_pct\t%s\n' "$(df --output=pcent "$ROOT" | tail -1 | tr -d ' %' | awk '{print 100 - $1}')"
  printf 'docker_root_free_inodes_pct\t%s\n' "$(df --output=ipcent "$ROOT" | tail -1 | tr -d ' %' | awk '{print 100 - $1}')"
} > "$OUT"

printf 'hostfeiten geschreven naar %s\n' "$OUT"
