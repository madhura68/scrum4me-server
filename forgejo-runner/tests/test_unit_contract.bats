#!/usr/bin/env bats
# forgejo-runner/tests/test_unit_contract.bats
# Het unitcontract uit §6: de vier verplichte afhankelijkheden, de Python-
# controller als enige ExecStart, een restartbeleid dat de gates niet omzeilt,
# en geen secrets. De unit is op beide hosts byte-identiek.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  UNIT="$REPO_ROOT/forgejo-runner/forgejo-runner-cycle.service"
}

@test "unit heeft alle vier verplichte afhankelijkheden" {
  grep -q '^Requires=docker.service' "$UNIT"
  grep -q '^After=docker.service network-online.target' "$UNIT"
  grep -q '^Wants=network-online.target' "$UNIT"
  grep -q '^WantedBy=multi-user.target' "$UNIT"
}

@test "unit start de python-controller en geen shellscript" {
  grep -qE '^ExecStart=.*forgejo_runner_cycle\.py' "$UNIT"
  run grep -cE '^ExecStart=.*\.sh' "$UNIT"
  [ "$output" = "0" ]
}

@test "unit herstart niet automatisch op een manier die de gates omzeilt" {
  grep -qE '^Restart=on-failure' "$UNIT"
  grep -qE '^RestartSec=' "$UNIT"
}

@test "unit bevat geen secrets" {
  run grep -ciE 'token|password|secret' "$UNIT"
  [ "$output" = "0" ]
}

@test "unit heeft precies een ExecStart en geen ExecStartPre die gates kan omzeilen" {
  # §7.9: de controller is de ENIGE eigenaar van de levenscyclus. Een
  # ExecStartPre die alvast een runner of DinD start loopt om de gates heen.
  run grep -cE '^ExecStart=' "$UNIT"
  [ "$output" = "1" ]
  run grep -cE '^ExecStartPre=' "$UNIT"
  [ "$output" = "0" ]
}

@test "unit is hostonafhankelijk: geen hostnaam, geen host-docker-socket" {
  # De Documentation-URL noemt de canonieke repo (scrum4me-server); dat is
  # geen hostafhankelijkheid. Alle andere regels mogen geen host noemen.
  run grep -iE 'scrum4me-server|max2|docker\.sock' <(grep -v '^Documentation=' "$UNIT")
  [ "$status" -ne 0 ]
}

@test "de stoptimeout dekt een gecontroleerde drain" {
  # §7.9: een geplande stop laat een RUNNING job terminaal worden en scrubt
  # (max 5 min). Een korte TimeoutStopSec zou de job halverwege SIGKILLen.
  run awk -F= '/^TimeoutStopSec=/{print $2}' "$UNIT"
  [ "$output" -ge 300 ]
  grep -q '^KillSignal=SIGTERM' "$UNIT"
}

@test "unit verhardt het proces zonder de bundel te breken" {
  grep -q '^NoNewPrivileges=true' "$UNIT"
  grep -q '^ProtectHome=true' "$UNIT"
  grep -q '^WorkingDirectory=/opt/forgejo-runner' "$UNIT"
}
