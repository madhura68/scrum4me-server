#!/usr/bin/env bash
# forgejo-runner/scripts/dind-guard.sh
# Hostfirewallguard voor de DinD-API (T-188, audit-opvolging 30 sep 2026).
# DinD luistert zonder TLS op tcp://0.0.0.0:2375 binnen de bridge fr-dind0. Een
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
# nog niet bestaande interface is geldig. Docker raakt de filter-OUTPUTketen
# niet aan. Geen ip6tables: het netwerk heeft EnableIPv6 false; zet iemand
# IPv6 aan, voeg dan dezelfde regels toe via ip6tables.
#
# Gebruik: dind-guard.sh apply|check
#   apply  zet de regels er idempotent bovenaan (vereist root / CAP_NET_ADMIN)
#   check  exit 0 alleen als alle regels bestaan
# IPTABLES is overschrijfbaar zodat tests zonder host draaien.
set -euo pipefail

IPTABLES="${IPTABLES:-iptables}"
BRIDGE="fr-dind0"
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
