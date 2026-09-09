#!/usr/bin/env bats
# forgejo-runner/tests/test_trust_timer_contract.bats
# Contract van de trustscan-timer (§7.7: "Dezelfde controle draait dagelijks").
# De dragende eigenschap is niet dat er een timer bestaat, maar dat zijn cadans
# strikt sneller is dan de vervaldatum die de controllergate hanteert, en dat de
# gepubliceerde paden dezelfde zijn als die de controller uitleest.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  BUNDLE="$REPO_ROOT/forgejo-runner"
  SERVICE="$BUNDLE/forgejo-runner-trust.service"
  TIMER="$BUNDLE/forgejo-runner-trust.timer"
  TOML="$BUNDLE/controller.toml.example"
}

@test "unit bevat geen secrets" {
  run grep -ciE 'token|password|secret' "$SERVICE"
  [ "$output" = "0" ]
}

@test "unit is oneshot met precies een ExecStart" {
  grep -q '^Type=oneshot' "$SERVICE"
  run grep -cE '^ExecStart=' "$SERVICE"
  [ "$output" = "1" ]
  run grep -cE '^ExecStartPre=' "$SERVICE"
  [ "$output" = "0" ]
}

@test "unit draait de deploy-wrapper met alle vijf verplichte vlaggen" {
  # De wrapper exit 2 bij een ontbrekende vlag; dan zou de timer stil niets doen.
  grep -q 'publish-trust-verdict\.sh' "$SERVICE"
  for vlag in --cli-py --labels --allowlist --target --out; do
    grep -q -- "$vlag " "$SERVICE"
  done
}

@test "unit herstelt van een transiente meting zonder always/on-success" {
  # publish-trust-verdict.sh invalideert het actieve verdict fail-closed bij een
  # mislukte meting. Zonder herpoging zet een netwerkhik de pool stil tot de
  # volgende timerslag. Type=oneshot verbiedt always en on-success (systemd).
  grep -qE '^Restart=on-failure$' "$SERVICE"
  grep -qE '^RestartSec=[0-9]' "$SERVICE"
  grep -qE '^StartLimitBurst=[0-9]' "$SERVICE"
  grep -qE '^StartLimitIntervalSec=[0-9]' "$SERVICE"
  run grep -cE '^Restart=(always|on-success)' "$SERVICE"
  [ "$output" = "0" ]
}

@test "unit verhardt het proces en mag alleen de bundel schrijven" {
  grep -q '^NoNewPrivileges=true' "$SERVICE"
  grep -q '^ProtectHome=true' "$SERVICE"
  grep -q '^ProtectSystem=strict' "$SERVICE"
  grep -q '^ReadWritePaths=/opt/forgejo-runner$' "$SERVICE"
  grep -q '^WorkingDirectory=/opt/forgejo-runner$' "$SERVICE"
}

@test "unit is hostonafhankelijk: geen hostnaam buiten de Documentation-URL" {
  run grep -iE 'scrum4me-server|max2' <(grep -v '^Documentation=' "$SERVICE")
  [ "$status" -ne 0 ]
}

@test "de gepubliceerde paden zijn exact de paden die de controller uitleest" {
  # Drift hier betekent dat de timer een verdict schrijft dat de gate nooit leest,
  # of hasht over andere bestanden dan de gate bindt — beide falen stil.
  for veld in verdict_path labels_file allowlist_file; do
    pad="$(awk -F'"' -v v="$veld" '$0 ~ "^" v " *=" {print $2}' "$TOML")"
    [ -n "$pad" ]
    grep -qF -- "$pad" "$SERVICE"
  done
}

@test "de timer slaat strikt vaker dan het verdict verloopt" {
  # De kern van deze unit. verdict_max_age_seconds is de vervaldatum die
  # cycle_runtime.verdict_green hanteert; de grootste gap tussen twee slagen
  # moet daar met marge onder blijven, anders staat de pool tussen twee slagen stil.
  run python3 - "$TIMER" "$TOML" <<'PY'
import re, sys
timer, toml = open(sys.argv[1]).read(), open(sys.argv[2]).read()
max_age = float(re.search(r'^verdict_max_age_seconds\s*=\s*(\d+)', toml, re.M).group(1))
cal = re.search(r'^OnCalendar=(.+)$', timer, re.M).group(1).strip()
uren = sorted(int(u) for u in re.search(r'(\d[\d,]*):\d\d:\d\d$', cal).group(1).split(','))
assert uren, "geen uren in OnCalendar"
gaps = [(b - a) * 3600 for a, b in zip(uren, uren[1:])] + [(uren[0] + 24 - uren[-1]) * 3600]
grootste = max(gaps)
jitter = float(re.search(r'^RandomizedDelaySec=(\d+)', timer, re.M).group(1))
assert grootste + jitter < max_age, f"gap {grootste}+{jitter} >= max_age {max_age}"
# Marge-eis: een enkele gemiste slag mag de pool niet stilzetten.
assert 2 * grootste + jitter < max_age, f"geen marge voor een gemiste slag: {grootste}"
print("ok")
PY
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

@test "de timer haalt in na een boot en spreidt over de twee hosts" {
  grep -q '^Persistent=true' "$TIMER"          # verlopen verdict niet tot de volgende slag laten liggen
  grep -qE '^RandomizedDelaySec=[1-9]' "$TIMER" # beide hosts meten niet op dezelfde seconde
  grep -q '^Unit=forgejo-runner-trust.service' "$TIMER"
  grep -q '^WantedBy=timers.target' "$TIMER"
}
