#!/usr/bin/env bats
# forgejo-runner/tests/test_unit_contract.bats
# Het unitcontract uit §6: de vier verplichte afhankelijkheden, de Python-
# controller als enige ExecStart, een restartbeleid dat de gates niet omzeilt,
# en geen secrets. De units zijn op alle hosts byte-identiek. Het contract geldt
# voor de vaste unit van stack 02 én voor de template van R17 (§5), die per
# stack een eigen controller.toml onder /opt/forgejo-runner-stacks/%i/ leest.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  UNIT="$REPO_ROOT/forgejo-runner/forgejo-runner-cycle.service"
  TEMPLATE="$REPO_ROOT/forgejo-runner/forgejo-runner-cycle@.service"
  UNITS=("$UNIT" "$TEMPLATE")
  GUARD_UNIT="$REPO_ROOT/forgejo-runner/forgejo-runner-dind-guard.service"
}

@test "unit heeft alle vier verplichte afhankelijkheden" {
  for u in "${UNITS[@]}"; do
    grep -q '^Requires=docker.service' "$u"
    grep -q '^After=docker.service network-online.target' "$u"
    grep -q '^Wants=network-online.target' "$u"
    grep -q '^WantedBy=multi-user.target' "$u"
  done
}

@test "unit start de python-controller en geen shellscript" {
  for u in "${UNITS[@]}"; do
    grep -qE '^ExecStart=.*forgejo_runner_cycle\.py' "$u"
    run grep -cE '^ExecStart=.*\.sh' "$u"
    [ "$output" = "0" ]
  done
}

@test "unit herstart niet automatisch op een manier die de gates omzeilt" {
  for u in "${UNITS[@]}"; do
    grep -qE '^Restart=on-failure' "$u"
    grep -qE '^RestartSec=' "$u"
  done
}

@test "unit bevat geen secrets" {
  for u in "${UNITS[@]}"; do
    run grep -ciE 'token|password|secret' "$u"
    [ "$output" = "0" ]
  done
}

@test "unit heeft precies een ExecStart en geen ExecStartPre die gates kan omzeilen" {
  # §7.9: de controller is de ENIGE eigenaar van de levenscyclus. Een
  # ExecStartPre die alvast een runner of DinD start loopt om de gates heen.
  # Voor de template geldt dat dubbel (R17 §5): een falende pre-check geeft met
  # Restart=on-failure een eindeloze herstartlus; een ontbrekende instantie faalt
  # al in het hoofdproces (exit 2 van load_config).
  for u in "${UNITS[@]}"; do
    run grep -cE '^ExecStart=' "$u"
    [ "$output" = "1" ]
    run grep -cE '^ExecStartPre=' "$u"
    [ "$output" = "0" ]
  done
}

@test "unit is hostonafhankelijk: geen hostnaam, geen host-docker-socket" {
  # De Documentation-URL noemt de canonieke repo (scrum4me-server); dat is
  # geen hostafhankelijkheid. Alle andere regels mogen geen host noemen.
  for u in "${UNITS[@]}"; do
    run grep -iE 'scrum4me-server|max2|docker\.sock' <(grep -v '^Documentation=' "$u")
    [ "$status" -ne 0 ]
  done
}

@test "de stoptimeout dekt een gecontroleerde drain" {
  # §7.9: een geplande stop laat een RUNNING job terminaal worden en scrubt
  # (max 5 min). Een korte TimeoutStopSec zou de job halverwege SIGKILLen.
  for u in "${UNITS[@]}"; do
    run awk -F= '/^TimeoutStopSec=/{print $2}' "$u"
    [ "$output" -ge 300 ]
    grep -q '^KillSignal=SIGTERM' "$u"
  done
}

@test "unit verhardt het proces zonder de bundel te breken" {
  for u in "${UNITS[@]}"; do
    grep -q '^NoNewPrivileges=true' "$u"
    grep -q '^ProtectHome=true' "$u"
    grep -q '^WorkingDirectory=/opt/forgejo-runner$' "$u"
  done
}

@test "cycle-unit vereist en volgt de dind-guard-unit (T-188)" {
  for u in "${UNITS[@]}"; do
    grep -q '^Requires=forgejo-runner-dind-guard.service' "$u"
    grep -q '^After=forgejo-runner-dind-guard.service' "$u"
  done
}

@test "de vaste unit blijft op het controller.toml van stack 02" {
  grep -qE '^ExecStart=.* --config /opt/forgejo-runner/controller\.toml$' "$UNIT"
}

@test "de template leest per instantie controller.toml uit de per-stack-map (R17 §5)" {
  grep -qE '^ExecStart=.* --config /opt/forgejo-runner-stacks/%i/controller\.toml$' "$TEMPLATE"
  grep -q '^Description=.*%i' "$TEMPLATE"
}

@test "de template wijkt alleen af in Description en het configpad van de ExecStart" {
  # Een andere afhankelijkheid, restartregel of hardening in alleen de template of
  # alleen de vaste unit (driftgevaar) valt hier op. Commentaarregels tellen niet mee.
  run diff \
    <(grep -vE '^(#|Description=|ExecStart=)' "$UNIT") \
    <(grep -vE '^(#|Description=|ExecStart=)' "$TEMPLATE")
  [ "$status" -eq 0 ]
  # Het ExecStart-commando zelf is gelijk tot aan het configpad.
  run diff \
    <(sed -E 's# --config .*$##' <(grep '^ExecStart=' "$UNIT")) \
    <(sed -E 's# --config .*$##' <(grep '^ExecStart=' "$TEMPLATE"))
  [ "$status" -eq 0 ]
}

@test "de template is een bestand en geen instantie: de bestandsnaam eindigt op @.service" {
  [ -f "$TEMPLATE" ]
  [ "$(basename "$TEMPLATE")" = "forgejo-runner-cycle@.service" ]
}

@test "dind-guard-unit staat vóór docker.service en hangt er niet hard aan (R16 review)" {
  # Een DinD met restart: always komt na een herstart terug zodra Docker start;
  # de regel moet er dan al liggen. Geen Requires=/BindsTo= van Docker op de
  # guard: een falende guard zou Docker en alle hostcontainers stoppen.
  grep -q '^Before=docker.service' "$GUARD_UNIT"
  run grep -E '^(Requires|BindsTo|PartOf|Wants)=.*docker' "$GUARD_UNIT"
  [ "$status" -ne 0 ]
}

@test "dind-guard-unit is een oneshot die dind-guard.sh apply draait" {
  grep -q '^Type=oneshot' "$GUARD_UNIT"
  grep -q '^RemainAfterExit=yes' "$GUARD_UNIT"
  grep -qE '^ExecStart=.*/opt/forgejo-runner/scripts/dind-guard\.sh apply$' "$GUARD_UNIT"
  grep -q '^WantedBy=multi-user.target' "$GUARD_UNIT"
  grep -q '^NoNewPrivileges=true' "$GUARD_UNIT"
}
