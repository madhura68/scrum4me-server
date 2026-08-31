#!/usr/bin/env bash
# forgejo-runner/scripts/measure-workload.sh
# Meet iedere vijf seconden het gebruik van runner en DinD plus MemAvailable.
# Read-only: docker stats leest alleen. Draait OP de host tijdens de workflow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/readonly.sh
source "$SCRIPT_DIR/lib/readonly.sh"

RUNNER="" ; DIND="" ; OUT="" ; SECONDS_TOTAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --runner)  RUNNER="$2"        ; shift 2 ;;
    --dind)    DIND="$2"          ; shift 2 ;;
    --out)     OUT="$2"           ; shift 2 ;;
    --seconds) SECONDS_TOTAL="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$RUNNER" ] && [ -n "$DIND" ] && [ -n "$OUT" ] && [ "$SECONDS_TOTAL" -gt 0 ] || {
  printf 'gebruik: --runner NAAM --dind NAAM --out BESTAND --seconds N\n' >&2 ; exit 2 ; }

printf 't\trunner_cpu_pct\trunner_mem_bytes\trunner_pids\tdind_cpu_pct\tdind_mem_bytes\tdind_pids\tmem_available_bytes\n' > "$OUT"

sample_container() {
  # CPUPerc, MemUsage en PIDs in een keer; --no-stream leest een momentopname.
  ro_docker stats --no-stream --format '{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' "$1" 2>/dev/null || printf '0%%\t0B / 0B\t0\n'
}

t=0
while [ "$t" -lt "$SECONDS_TOTAL" ]; do
  R="$(sample_container "$RUNNER")"
  D="$(sample_container "$DIND")"
  MEMAV="$(awk '/MemAvailable/{print $2 * 1024; exit}' /proc/meminfo)"
  printf '%s\t%s\t%s\t%s\n' "$t" \
    "$(printf '%s' "$R" | python3 -c '
import sys
cpu, mem, pids = sys.stdin.read().rstrip("\n").split("\t")
def to_bytes(s):
    s = s.split("/")[0].strip()
    units = {"B":1,"KiB":1024,"MiB":1024**2,"GiB":1024**3,"kB":1000,"MB":1000**2,"GB":1000**3}
    for unit, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.endswith(unit):
            return int(float(s[:-len(unit)]) * factor)
    return 0
print("%s\t%d\t%s" % (cpu.rstrip("%"), to_bytes(mem), pids))
')" \
    "$(printf '%s' "$D" | python3 -c '
import sys
cpu, mem, pids = sys.stdin.read().rstrip("\n").split("\t")
def to_bytes(s):
    s = s.split("/")[0].strip()
    units = {"B":1,"KiB":1024,"MiB":1024**2,"GiB":1024**3,"kB":1000,"MB":1000**2,"GB":1000**3}
    for unit, factor in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if s.endswith(unit):
            return int(float(s[:-len(unit)]) * factor)
    return 0
print("%s\t%d\t%s" % (cpu.rstrip("%"), to_bytes(mem), pids))
')" \
    "$MEMAV" >> "$OUT"
  sleep 5
  t=$((t + 5))
done

printf 'meetreeks geschreven naar %s\n' "$OUT"
