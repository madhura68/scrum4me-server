#!/usr/bin/env bash
# forgejo-runner/scripts/preflight.sh
# De vier harde drempels uit §7.8. Faalt vóór iedere mutatie op deze host.
# Exit 0 als alle vier halen, 40 zodra er een faalt, 2 bij een gebruiksfout.
#
# --stacks N (standaard 1, R17): het aantal stacks dat naast elkaar op deze host moet
# passen. De vCPU-som en de geheugensom worden N × de som van één stack, de schijfregel
# wordt N × (images + 20 GiB). Zonder --stacks, of met --stacks 1, is de uitvoer
# byte-gelijk aan die van vóór R17.
#
# Het script versoepelt nooit een drempel om verder te kunnen: een FAIL is een
# NO-GO voor deze host en vraagt om overleg, niet om een lagere grens.
set -euo pipefail

FACTS="" ; CAPS="" ; IMAGES="" ; STACKS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --facts)  FACTS="$2"  ; shift 2 ;;
    --caps)   CAPS="$2"   ; shift 2 ;;
    --images) IMAGES="$2" ; shift 2 ;;
    --stacks)
      [ $# -ge 2 ] || { printf '--stacks vraagt een waarde\n' >&2 ; exit 2 ; }
      STACKS="$2" ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -f "$FACTS" ] && [ -f "$CAPS" ] || {
  printf 'gebruik: preflight.sh --facts TSV --caps ENV [--images BESTAND] [--stacks N]\n' >&2 ; exit 2 ; }
case "$STACKS" in
  ''|*[!0-9]*|0|0[0-9]*) printf -- '--stacks vraagt een geheel getal >= 1, kreeg: %s\n' "$STACKS" >&2 ; exit 2 ;;
esac

fact() { awk -F'\t' -v k="$1" '$1==k{print $2; exit}' "$FACTS" ; }
# shellcheck source=/dev/null
source "$CAPS"

# Een onvolledige caps.env is een gebruiksfout en geen stille GO: zonder deze
# check zou set -u pas verderop met een cryptische melding afbreken.
for V in RUNNER_CPU DIND_CPU RUNNER_MEM_BYTES DIND_MEM_BYTES; do
  [ -n "${!V:-}" ] || { printf '%s ontbreekt in %s\n' "$V" "$CAPS" >&2 ; exit 2 ; }
done

WERKRUIMTE_BYTES=$((20 * 1024 * 1024 * 1024))   # 20 GiB, vastgelegd in §7.8
FALEN=0
melding() {
  printf '%s: %s — %s\n' "$1" "$2" "$3"
  if [ "$2" = "FAIL" ]; then FALEN=1 ; fi
}

# Bij meer dan één stack noemt de melding het aantal; bij één stack blijft de tekst gelijk.
if [ "$STACKS" -gt 1 ]; then STACKS_TEKST=" (${STACKS} stacks)" ; else STACKS_TEKST="" ; fi

VCPU="$(fact vcpu)"
if [ "$STACKS" -gt 1 ]; then
  CPU_SOM="$(python3 -c "print(${STACKS} * (${RUNNER_CPU} + ${DIND_CPU}))")"
else
  CPU_SOM="$(python3 -c "print(${RUNNER_CPU} + ${DIND_CPU})")"
fi
if python3 -c "import sys; sys.exit(0 if ${CPU_SOM} <= ${VCPU} * 0.5 else 1)"; then
  melding vcpu OK "som ${CPU_SOM}${STACKS_TEKST} binnen 50% van ${VCPU}"
else
  melding vcpu FAIL "som ${CPU_SOM}${STACKS_TEKST} boven 50% van ${VCPU}"
fi

MEMAV="$(fact mem_available_bytes)"
MEM_SOM=$((STACKS * (RUNNER_MEM_BYTES + DIND_MEM_BYTES)))
if [ "$MEM_SOM" -le $((MEMAV / 2)) ]; then
  melding geheugen OK "som ${MEM_SOM}${STACKS_TEKST} binnen 50% van ${MEMAV}"
else
  melding geheugen FAIL "som ${MEM_SOM}${STACKS_TEKST} boven 50% van ${MEMAV}"
fi

VRIJ_PCT="$(fact docker_root_free_pct)"
VRIJ_BYTES="$(fact docker_root_free_bytes)"
IMAGES_BYTES=0
if [ -n "$IMAGES" ] && [ -f "$IMAGES" ]; then
  # Alleen regels "digest<TAB>bytes"; commentaar en lege regels tellen niet mee.
  IMAGES_BYTES="$(awk '!/^[[:space:]]*(#|$)/ && NF >= 2 {som += $2} END {print som + 0}' "$IMAGES")"
fi
NODIG=$((STACKS * (IMAGES_BYTES + WERKRUIMTE_BYTES)))
if [ "$VRIJ_PCT" -ge 20 ] && [ "$VRIJ_BYTES" -ge "$NODIG" ]; then
  melding schijf OK "${VRIJ_PCT}% vrij en ${VRIJ_BYTES} bytes >= ${NODIG} nodig"
else
  melding schijf FAIL "${VRIJ_PCT}% vrij en ${VRIJ_BYTES} bytes tegenover ${NODIG} nodig"
fi

INODES_PCT="$(fact docker_root_free_inodes_pct)"
if [ "$INODES_PCT" -ge 20 ]; then
  melding inodes OK "${INODES_PCT}% vrij"
else
  melding inodes FAIL "${INODES_PCT}% vrij"
fi

[ "$FALEN" -eq 0 ] || exit 40
