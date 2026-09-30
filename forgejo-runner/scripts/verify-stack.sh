#!/usr/bin/env bash
# forgejo-runner/scripts/verify-stack.sh
# Verifieert de uitgerolde stack op deze host (§6.1, §7.5, §7.6).
# Exit 0 groen, 60 commit-drift, 61 bundelhash-drift, 62 isolatiefout (ook
# een ontbrekende `ss`), 63 systemd-unit-drift, 64 eigendom/schrijfrechten van
# de bundel, 65 DinD-guard ontbreekt of de DinD-API is vanaf de host bereikbaar,
# 2 gebruiksfout.
#
# BUNDLE_COMMIT_FILE en SYSTEMD_DIR zijn overschrijfbaar zodat de faaltakken
# zonder host getest kunnen worden; op de hosts zijn het
# /opt/forgejo-runner/BUNDLE_COMMIT en /etc/systemd/system.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_COMMIT_FILE="${BUNDLE_COMMIT_FILE:-/opt/forgejo-runner/BUNDLE_COMMIT}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
VERWACHT_COMMIT="${1:-}"
VERWACHTE_HASH="${2:-}"
[ -n "$VERWACHT_COMMIT" ] && [ -n "$VERWACHTE_HASH" ] || {
  printf 'gebruik: verify-stack.sh COMMIT_SHA BUNDEL_HASH\n' >&2 ; exit 2 ; }

HUIDIG_COMMIT="$(cat "$BUNDLE_COMMIT_FILE" 2>/dev/null || true)"
[ -n "$HUIDIG_COMMIT" ] || { printf 'BUNDLE_COMMIT ontbreekt: %s\n' "$BUNDLE_COMMIT_FILE" >&2 ; exit 60 ; }
[ "$HUIDIG_COMMIT" = "$VERWACHT_COMMIT" ] || {
  printf 'commit-drift: host %s, verwacht %s\n' "$HUIDIG_COMMIT" "$VERWACHT_COMMIT" >&2 ; exit 60 ; }

HUIDIGE_HASH="$(bash "$SCRIPT_DIR/bundle-hash.sh" "$BUNDLE")"
[ "$HUIDIGE_HASH" = "$VERWACHTE_HASH" ] || {
  printf 'bundelhash-drift: host %s, verwacht %s\n' "$HUIDIGE_HASH" "$VERWACHTE_HASH" >&2 ; exit 61 ; }

# Geïnstalleerde units moeten byte-gelijk zijn aan de bundelkopie (AUDIT-023):
# de bundelhash dekt alleen de bestanden in /opt/forgejo-runner, niet wat
# systemd daadwerkelijk laadt.
for unit in forgejo-runner-cycle.service forgejo-runner-dind-guard.service forgejo-runner-trust.service forgejo-runner-trust.timer; do
  cmp -s "$BUNDLE/$unit" "$SYSTEMD_DIR/$unit" || {
    printf 'unit-drift: %s ontbreekt of wijkt af van de bundelkopie (%s)\n' "$unit" "$SYSTEMD_DIR" >&2 ; exit 63 ; }
done

# Eigendom (AUDIT-033): root-units voeren de bundel uit, dus de map en ieder
# gehasht bestand moeten van uid 0 zijn en niet groep- of wereldschrijfbaar.
# GNU stat (Ubuntu); tests stubben stat.
eigendom_ok() {
  local uid modus
  read -r uid modus < <(stat -c '%u %a' "$1") || return 1
  [ "$uid" = 0 ] && (( (8#$modus & 8#022) == 0 ))
}
eigendom_ok "$BUNDLE" || {
  printf 'eigendomsfout: bundelmap %s is niet van root of is groep/wereld-schrijfbaar\n' "$BUNDLE" >&2 ; exit 64 ; }
while IFS= read -r -d '' pad; do
  eigendom_ok "$BUNDLE/$pad" || {
    printf 'eigendomsfout: %s is niet van root of is groep/wereld-schrijfbaar\n' "$pad" >&2 ; exit 64 ; }
done < <(bash "$SCRIPT_DIR/bundle-hash.sh" "$BUNDLE" --list)

# Isolatie: geen hostlistener op de Docker-API-poorten (§7.5). Het patroon
# eist een poortgrens, zodat 23750 niet als 2375 telt.
command -v ss >/dev/null 2>&1 || {
  printf 'isolatiefout: ss ontbreekt, isolatie niet te controleren\n' >&2 ; exit 62 ; }
if ss -ltn 2>/dev/null | grep -qE ':(2375|2376)([^0-9]|$)'; then
  printf 'isolatiefout: er luistert iets op 2375 of 2376\n' >&2 ; exit 62
fi

# DinD-guard (T-188): de firewallregel moet bestaan én de DinD-API mag vanaf de
# host niet bereikbaar zijn op de bridge fr-dind0. De gedragsproef is het echte
# bewijs; ontbreekt DinD, docker of timeout, dan is de guard niet te bewijzen
# en faalt de gate (fail-closed).
bash "$SCRIPT_DIR/dind-guard.sh" check || {
  printf 'guardfout: dind-guard.sh check faalde, firewallregel ontbreekt\n' >&2 ; exit 65 ; }
for cmd in docker timeout; do
  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'guardfout: %s ontbreekt, bereikbaarheid niet te proeven\n' "$cmd" >&2 ; exit 65 ; }
done
DIND_ID="$(docker ps -q --filter label=com.docker.compose.project=forgejo-runner \
  --filter label=com.docker.compose.service=dind 2>/dev/null | head -n 1)"
DIND_IPS=""
[ -z "$DIND_ID" ] || DIND_IPS="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$DIND_ID" 2>/dev/null || true)"
[ -n "${DIND_IPS// /}" ] || {
  printf 'guardfout: geen draaiende DinD-container met IP gevonden, bereikbaarheid niet te proeven\n' >&2 ; exit 65 ; }
for ip in $DIND_IPS; do
  for poort in 2375 2376; do
    # shellcheck disable=SC2016  # $0/$1 zijn de argumenten van de kind-bash
    if timeout 3 bash -c 'exec 3<>"/dev/tcp/$0/$1"' "$ip" "$poort" 2>/dev/null; then
      printf 'guardfout: DinD-API bereikbaar vanaf de host op %s:%s\n' "$ip" "$poort" >&2 ; exit 65
    fi
  done
done

printf 'commit: %s\nbundel_hash: %s\nisolatie: OK\nguard: OK\n' "$HUIDIG_COMMIT" "$HUIDIGE_HASH"
