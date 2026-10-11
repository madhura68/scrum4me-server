#!/usr/bin/env bash
# forgejo-runner/scripts/dind-guard.sh
# Hostfirewallguard voor de DinD-API (T-188, audit-opvolging 30 sep 2026).
# DinD luistert zonder TLS op tcp://0.0.0.0:2375 binnen de bridge van zijn stack
# (fr-dind0 voor stack 02, fr-dind1 voor de volgende, enzovoort). Een
# lokale hostgebruiker (zelfs `nobody`) kan vanuit de hostnamespace naar
# <bridge-ip>:2375 verbinden en is dan root. Niets op de host heeft dat pad
# nodig (healthcheck draait in de container, de controller gebruikt
# `docker compose exec`). De runnercontainer bereikt DinD container-naar-
# container via de bridge (FORWARD), niet via OUTPUT, en blijft dus werken.
# Jobcontainers binnen DinD gebruiken tcp://dind.internal:2375, ook niet via
# host-OUTPUT.
#
# De regel staat in OUTPUT (verkeer dat de host zelf naar de bridge stuurt) en
# hangt aan de interfacenaam, niet aan het bestaan van de bridge: `-o` op een
# nog niet bestaande interface is geldig. Het patroon is de wildcard `fr-dind+`
# (iptables: iedere interface die met fr-dind begint, R17 §7.5): een nieuwe stack
# met bridge fr-dind<N> is dus gedekt zonder dat de regel opnieuw gezet hoeft te
# worden, ook als zijn bridge pas bestaat nadat de guard draait. Oude, specifieke
# regels (`-o fr-dind0`) van vóór R17 blijven onschadelijk staan; `check` eist de
# wildcardregels, dus een host is pas na `apply` op de R17-bundel. Docker raakt de
# filter-OUTPUTketen niet aan. Geen ip6tables: het netwerk heeft EnableIPv6 false; zet iemand
# IPv6 aan, voeg dan dezelfde regels toe via ip6tables.
#
# Gebruik: dind-guard.sh apply|check
#   apply  zet de regels er idempotent bovenaan (vereist root / CAP_NET_ADMIN)
#   check  exit 0 alleen als alle regels bestaan
# IPTABLES is overschrijfbaar zodat tests zonder host draaien.
set -euo pipefail

IPTABLES="${IPTABLES:-iptables}"
BRIDGE="fr-dind+"
POORTEN=(2375 2376)

bestaat() {
  "$IPTABLES" -w -C OUTPUT -o "$BRIDGE" -p tcp --dport "$1" -j REJECT --reject-with tcp-reset 2>/dev/null
}

case "${1:-}" in
  apply)
    for poort in "${POORTEN[@]}"; do
      bestaat "$poort" || \
        "$IPTABLES" -w -I OUTPUT 1 -o "$BRIDGE" -p tcp --dport "$poort" -j REJECT --reject-with tcp-reset
    done
    ;;
  check)
    for poort in "${POORTEN[@]}"; do
      bestaat "$poort" || { printf 'dind-guard: regel voor %s:%s ontbreekt\n' "$BRIDGE" "$poort" >&2 ; exit 1 ; }
    done
    ;;
  *)
    printf 'gebruik: dind-guard.sh apply|check\n' >&2 ; exit 2 ;;
esac
