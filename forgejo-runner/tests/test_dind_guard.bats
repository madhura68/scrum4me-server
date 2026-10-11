#!/usr/bin/env bats
# forgejo-runner/tests/test_dind_guard.bats
# dind-guard.sh (T-188, R17 §7.5): apply zet de REJECT-regels idempotent op de
# wildcard fr-dind+ (alle stackbridges fr-dind0, fr-dind1, ...), check faalt
# zolang een regel ontbreekt. Een fake iptables houdt de regels in een bestand.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/dind-guard.sh"
  export REGELS="$BATS_TEST_TMPDIR/regels"
  : > "$REGELS"
  export IPTABLES="$BATS_TEST_TMPDIR/iptables"
  cat > "$IPTABLES" <<'FAKE'
#!/usr/bin/env bash
# -w negeren; -C = bestaat de regel, -I OUTPUT 1 = voeg toe.
[ "$1" = "-w" ] && shift
actie="$1"; shift
case "$actie" in
  -C) grep -qxF -- "$*" "$REGELS" ;;
  -I) shift 2; echo "OUTPUT $*" >> "$REGELS" ;;
  *) exit 9 ;;
esac
FAKE
  chmod +x "$IPTABLES"
}

@test "apply zet de regels voor 2375 en 2376 op de wildcard fr-dind+" {
  run bash "$SCRIPT" apply
  [ "$status" -eq 0 ]
  grep -qxF 'OUTPUT -o fr-dind+ -p tcp --dport 2375 -j REJECT --reject-with tcp-reset' "$REGELS"
  grep -qxF 'OUTPUT -o fr-dind+ -p tcp --dport 2376 -j REJECT --reject-with tcp-reset' "$REGELS"
}

@test "apply is idempotent: tweede keer voegt niets toe" {
  bash "$SCRIPT" apply
  bash "$SCRIPT" apply
  [ "$(wc -l < "$REGELS" | tr -d ' ')" = "2" ]
}

@test "check faalt zonder regels en na een halve set" {
  run bash "$SCRIPT" check
  [ "$status" -ne 0 ]
  echo 'OUTPUT -o fr-dind+ -p tcp --dport 2375 -j REJECT --reject-with tcp-reset' > "$REGELS"
  run bash "$SCRIPT" check
  [ "$status" -ne 0 ]
  [[ "$output" == *"2376"* ]]
}

@test "check slaagt na apply" {
  bash "$SCRIPT" apply
  run bash "$SCRIPT" check
  [ "$status" -eq 0 ]
}

@test "onbekende actie is een gebruiksfout" {
  run bash "$SCRIPT" nonsens
  [ "$status" -eq 2 ]
}

@test "overgang: alleen de oude fr-dind0-regels laat check falen; apply voegt de wildcardregels toe en laat de oude staan" {
  # Een host van vóór R17 heeft alleen -o fr-dind0. De wildcard dekt die bridge ook,
  # maar check eist de wildcardregels: pas na apply is de host op de R17-bundel.
  for p in 2375 2376; do
    echo "OUTPUT -o fr-dind0 -p tcp --dport $p -j REJECT --reject-with tcp-reset" >> "$REGELS"
  done
  run bash "$SCRIPT" check
  [ "$status" -ne 0 ]
  run bash "$SCRIPT" apply
  [ "$status" -eq 0 ]
  grep -qxF 'OUTPUT -o fr-dind+ -p tcp --dport 2375 -j REJECT --reject-with tcp-reset' "$REGELS"
  grep -qxF 'OUTPUT -o fr-dind+ -p tcp --dport 2376 -j REJECT --reject-with tcp-reset' "$REGELS"
  run bash "$SCRIPT" check
  [ "$status" -eq 0 ]
  # De oude regels zijn onschadelijk en blijven staan (geen -D, niets om te herstarten).
  grep -qxF 'OUTPUT -o fr-dind0 -p tcp --dport 2375 -j REJECT --reject-with tcp-reset' "$REGELS"
  [ "$(wc -l < "$REGELS" | tr -d ' ')" = "4" ]
}
