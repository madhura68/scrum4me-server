#!/usr/bin/env bash
# scripts/verify.sh — één verificatie-ingang voor de hele repo (T-153, AUDIT-014).
#
# Draait alle suites, telt pass/fail/skip per onderdeel, noemt iedere overgeslagen
# test bij naam met reden, en geeft een exitcode != 0 zodra ÉÉN onderdeel faalt.
#
# Onderdelen:
#   bats        iedere forgejo-runner/tests/*.bats en scripts/tests/*.bats
#   py          iedere forgejo-runner/tests/test_*.py en scripts/tests/test_*.py,
#               elk als eigen python3-proces (PYTHONDONTWRITEBYTECODE=1: geen .pyc)
#   lint        (--only shellcheck) `shellcheck -x` op iedere gevolgde *.sh (git ls-files), per bestand
#               vanuit de eigen map zodat gesourcete libs oplossen; bestanden met
#               een `#!/bin/sh`-shebang krijgen daarbij `-s sh`
#
# Gebruik:
#   bash scripts/verify.sh [--only bats|py|shellcheck] [--help]
#
# Opt-in integratietests (standaard UIT; ze halen images of hebben een database nodig):
#   VERIFY_INTEGRATION=1   neemt forgejo-runner/tests/test_compose_runner_exec.bats mee
#                          (pullt en draait de echte runnerimage; docker + timeout nodig)
#   REC_PG_INTEGRATION=...  schakelt scripts/tests/test_integration_pg.py in (Postgres);
#                          dat bestand bewaakt dit zelf en meldt zich anders als skip
#
# Overig:
#   VERIFY_ROOT=<map>      repo-root overschrijven (voor de hermetische test in
#                          scripts/tests/test_verify.bats); standaard de map boven scripts/
#
# Werkt onder macOS /bin/bash 3.2: geen mapfile, geen associatieve arrays.

set -uo pipefail

ROOT_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${VERIFY_ROOT:-$ROOT_DEFAULT}"
INTEGRATION_BATS="test_compose_runner_exec.bats"

usage() {
  cat <<'EOF'
Gebruik: bash scripts/verify.sh [--only bats|py|shellcheck] [--help]

Draait alle bats-, Python-unittest- en shellcheck-controles van de repo en
geeft een samenvatting met pass/fail-aantallen en alle overgeslagen tests.
Exit 0 alleen als alle onderdelen slagen; anders 1.

  --only <onderdeel>   draai alleen bats, py of shellcheck
  --help               deze tekst

Omgeving:
  VERIFY_INTEGRATION=1   ook test_compose_runner_exec.bats (echte image, docker + timeout)
  REC_PG_INTEGRATION=..  Postgres-integratietest in scripts/tests (zie dat bestand)
  VERIFY_ROOT=<map>      andere repo-root (voor tests van dit script)
EOF
}

ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --only)
      [ $# -ge 2 ] || { echo "verify: --only vraagt een waarde" >&2; exit 2; }
      case "$2" in
        bats|py|shellcheck) ONLY="$2" ;;
        *) echo "verify: onbekend onderdeel '$2' (bats|py|shellcheck)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "verify: onbekend argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

[ -d "$ROOT" ] || { echo "verify: repo-root bestaat niet: $ROOT" >&2; exit 2; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/verify.XXXXXX")" || exit 2
trap 'rm -rf "$TMP"' EXIT
export PYTHONDONTWRITEBYTECODE=1

SUMMARY="$TMP/summary"   # één regel per onderdeel
SKIPS="$TMP/skips"       # één regel per overgeslagen test
EXCL="$TMP/excluded"     # bewust uitgesloten bestanden
FAILS="$TMP/fails"       # namen van gefaalde onderdelen/bestanden
: >"$SUMMARY"; : >"$SKIPS"; : >"$EXCL"; : >"$FAILS"
OVERALL=0

rel() { printf '%s' "${1#"$ROOT"/}"; }

# Geeft de gevonden bestanden (één per regel) voor een glob-paar; tolereert 0 treffers.
list_files() { # $1 = submap-patroonlijst: "dir1 dir2" ; $2 = bestandspatroon
  local d f
  for d in $1; do
    for f in "$ROOT"/$d/$2; do
      [ -e "$f" ] && printf '%s\n' "$f"
    done
  done
  return 0
}

# Toont alleen het relevante deel van falende uitvoer.
show_failure() { # $1 = label, $2 = uitvoerbestand
  echo "---- FAIL: $1 ----"
  sed -e 's/^/    /' "$2" | tail -n 60
  echo "------------------"
}

# ---------------------------------------------------------------- bats
run_bats() {
  local pass=0 fail=0 skip=0 files=0 badfile=0 f rc out counts
  if ! command -v bats >/dev/null 2>&1; then
    echo "bats: NIET GEVONDEN" >&2
    echo "bats|FAIL|0|0|0|bats niet geinstalleerd" >>"$SUMMARY"
    echo "bats" >>"$FAILS"; OVERALL=1; return
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ "$(basename "$f")" = "$INTEGRATION_BATS" ] && [ "${VERIFY_INTEGRATION:-0}" != "1" ]; then
      echo "$(rel "$f")  (integratie; zet VERIFY_INTEGRATION=1)" >>"$EXCL"
      continue
    fi
    files=$((files + 1))
    out="$TMP/bats.$files.out"
    ( cd "$(dirname "$f")/.." && bats --tap "tests/$(basename "$f")" ) >"$out" 2>&1
    rc=$?
    # TAP: "ok N naam", "ok N naam # skip reden", "not ok N naam"
    counts="$(awk -v file="$(rel "$f")" -v skips="$SKIPS" '
      /^ok [0-9]+ /   { if ($0 ~ / # skip/) {
                          s++; name=$0; sub(/^ok [0-9]+ /,"",name)
                          reason=name; sub(/.* # skip ?/,"",reason); sub(/ # skip.*/,"",name)
                          if (reason=="") reason="(geen reden opgegeven)"
                          print "bats  " file ": " name "  -- " reason >> skips
                        } else p++ }
      /^not ok [0-9]+ / { fl++ }
      END { printf "%d %d %d\n", p, fl, s }' "$out")"
    # shellcheck disable=SC2086
    set -- $counts
    pass=$((pass + $1)); fail=$((fail + $2)); skip=$((skip + $3))
    if [ "$rc" -ne 0 ]; then
      # rc != 0 zonder "not ok" (bv. syntaxfout in het bestand) telt ook als falen
      [ "$2" -eq 0 ] && fail=$((fail + 1))
      printf '%s\n' "${f#"$ROOT"/}" >>"$FAILS"
      badfile=1
      show_failure "$(rel "$f")" "$out"
    fi
  done < <(list_files "forgejo-runner/tests scripts/tests" "*.bats")
  local status=PASS
  if [ "$fail" -gt 0 ] || [ "$badfile" -eq 1 ]; then
    status=FAIL; OVERALL=1
  fi
  echo "bats|$status|$pass|$fail|$skip|$files bestand(en)" >>"$SUMMARY"
}

# ---------------------------------------------------------------- python
run_py() {
  local pass=0 fail=0 skip=0 xfail=0 xpass=0 files=0 f rc out counts rel_f status=PASS
  if ! command -v python3 >/dev/null 2>&1; then
    echo "py|FAIL|0|0|0|python3 niet gevonden|0" >>"$SUMMARY"
    echo "py" >>"$FAILS"; OVERALL=1; return
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    files=$((files + 1))
    rel_f="$(rel "$f")"
    out="$TMP/py.$files.out"
    # vanuit de map boven tests/ (zoals de README): paden in de tests zijn daaraan relatief
    ( cd "$(dirname "$f")/.." && PYTHONUNBUFFERED=1 python3 "tests/$(basename "$f")" -v ) >"$out" 2>&1
    rc=$?
    # Verbose-regels: "test_x (mod.Class.test_x) ... ok|FAIL|ERROR|skipped 'reden'|expected failure|unexpected success".
    # Een test mag tussen "..." en het resultaat nog uitvoer printen; het resultaat staat
    # dan op een eigen regel. Daarom onthoudt de parser de lopende test (pending).
    counts="$(awk -v file="$rel_f" -v skips="$SKIPS" '
      function result(r,   reason) {
        if (r == "ok") p++
        else if (r == "FAIL" || r == "ERROR") fl++
        else if (r == "expected failure") x++
        else if (r == "unexpected success") u++
        else if (r ~ /^skipped /) {
          s++; reason=r; sub(/^skipped /,"",reason); gsub(/^["\047]|["\047]$/,"",reason)
          print "py    " file ": " pending "  -- " reason >> skips
        } else return 0
        pending=""; return 1
      }
      /^Ran [0-9]+ tests? in / { ran=$2 }
      {
        if (match($0, / \.\.\. /)) {
          name=substr($0,1,RSTART-1); rest=substr($0,RSTART+RLENGTH)
          pending=name
          if (result(rest)) next
          pending=name; next
        }
        if (pending != "") result($0)
      }
      END { printf "%d %d %d %d %d %d\n", p, fl, s, x, u, ran }' "$out")"
    # shellcheck disable=SC2086
    set -- $counts
    pass=$((pass + $1)); fail=$((fail + $2)); skip=$((skip + $3)); xfail=$((xfail + $4)); xpass=$((xpass + $5))
    if [ "$rc" -eq 0 ] && [ $(($1 + $2 + $3 + $4 + $5)) -ne "$6" ]; then
      echo "verify: telling klopt niet voor $rel_f (geteld $(($1 + $2 + $3 + $4 + $5)), unittest meldt $6)" >>"$out"
      rc=1
    fi
    if [ "$rc" -ne 0 ] || [ "$2" -gt 0 ] || [ "$5" -gt 0 ]; then
      [ "$2" -eq 0 ] && [ "$5" -eq 0 ] && fail=$((fail + 1))
      echo "$rel_f" >>"$FAILS"
      status=FAIL
      show_failure "$rel_f" "$out"
    fi
  done < <(list_files "forgejo-runner/tests scripts/tests" "test_*.py")
  [ "$status" = FAIL ] && OVERALL=1
  fail=$((fail + xpass))   # een onverwacht slagende expectedFailure is een falen
  echo "py|$status|$pass|$fail|$skip|$files bestand(en)|$xfail" >>"$SUMMARY"
}

# ---------------------------------------------------------------- shellcheck
run_shellcheck() {
  local n=0 bad=0 findings=0 f dir base out rc shebang status=PASS list
  if ! command -v shellcheck >/dev/null 2>&1; then
    echo "shellcheck|FAIL|0|0|0|shellcheck niet geinstalleerd" >>"$SUMMARY"
    echo "shellcheck" >>"$FAILS"; OVERALL=1; return
  fi
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    list="$(git -C "$ROOT" ls-files '*.sh')"
  else
    list="$(cd "$ROOT" && find . -name '*.sh' -not -path './.git/*' | sed 's|^\./||' | sort)"
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -f "$ROOT/$f" ] || continue
    n=$((n + 1))
    dir="$(dirname "$ROOT/$f")"; base="$(basename "$f")"
    shebang="$(head -n 1 "$ROOT/$f")"
    out="$TMP/sc.$n.out"
    case "$shebang" in
      '#!/bin/sh'*|'#!/usr/bin/env sh'*) ( cd "$dir" && shellcheck -x -s sh "$base" ) >"$out" 2>&1; rc=$? ;;
      *)                                 ( cd "$dir" && shellcheck -x "$base" ) >"$out" 2>&1; rc=$? ;;
    esac
    if [ "$rc" -ne 0 ]; then
      bad=$((bad + 1))
      findings=$((findings + $(grep -c '^In .* line [0-9]' "$out")))
      echo "$f" >>"$FAILS"
      show_failure "$f" "$out"
    fi
  done <<EOF
$list
EOF
  [ "$bad" -gt 0 ] && { status=FAIL; OVERALL=1; }
  echo "shellcheck|$status|$((n - bad))|$bad|0|$n bestand(en), $findings bevinding(en)" >>"$SUMMARY"
}

# ---------------------------------------------------------------- uitvoeren
START="$(date +%s)"
[ -z "$ONLY" ] || [ "$ONLY" = bats ]       && run_bats
[ -z "$ONLY" ] || [ "$ONLY" = py ]         && run_py
[ -z "$ONLY" ] || [ "$ONLY" = shellcheck ] && run_shellcheck
END="$(date +%s)"

echo
echo "================ verify: samenvatting ================"
printf '%-11s %-5s %6s %6s %6s  %s\n' onderdeel stand pass fail skip details
while IFS='|' read -r name status pass fail skip detail xfail; do
  [ -n "$name" ] || continue
  [ -n "${xfail:-}" ] && detail="$detail, expected failure: $xfail"
  printf '%-11s %-5s %6s %6s %6s  %s\n' "$name" "$status" "$pass" "$fail" "$skip" "$detail"
done <"$SUMMARY"

echo
if [ -s "$SKIPS" ]; then
  echo "Overgeslagen tests ($(wc -l <"$SKIPS" | tr -d ' ')):"
  sed -e 's/^/  /' "$SKIPS"
else
  echo "Overgeslagen tests: geen"
fi
if [ -s "$EXCL" ]; then
  echo
  echo "Bewust niet gedraaid (opt-in):"
  sed -e 's/^/  /' "$EXCL"
fi
if [ -s "$FAILS" ]; then
  echo
  echo "Gefaald:"
  sed -e 's/^/  /' "$FAILS"
fi
echo
if [ "$OVERALL" -eq 0 ]; then
  echo "RESULTAAT: GESLAAGD ($((END - START))s)"
else
  echo "RESULTAAT: GEFAALD ($((END - START))s)"
fi
exit "$OVERALL"
