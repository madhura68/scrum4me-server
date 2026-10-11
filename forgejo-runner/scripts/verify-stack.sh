#!/usr/bin/env bash
# forgejo-runner/scripts/verify-stack.sh
# Verifieert de uitgerolde stack(s) op deze host (§6.1, §7.5, §7.6, R17).
# Gebruik: verify-stack.sh COMMIT_SHA BUNDEL_HASH [--stacks "02 03" [--pre-start]]
# Exit 0 groen, 60 commit-drift, 61 bundelhash-drift, 62 isolatiefout (ook
# een ontbrekende `ss`), 63 systemd-unit-drift, 64 eigendom/schrijfrechten van
# de bundel, 65 DinD-guard ontbreekt of een DinD-API is vanaf de host bereikbaar,
# 66 stackinvariant geschonden (alleen met --stacks), 2 gebruiksfout.
#
# Zonder --stacks, en zolang er geen ingeschakelde instantie van de template
# forgejo-runner-cycle@.service is, is het gedrag dat van vóór R17 (één stack).
# Met --stacks "02 03" kijkt de gate naar de aangekondigde stacks:
#   - exit 63 vergelijkt dan ook de template byte voor byte met de bundelkopie;
#   - exit 64 omvat de bestandsset van R17 §5 per stack;
#   - exit 66, statisch deel (stack_invariants.py): unieke projectnaam, bridge,
#     volume, tokenpad, tokeninhoud en marker_path uit de EFFECTIEVE waarden van
#     `docker compose config`, en gelijke pins/caps over de per-stack-envs;
#   - exit 66, runtime-deel: de verzameling projectnamen van de draaiende DinD's is
#     gelijk aan de verwachte stackset (setgelijkheid, niet aantal).
# Met --pre-start (vereist --stacks) vervalt het runtime-deel van 66: een DinD die
# nog niet gestart is, is dan geen fout. De guardproef (65) en de `ss`-controle (62)
# gelden voor de DinD's die bestaan, en stack 02 moet er altijd een hebben.
#
# BUNDLE_COMMIT_FILE, SYSTEMD_DIR en STACKS_DIR zijn overschrijfbaar zodat de
# faaltakken zonder host getest kunnen worden; op de hosts zijn het
# /opt/forgejo-runner/BUNDLE_COMMIT, /etc/systemd/system en /opt/forgejo-runner-stacks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_COMMIT_FILE="${BUNDLE_COMMIT_FILE:-/opt/forgejo-runner/BUNDLE_COMMIT}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
STACKS_DIR="${STACKS_DIR:-/opt/forgejo-runner-stacks}"
TEMPLATE_UNIT="forgejo-runner-cycle@.service"

gebruik() {
  printf 'gebruik: verify-stack.sh COMMIT_SHA BUNDEL_HASH [--stacks "02 03" [--pre-start]]\n' >&2
  exit 2
}

VERWACHT_COMMIT="${1:-}"
VERWACHTE_HASH="${2:-}"
[ -n "$VERWACHT_COMMIT" ] && [ -n "$VERWACHTE_HASH" ] || gebruik
shift 2

STACKS_GEGEVEN=0
STACKS=""
PRE_START=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stacks) [ $# -ge 2 ] || gebruik; STACKS_GEGEVEN=1; STACKS="$2"; shift 2 ;;
    --pre-start) PRE_START=1; shift ;;
    *) gebruik ;;
  esac
done
[ "$PRE_START" = 0 ] || [ "$STACKS_GEGEVEN" = 1 ] || gebruik

# De stackids: unieke tweecijferige ids, inclusief 02 (de bestaande stack, de bundelmap zelf).
STACK_IDS=()
if [ "$STACKS_GEGEVEN" = 1 ]; then
  GEZIEN_IDS=" "
  set -f   # geen padexpansie van de waarde van --stacks
  for id in $STACKS; do
    case "$id" in
      [0-9][0-9]) ;;
      *) printf 'gebruiksfout: ongeldig stack-id %s (tweecijferig verwacht)\n' "$id" >&2 ; exit 2 ;;
    esac
    case "$GEZIEN_IDS" in
      *" $id "*) printf 'gebruiksfout: stack-id %s komt dubbel voor\n' "$id" >&2 ; exit 2 ;;
    esac
    GEZIEN_IDS="$GEZIEN_IDS$id "
    STACK_IDS+=("$id")
  done
  set +f
  case "$GEZIEN_IDS" in
    *" 02 "*) ;;
    *) printf 'gebruiksfout: --stacks moet stack 02 bevatten\n' >&2 ; exit 2 ;;
  esac
fi

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
# De template (R17): vergeleken zodra er een ingeschakelde instantie is, of altijd met
# --stacks. Een instantie is geen bestand maar de symlink die `systemctl enable` onder
# <target>.wants/ naar de template zet; een dode link telt ook (template verdwenen). Het
# patroon @?* matcht de template zelf niet (@.service), dus "template geïnstalleerd,
# instantie niet ingeschakeld" blijft groen.
TEMPLATE_VERGELIJKEN="$STACKS_GEGEVEN"
for link in "$SYSTEMD_DIR"/*.wants/forgejo-runner-cycle@?*.service "$SYSTEMD_DIR"/forgejo-runner-cycle@?*.service; do
  if [ -L "$link" ] || [ -e "$link" ]; then TEMPLATE_VERGELIJKEN=1 ; fi
done
if [ "$TEMPLATE_VERGELIJKEN" = 1 ]; then
  cmp -s "$BUNDLE/$TEMPLATE_UNIT" "$SYSTEMD_DIR/$TEMPLATE_UNIT" || {
    printf 'unit-drift: %s ontbreekt of wijkt af van de bundelkopie (%s)\n' "$TEMPLATE_UNIT" "$SYSTEMD_DIR" >&2 ; exit 63 ; }
fi

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
# Ook iedere map die gehashte bestanden bevat telt (R16 review): wie een map kan
# schrijven kan een root-eigendom-bestand erin hernoemen of vervangen, ook als het
# bestand zelf en zijn bytes kloppen. Zonder externe tools (bash 3.2 op macOS).
GEZIEN=$'\n'
while IFS= read -r -d '' pad; do
  eigendom_ok "$BUNDLE/$pad" || {
    printf 'eigendomsfout: %s is niet van root of is groep/wereld-schrijfbaar\n' "$pad" >&2 ; exit 64 ; }
  map="${pad%/*}"
  while [ "$map" != "." ] && [ "$map" != "$pad" ]; do
    case "$GEZIEN" in *$'\n'"$map"$'\n'*) break ;; esac
    GEZIEN="$GEZIEN$map"$'\n'
    eigendom_ok "$BUNDLE/$map" || {
      printf 'eigendomsfout: map %s is niet van root of is groep/wereld-schrijfbaar\n' "$map" >&2 ; exit 64 ; }
    map="${map%/*}"
  done
done < <(bash "$SCRIPT_DIR/bundle-hash.sh" "$BUNDLE" --list)

# De bestandsset van R17 §5 per aangekondigde stack (alleen met --stacks): de per-stack-map,
# .env, controller.toml, runner-config.yml, state/ en een aanwezige marker; voor stack 02
# bovendien BUNDLE_COMMIT en een aanwezig trust-verdict.json. credentials/ is bewust
# uitgezonderd (root 0700, het token zelf is van de runner-UID). Een ontbrekend bestand is
# ook een fout: zonder het is er niets te meten.
eigendom_stack() {   # pad, verplicht|optioneel
  if [ ! -e "$1" ]; then
    [ "$2" = optioneel ] && return 0
    printf 'eigendomsfout: %s ontbreekt\n' "$1" >&2 ; exit 64
  fi
  eigendom_ok "$1" || {
    printf 'eigendomsfout: %s is niet van root of is groep/wereld-schrijfbaar\n' "$1" >&2 ; exit 64 ; }
}
if [ "$STACKS_GEGEVEN" = 1 ]; then
  for id in "${STACK_IDS[@]}"; do
    if [ "$id" = 02 ]; then stack_map="$BUNDLE"; else stack_map="$STACKS_DIR/$id"; fi
    eigendom_stack "$stack_map" verplicht
    for bestand in .env controller.toml runner-config.yml state; do
      eigendom_stack "$stack_map/$bestand" verplicht
    done
    eigendom_stack "$stack_map/state/cycle-op.marker" optioneel
    if [ "$id" = 02 ]; then
      eigendom_stack "$BUNDLE_COMMIT_FILE" verplicht
      eigendom_stack "$BUNDLE/trust-verdict.json" optioneel
    fi
  done

  # Stackinvarianten, statisch deel (exit 66): vóór de `ss`- en guardproef, zodat een
  # aangekondigde stack die zijn bridge of zijn volume met een andere deelt nooit tot een
  # groene uitkomst komt, ook niet als zijn DinD nog niet bestaat.
  command -v python3 >/dev/null 2>&1 || {
    printf 'stackinvariant: python3 ontbreekt, de invarianten zijn niet te controleren\n' >&2 ; exit 66 ; }
  python3 "$SCRIPT_DIR/stack_invariants.py" --bundle "$BUNDLE" --stacks-dir "$STACKS_DIR" --stacks "$STACKS" || {
    printf 'stackinvariant: de statische controle van de stacks faalde\n' >&2 ; exit 66 ; }
fi

# Isolatie: geen hostlistener op de Docker-API-poorten (§7.5). Het patroon
# eist een poortgrens, zodat 23750 niet als 2375 telt.
command -v ss >/dev/null 2>&1 || {
  printf 'isolatiefout: ss ontbreekt, isolatie niet te controleren\n' >&2 ; exit 62 ; }
# De uitvoer van ss wordt eerst gemeten: een ss die zelf faalt is geen bewijs
# van "niets luistert" (R16 review).
SS_UIT="$(ss -ltn 2>/dev/null)" || {
  printf 'isolatiefout: ss faalde, isolatie niet te controleren\n' >&2 ; exit 62 ; }
if printf '%s\n' "$SS_UIT" | grep -qE ':(2375|2376)([^0-9]|$)'; then
  printf 'isolatiefout: er luistert iets op 2375 of 2376\n' >&2 ; exit 62
fi

# DinD-guard (T-188): de firewallregel moet bestaan én de DinD-API mag vanaf de
# host niet bereikbaar zijn op de bridges fr-dind+. De gedragsproef is het echte
# bewijs; ontbreekt DinD, docker of timeout, dan is de guard niet te bewijzen
# en faalt de gate (fail-closed).
bash "$SCRIPT_DIR/dind-guard.sh" check || {
  printf 'guardfout: dind-guard.sh check faalde, firewallregel ontbreekt\n' >&2 ; exit 65 ; }
for cmd in docker timeout; do
  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'guardfout: %s ontbreekt, bereikbaarheid niet te proeven\n' "$cmd" >&2 ; exit 65 ; }
done
# Alle DinD-containers van deze bundel: label service=dind en een project dat
# forgejo-runner heet of ermee begint (forgejo-runner-03). Eén `docker ps` voedt zowel de
# guardproef als het runtime-deel van exit 66. Faalt `docker ps`, dan is er geen DinD
# gevonden en volgt exit 65 hieronder.
DIND_PS="$(docker ps --filter label=com.docker.compose.service=dind \
  --format '{{.ID}} {{.Label "com.docker.compose.project"}}' 2>/dev/null)" || DIND_PS=""
DIND_REGELS=""
WAARGENOMEN=" "
while read -r dind_id dind_project; do
  [ -n "$dind_id" ] || continue
  case "$dind_project" in
    forgejo-runner|forgejo-runner-*)
      DIND_REGELS="$DIND_REGELS$dind_id $dind_project"$'\n'
      case "$WAARGENOMEN" in *" $dind_project "*) ;; *) WAARGENOMEN="$WAARGENOMEN$dind_project " ;; esac ;;
  esac
done <<< "$DIND_PS"
# Stack 02 moet altijd een draaiende DinD hebben (fail-closed, ook met --pre-start).
case "$WAARGENOMEN" in
  *" forgejo-runner "*) ;;
  *) printf 'guardfout: geen draaiende DinD-container van project forgejo-runner gevonden, bereikbaarheid niet te proeven\n' >&2 ; exit 65 ;;
esac

# Stackinvarianten, runtime-deel (exit 66): de verzameling projectnamen van de draaiende
# DinD's is gelijk aan de verwachte stackset. Setgelijkheid, niet aantal: een vreemd
# forgejo-runner-04 gaat niet door voor een ontbrekende -03.
if [ "$STACKS_GEGEVEN" = 1 ] && [ "$PRE_START" = 0 ]; then
  VERWACHT=" "
  for id in "${STACK_IDS[@]}"; do
    if [ "$id" = 02 ]; then VERWACHT="${VERWACHT}forgejo-runner "; else VERWACHT="${VERWACHT}forgejo-runner-$id "; fi
  done
  ONTBREEKT=""
  for project in $VERWACHT; do
    case "$WAARGENOMEN" in *" $project "*) ;; *) ONTBREEKT="$ONTBREEKT $project" ;; esac
  done
  VREEMD=""
  for project in $WAARGENOMEN; do
    case "$VERWACHT" in *" $project "*) ;; *) VREEMD="$VREEMD $project" ;; esac
  done
  if [ -n "$ONTBREEKT" ] || [ -n "$VREEMD" ]; then
    printf 'stackinvariant: de draaiende DinD-projecten komen niet overeen met de aangekondigde stacks (ontbreekt:%s; onverwacht:%s)\n' \
      "${ONTBREEKT:- -}" "${VREEMD:- -}" >&2
    exit 66
  fi
fi

# De gedragsproef over ALLE DinD's, niet over de eerste: iedere DinD heeft zijn eigen bridge.
while read -r dind_id dind_project; do
  [ -n "$dind_id" ] || continue
  DIND_IPS="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$dind_id" 2>/dev/null || true)"
  [ -n "${DIND_IPS// /}" ] || {
    printf 'guardfout: DinD-container van project %s heeft geen IP, bereikbaarheid niet te proeven\n' "$dind_project" >&2 ; exit 65 ; }
  for ip in $DIND_IPS; do
    for poort in 2375 2376; do
      # Exit 0 = verbonden (bereikbaar), 1 = verbinding geweigerd, 124 = niet binnen
      # 3 s tot stand gekomen. Iedere andere uitkomst (125-127: timeout of bash kon
      # niet draaien, 137: gedood) is geen meting van de guard (R16 review).
      rc=0
      # shellcheck disable=SC2016  # $0/$1 zijn de argumenten van de kind-bash
      timeout 3 bash -c 'exec 3<>"/dev/tcp/$0/$1"' "$ip" "$poort" 2>/dev/null || rc=$?
      case "$rc" in
        0) printf 'guardfout: DinD-API bereikbaar vanaf de host op %s:%s (project %s)\n' "$ip" "$poort" "$dind_project" >&2 ; exit 65 ;;
        1|124) : ;;
        *) printf 'guardfout: de bereikbaarheidsproef op %s:%s kon niet draaien (exit %s), guard niet te bewijzen\n' "$ip" "$poort" "$rc" >&2 ; exit 65 ;;
      esac
    done
  done
done <<< "$DIND_REGELS"

printf 'commit: %s\nbundel_hash: %s\nisolatie: OK\nguard: OK\n' "$HUIDIG_COMMIT" "$HUIDIGE_HASH"
if [ "$STACKS_GEGEVEN" = 1 ]; then
  if [ "$PRE_START" = 1 ]; then MODUS="pre-start"; else MODUS="runtime"; fi
  printf 'stacks: %s (%s)\nstackinvarianten: OK\n' "$STACKS" "$MODUS"
fi
