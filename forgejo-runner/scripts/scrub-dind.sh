#!/bin/sh
# forgejo-runner/scripts/scrub-dind.sh
# Fenced cleanup binnen uitsluitend de eigen DinD (§7.9).
# Draait terwijl er aantoonbaar geen runnerproces bestaat, volgens de
# endpointmatrix van §7.5 bínnen de DinD-container op tcp://127.0.0.1:2375.
# docker:dind is Alpine zonder bash; daarom POSIX sh.
# De outer Runner- en DinD-images staan in de hostdaemon en worden hier niet geraakt.
#
# Exitcodes: 0 bewezen schoon, 50 restobject (of een bewijscommando dat zelf
# faalde), 51 tijdsoverschrijding, 52 DinD-daemon antwoordt niet (geen bewijs
# mogelijk), 2 gebruiksfout. Het opruimen negeert fouten; het bewijs daarna
# telt, en een leeg bewijsresultaat telt alleen als het commando slaagde.
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
# Regels "ID repo@digest". Met -a, want met de containerd-snapshotter (Docker
# 29) toont `images` zonder -a geen untagged/dangling images (ISS-10).
images() { d images -a --digests --format '{{.ID}} {{.Repository}}@{{.Digest}}' ; }
# IDs van toegestane images: een ander label op hetzelfde ID mag hem niet slopen.
bewaar_ids() {
  images | while read -r id img; do
    if toegestaan "$img"; then printf '%s\n' "$id"; fi
  done
}

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
BEWAAR="$(bewaar_ids)"
images | while read -r id img; do
  [ -n "$id" ] || continue
  toegestaan "$img" && continue
  printf '%s\n' "$BEWAAR" | grep -Fxq -- "$id" && continue
  d rmi -f "$id" || true
done

# Bewijs. Vanaf hier bepaalt de meting de exitcode.
# Zonder antwoordende daemon is ieder commando leeg en zou alles "OK" lijken;
# daarom moet de daemon vóór en na het bewijs antwoorden (exit 52).
leeft() { d version --format '{{.Server.Version}}' >/dev/null 2>&1 ; }
daemon_vereist() {
  if leeft; then printf 'daemon: OK\n'; else printf 'daemon: FAIL\n'; exit 52; fi
}
daemon_vereist

FALEN=0
melden() {
  printf '%s: %s\n' "$1" "$2"
  if [ "$2" = "FAIL" ]; then FALEN=1 ; fi
}
# Een bewijscommando dat zelf faalt is FAIL, nooit een leeg (= schoon) resultaat.
leeg_bewijs() {
  naam="$1" ; shift
  if ! UIT="$(d "$@" 2>/dev/null)"; then melden "$naam" FAIL; return 0; fi
  if [ -z "$UIT" ]; then melden "$naam" OK; else melden "$naam" FAIL; fi
}

leeg_bewijs containers ps -aq
leeg_bewijs volumes volume ls -q

if NETS="$(d network ls --format '{{.Name}}' 2>/dev/null)"; then
  VREEMD="$(printf '%s\n' "$NETS" | grep -vxE 'bridge|host|none' || true)"
  if [ -z "$VREEMD" ]; then melden netwerken OK; else melden netwerken FAIL; fi
else
  melden netwerken FAIL
fi

if IMGS="$(images 2>/dev/null)"; then
  NIET_TOEGESTAAN="$(printf '%s\n' "$IMGS" | while read -r id img; do
    [ -n "$id" ] || continue
    toegestaan "$img" || printf '%s(%s) ' "$img" "$id"
  done)"
  if [ -z "$NIET_TOEGESTAAN" ]; then melden images OK; else melden images FAIL; fi
else
  melden images FAIL
fi

# §7.9 stap 8: geen buildcache. `system df` toont de cachegrootte van de
# daemon zelf, ook zonder buildx-plugin. Een leeg resultaat is FAIL: ook een
# schone daemon meldt "Build Cache 0B".
if DF="$(d system df --format '{{.Type}}\t{{.Size}}' 2>/dev/null)"; then
  CACHE="$(printf '%s\n' "$DF" | awk -F'\t' '$1=="Build Cache"{print $2}')"
  if [ "$CACHE" = "0B" ]; then melden buildcache OK; else melden buildcache FAIL; fi
else
  melden buildcache FAIL
fi

# De daemon moet ook aan het eind nog antwoorden (hij kan tijdens het bewijs
# zijn weggevallen).
daemon_vereist

DUUR=$(( $(date +%s) - START ))
printf 'duur_seconden: %s\n' "$DUUR"
[ "$DUUR" -le "$MAX_SECONDS" ] || exit 51
[ "$FALEN" -eq 0 ] || exit 50
