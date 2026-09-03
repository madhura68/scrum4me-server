#!/bin/sh
# forgejo-runner/scripts/scrub-dind.sh
# Fenced cleanup binnen uitsluitend de eigen DinD (§7.9).
# Draait terwijl er aantoonbaar geen runnerproces bestaat, volgens de
# endpointmatrix van §7.5 bínnen de DinD-container op tcp://127.0.0.1:2375.
# docker:dind is Alpine zonder bash; daarom POSIX sh.
# De outer Runner- en DinD-images staan in de hostdaemon en worden hier niet geraakt.
#
# Exitcodes: 0 bewezen schoon, 50 restobject, 51 tijdsoverschrijding,
# 2 gebruiksfout. Het opruimen negeert fouten; het bewijs daarna telt.
set -eu

ENDPOINT="" ; ALLOW="" ; MAX_SECONDS="${SCRUB_MAX_SECONDS:-300}"
while [ $# -gt 0 ]; do
  case "$1" in
    --endpoint) ENDPOINT="$2" ; shift 2 ;;
    --allow)    ALLOW="$2"    ; shift 2 ;;
    *) printf 'onbekend argument: %s\n' "$1" >&2 ; exit 2 ;;
  esac
done
[ -n "$ENDPOINT" ] && [ -f "$ALLOW" ] || {
  printf 'gebruik: scrub-dind.sh --endpoint tcp://127.0.0.1:2375 --allow BESTAND\n' >&2 ; exit 2 ; }

START="$(date +%s)"
d() { docker -H "$ENDPOINT" "$@" ; }

# Alleen regels "digest<TAB>bytes"; commentaar en lege regels zijn geen images.
toegestaan() {
  awk '!/^[[:space:]]*(#|$)/ {print $1}' "$ALLOW" | grep -Fxq -- "$1"
}
images() { d images --digests --format '{{.Repository}}@{{.Digest}}' ; }

# Opruimen. Fouten worden genegeerd; het bewijs hieronder is wat telt.
d ps -aq | while read -r id; do
  [ -n "$id" ] && { d rm -f "$id" || true ; }
done
d volume ls -q | while read -r v; do
  [ -n "$v" ] && { d volume rm -f "$v" || true ; }
done
d network ls --format '{{.Name}}' | while read -r n; do
  case "$n" in bridge|host|none|'') : ;; *) d network rm "$n" || true ;; esac
done
d builder prune -af >/dev/null 2>&1 || true
images | while read -r img; do
  [ -n "$img" ] || continue
  toegestaan "$img" || d rmi -f "$img" || true
done

# Bewijs. Vanaf hier bepaalt de meting de exitcode.
FALEN=0
melden() {
  printf '%s: %s\n' "$1" "$2"
  if [ "$2" = "FAIL" ]; then FALEN=1 ; fi
}

if [ -z "$(d ps -aq)" ]; then melden containers OK; else melden containers FAIL; fi
if [ -z "$(d volume ls -q)" ]; then melden volumes OK; else melden volumes FAIL; fi

VREEMD="$(d network ls --format '{{.Name}}' | grep -vxE 'bridge|host|none' || true)"
if [ -z "$VREEMD" ]; then melden netwerken OK; else melden netwerken FAIL; fi

NIET_TOEGESTAAN="$(images | while read -r img; do
  [ -n "$img" ] || continue
  toegestaan "$img" || printf '%s ' "$img"
done)"
if [ -z "$NIET_TOEGESTAAN" ]; then melden images OK; else melden images FAIL; fi

# §7.9 stap 8: geen buildcache. `system df` toont de cachegrootte van de
# daemon zelf, ook zonder buildx-plugin.
CACHE="$(d system df --format '{{.Type}}\t{{.Size}}' | awk -F'\t' '$1=="Build Cache"{print $2}')"
if [ "${CACHE:-0B}" = "0B" ]; then melden buildcache OK; else melden buildcache FAIL; fi

DUUR=$(( $(date +%s) - START ))
printf 'duur_seconden: %s\n' "$DUUR"
[ "$DUUR" -le "$MAX_SECONDS" ] || exit 51
[ "$FALEN" -eq 0 ] || exit 50
