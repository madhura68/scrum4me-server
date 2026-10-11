#!/usr/bin/env bats
# forgejo-runner/tests/test_verify_stack.bats
# De driftgate uit §6.1 en de isolatiegate uit §7.5: iedere faaltak moet
# aantoonbaar kunnen falen (60 commit-drift, 61 bundelhash-drift, 62
# hostlistener, 63 unit-drift, 64 eigendom, 65 DinD-guard, 66 stackinvariant),
# want een gate die niet kan falen is geen gate. Met --stacks (R17) kijkt de gate
# naar meerdere stacks; zonder --stacks en zonder ingeschakelde template-instantie
# is het gedrag dat van vóór R17. Het script leest het uitrolrecord, de systemd-map en `ss` via
# overschrijfbare paden en `stat` via een stub, zodat dit zonder host (en op
# macOS) kan draaien.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/verify-stack.sh"
  HASHER="$REPO_ROOT/forgejo-runner/scripts/bundle-hash.sh"
  BUNDLE="$BATS_TEST_TMPDIR/bundel"
  mkdir -p "$BUNDLE/scripts"
  cp "$HASHER" "$BUNDLE/scripts/bundle-hash.sh"
  cp "$SCRIPT" "$BUNDLE/scripts/verify-stack.sh"
  cp "$REPO_ROOT/forgejo-runner/scripts/dind-guard.sh" "$BUNDLE/scripts/dind-guard.sh"
  for f in stack_invariants.py cycle_runtime.py forgejo_runner_cycle.py; do
    cp "$REPO_ROOT/forgejo-runner/scripts/$f" "$BUNDLE/scripts/$f"
  done
  echo "a" > "$BUNDLE/compose.yaml"
  # De template zit in de bundel maar staat pas onder SYSTEMD_DIR na fase 2b stap 5.
  echo "template" > "$BUNDLE/forgejo-runner-cycle@.service"
  export STACKS_DIR="$BATS_TEST_TMPDIR/stacks"
  export SYSTEMD_DIR="$BATS_TEST_TMPDIR/systemd"
  mkdir -p "$SYSTEMD_DIR"
  for u in forgejo-runner-cycle.service forgejo-runner-dind-guard.service forgejo-runner-trust.service forgejo-runner-trust.timer; do
    echo "unit $u" > "$BUNDLE/$u"
    cp "$BUNDLE/$u" "$SYSTEMD_DIR/$u"
  done
  export BUNDLE_COMMIT_FILE="$BATS_TEST_TMPDIR/BUNDLE_COMMIT"
  echo "abc123" > "$BUNDLE_COMMIT_FILE"
  HASH="$(bash "$HASHER" "$BUNDLE")"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  printf '#!/usr/bin/env bash\ncat "%s/ss.txt"\n' "$BATS_TEST_TMPDIR" > "$FAKE_BIN/ss"
  chmod +x "$FAKE_BIN/ss"
  printf 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n' > "$BATS_TEST_TMPDIR/ss.txt"
  # stat-stub: standaard root (uid 0) en modus 755. Een bestand in $STATD overschrijft de
  # uitvoer ("uid modus"), eerst op het volledige pad (slashes als %: zie stat_zet), dan op
  # de bestandsnaam. Met alleen de bestandsnaam zouden .env en controller.toml van twee
  # stacks botsen.
  export STATD="$BATS_TEST_TMPDIR/stat"
  mkdir -p "$STATD"
  cat > "$FAKE_BIN/stat" <<'EOF'
#!/usr/bin/env bash
p="${3}"
f="$STATD/${p//\//%}"
[ -f "$f" ] || f="$STATD/$(basename "$p")"
if [ -f "$f" ]; then cat "$f"; else echo "0 755"; fi
EOF
  chmod +x "$FAKE_BIN/stat"
  # DinD-guard (T-188): fake iptables (regels in een bestand), docker (container
  # met IP 172.30.0.2) en timeout (exit 0 = de verbinding lukte, 1 = geweigerd).
  export REGELS="$BATS_TEST_TMPDIR/regels"
  for p in 2375 2376; do
    echo "OUTPUT -o fr-dind+ -p tcp --dport $p -j REJECT --reject-with tcp-reset" >> "$REGELS"
  done
  cat > "$FAKE_BIN/iptables" <<'FAKE'
#!/usr/bin/env bash
[ "$1" = "-w" ] && shift
[ "$1" = "-C" ] || exit 9
shift
grep -qxF -- "$*" "$REGELS"
FAKE
  export IPTABLES="$FAKE_BIN/iptables"
  # docker-stub: `ps` geeft "ID PROJECT"-regels uit dind-ps, `inspect <id>` de IP's uit
  # ip-<id> (standaard 172.30.0.2), `compose -p <project> ... config` de canned JSON.
  cat > "$FAKE_BIN/docker" <<'FAKE'
#!/usr/bin/env bash
case "$1" in
  ps) cat "$BATS_TEST_TMPDIR/dind-ps" ;;
  inspect)
    f="$BATS_TEST_TMPDIR/ip-${@: -1}"
    if [ -f "$f" ]; then cat "$f"; else echo "172.30.0.2 "; fi ;;
  compose)
    project=""; prev=""
    for a in "$@"; do [ "$prev" = "-p" ] && project="$a"; prev="$a"; done
    cat "$BATS_TEST_TMPDIR/compose-$project.json" ;;
esac
FAKE
  # stack_invariants.py draait docker compose met een schone omgeving (zonder BATS_TEST_TMPDIR):
  # het pad staat dus vast in de stub.
  sed -i.bak "s#\$BATS_TEST_TMPDIR#$BATS_TEST_TMPDIR#g" "$FAKE_BIN/docker"
  rm -f "$FAKE_BIN/docker.bak"
  echo "abc forgejo-runner" > "$BATS_TEST_TMPDIR/dind-ps"
  # timeout-stub: exit 0 = de verbinding lukte (bereikbaar). probe-connect geldt voor alle
  # IP's, probe-connect-<ip> voor één IP; anders 1 = geweigerd. Het IP is het 5e argument
  # (timeout 3 bash -c SCRIPT ip poort).
  cat > "$FAKE_BIN/timeout" <<'FAKE'
#!/usr/bin/env bash
[ -f "$BATS_TEST_TMPDIR/probe-connect" ] || [ -f "$BATS_TEST_TMPDIR/probe-connect-$5" ]
FAKE
  chmod +x "$FAKE_BIN/iptables" "$FAKE_BIN/docker" "$FAKE_BIN/timeout"
  PATH="$FAKE_BIN:$PATH"
}

verify() { bash "$BUNDLE/scripts/verify-stack.sh" "$@"; }

@test "groen bij juiste commit, juiste hash en geen listener" {
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"isolatie: OK"* ]]
  [[ "$output" == *"guard: OK"* ]]
  [[ "$output" == *"commit: abc123"* ]]
}

@test "ontbrekend BUNDLE_COMMIT is exit 60" {
  rm -f "$BUNDLE_COMMIT_FILE"
  run verify abc123 "$HASH"
  [ "$status" -eq 60 ]
}

@test "afwijkende commit is exit 60 en noemt beide waarden" {
  echo "def456" > "$BUNDLE_COMMIT_FILE"
  run verify abc123 "$HASH"
  [ "$status" -eq 60 ]
  [[ "$output" == *"def456"* ]]
  [[ "$output" == *"abc123"* ]]
}

@test "afwijkende bundelhash is exit 61" {
  run verify abc123 "afwijkende-hash"
  [ "$status" -eq 61 ]
}

@test "gewijzigde bundelinhoud op de host is exit 61" {
  echo "gemuteerd op de host" >> "$BUNDLE/compose.yaml"
  run verify abc123 "$HASH"
  [ "$status" -eq 61 ]
}

@test "hostlistener op 2375 is exit 62" {
  printf 'LISTEN 0 128 0.0.0.0:2375 0.0.0.0:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
}

@test "hostlistener op 2376 is exit 62 en een poort als 23750 niet" {
  printf 'LISTEN 0 128 [::]:23750 [::]:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  printf 'LISTEN 0 128 [::]:2376 [::]:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
}

@test "commit-drift gaat voor hash-drift: eerst weten welke commit er staat" {
  echo "def456" > "$BUNDLE_COMMIT_FILE"
  run verify abc123 "afwijkende-hash"
  [ "$status" -eq 60 ]
}

@test "ontbrekende ss is exit 62 (isolatie niet te controleren)" {
  rm "$FAKE_BIN/ss"
  SCHOON="$BATS_TEST_TMPDIR/schoon"
  mkdir -p "$SCHOON"
  for t in bash cat cmp find sort awk grep dirname sha256sum shasum env; do
    p="$(command -v "$t" 2>/dev/null || true)"
    if [ -n "$p" ]; then ln -s "$p" "$SCHOON/$t"; fi
  done
  ln -s "$FAKE_BIN/stat" "$SCHOON/stat"
  PATH="$SCHOON" run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
  [[ "$output" == *"ss ontbreekt"* ]]
}

@test "ontbrekende geinstalleerde unit is exit 63" {
  rm "$SYSTEMD_DIR/forgejo-runner-trust.timer"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
  [[ "$output" == *"forgejo-runner-trust.timer"* ]]
}

@test "afwijkende geinstalleerde unit is exit 63" {
  echo "handmatig aangepast" >> "$SYSTEMD_DIR/forgejo-runner-cycle.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
  [[ "$output" == *"forgejo-runner-cycle.service"* ]]
}

@test "bundelbestand van een andere eigenaar is exit 64" {
  echo "1000 644" > "$BATS_TEST_TMPDIR/stat/compose.yaml"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"compose.yaml"* ]]
}

@test "groepsschrijfbaar bundelbestand is exit 64" {
  echo "0 664" > "$BATS_TEST_TMPDIR/stat/forgejo-runner-cycle.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
}

@test "wereldschrijfbaar script is exit 64" {
  echo "0 757" > "$BATS_TEST_TMPDIR/stat/bundle-hash.sh"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
}

@test "bundelmap van een andere eigenaar is exit 64" {
  echo "1000 755" > "$BATS_TEST_TMPDIR/stat/bundel"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"bundelmap"* ]]
}

@test "schrijfbare map met gehashte bestanden is exit 64, ook als bestanden en bytes kloppen" {
  # Wie de map kan schrijven kan een root-eigendom-bestand erin hernoemen of
  # vervangen; de bestandscontrole alleen vangt dat niet (R16 review, ronde 1).
  echo "0 775" > "$BATS_TEST_TMPDIR/stat/scripts"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"scripts"* ]]
}

@test "map van een andere eigenaar is exit 64" {
  echo "1000 755" > "$BATS_TEST_TMPDIR/stat/scripts"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"scripts"* ]]
}

@test "ook een diepere tussenmap zonder eigen bestanden wordt gecontroleerd" {
  mkdir -p "$BUNDLE/scripts/lib/x"
  echo "m" > "$BUNDLE/scripts/lib/x/m.sh"
  HASH="$(bash "$HASHER" "$BUNDLE")"
  echo "0 777" > "$BATS_TEST_TMPDIR/stat/lib"
  run verify abc123 "$HASH"
  [ "$status" -eq 64 ]
  [[ "$output" == *"lib"* ]]
}

@test "root-eigendom met modus 644 en 755 is groen" {
  echo "0 644" > "$BATS_TEST_TMPDIR/stat/compose.yaml"
  echo "0 755" > "$BATS_TEST_TMPDIR/stat/bundle-hash.sh"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
}

@test "ontbrekende argumenten zijn een gebruiksfout" {
  run verify abc123
  [ "$status" -eq 2 ]
}

@test "ontbrekende firewallregel is exit 65" {
  : > "$REGELS"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
  [[ "$output" == *"guardfout"* ]]
}

@test "DinD-API bereikbaar vanaf de host is exit 65" {
  touch "$BATS_TEST_TMPDIR/probe-connect"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
  [[ "$output" == *"172.30.0.2:2375"* ]]
}

@test "geen draaiende DinD-container is exit 65 (fail-closed)" {
  : > "$BATS_TEST_TMPDIR/dind-ps"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
}

@test "een ss die zelf faalt is exit 62 en geen groene isolatie (R16 review)" {
  # Zonder gemeten uitvoer is er niets bewezen; falen mag niet lezen als "geen listener".
  printf '#!/usr/bin/env bash\nexit 3\n' > "$FAKE_BIN/ss"
  run verify abc123 "$HASH"
  [ "$status" -eq 62 ]
  [[ "$output" == *"ss faalde"* ]]
}

@test "een proef die zelf niet kan draaien (timeout exit 125) is exit 65, geen geslaagde guard" {
  printf '#!/usr/bin/env bash\nexit 125\n' > "$FAKE_BIN/timeout"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
  [[ "$output" == *"kon niet draaien"* ]]
}

@test "een verbinding die blijft hangen (timeout exit 124) telt als niet bereikbaar" {
  printf '#!/usr/bin/env bash\nexit 124\n' > "$FAKE_BIN/timeout"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"guard: OK"* ]]
}

@test "ontbrekende dind-guard-unit op de host is exit 63" {
  rm "$SYSTEMD_DIR/forgejo-runner-dind-guard.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
}

# ---------------------------------------------------------------------------
# Meerdere stacks (R17, M52 T4): --stacks, --pre-start, exit 66
# ---------------------------------------------------------------------------

stat_zet() { printf '%s\n' "$2" > "$STATD/${1//\//%}"; }

# De bestanden van één stack: map (stack 02 = de bundelmap), per-stack-env, controller.toml,
# runner-config, state/, credentials/ en de canned `docker compose config`-JSON.
maak_stack() {   # id [bridge] [volume]
  local id="$1" n bridge volume m project envregel=""
  n=$(( 10#$id - 2 ))
  bridge="${2:-fr-dind$n}"
  if [ "$id" = 02 ]; then
    m="$BUNDLE"; project=forgejo-runner; volume="${3:-forgejo-runner-dind-data}"
  else
    m="$STACKS_DIR/$id"; project="forgejo-runner-$id"; volume="${3:-forgejo-runner-$id-dind-data}"
    envregel="env_file = \"$m/.env\""
  fi
  mkdir -p "$m/credentials" "$m/state"
  printf 'geheim-%s' "$id" > "$m/credentials/forgejo-token"
  : > "$m/runner-config.yml"
  cat > "$m/.env" <<ENV
# per-stack-env stack $id
DIND_IMAGE=docker.io/library/docker@sha256:aaaa
RUNNER_IMAGE=code.forgejo.org/forgejo/runner@sha256:bbbb
DIND_CPU_QUOTA=1150000
DIND_MEM=5368709120
STACK_BRIDGE=$bridge
STACK_VOLUME=$volume
STACK_CONFIG=$m/runner-config.yml
STACK_TOKEN=$m/credentials/forgejo-token
ENV
  cat > "$m/controller.toml" <<TOML
[forgejo]
base_url = "https://git.jp-visser.nl"
probe_timeout_seconds = 5
[dind]
compose_file = "$BUNDLE/compose.yaml"
project = "$project"
$envregel
marker_path = "$m/state/cycle-op.marker"
[runner]
allowed_images_file = "/opt/forgejo-runner/allowed-job-images.txt"
child_stop_grace_seconds = 200
[trust]
verdict_path = "$m/trust-verdict.json"
verdict_max_age_seconds = 86400
labels_file = "/opt/forgejo-runner/labels.txt"
allowlist_file = "/opt/forgejo-runner/trusted-actions-scope.yml"
[docker]
subprocess_timeout_seconds = 30
[cadence]
poll_interval_seconds = 1
retry_interval_seconds = 30
[log]
level = "INFO"
TOML
  python3 - "$project" "$bridge" "$volume" "$m/runner-config.yml" "$m/credentials/forgejo-token" \
    > "$BATS_TEST_TMPDIR/compose-$project.json" <<'PY'
import json, sys
project, bridge, volume, config, token = sys.argv[1:]
print(json.dumps({
    "name": project,
    "networks": {"runner-control": {"driver": "bridge", "driver_opts": {"com.docker.network.bridge.name": bridge}}},
    "volumes": {"dind-data": {"name": volume}},
    "services": {"runner": {"volumes": [
        {"type": "bind", "source": config, "target": "/etc/forgejo-runner/config.yml"},
        {"type": "bind", "source": token, "target": "/run/forgejo-runner-credentials/forgejo-token"}]}},
}))
PY
}

dinds() { printf '%s\n' "$@" > "$BATS_TEST_TMPDIR/dind-ps"; }
sjabloon_installeren() { cp "$BUNDLE/forgejo-runner-cycle@.service" "$SYSTEMD_DIR/"; }
instantie_inschakelen() {
  mkdir -p "$SYSTEMD_DIR/multi-user.target.wants"
  ln -s "$SYSTEMD_DIR/forgejo-runner-cycle@.service" "$SYSTEMD_DIR/multi-user.target.wants/forgejo-runner-cycle@03.service"
}
# Stack 02 en 03 volledig voorbereid, template geïnstalleerd, beide DinD's draaiend.
twee_stacks() {
  maak_stack 02; maak_stack 03; sjabloon_installeren
  dinds "abc forgejo-runner" "def forgejo-runner-03"
  echo "172.31.0.2 " > "$BATS_TEST_TMPDIR/ip-def"
}

@test "twee volledig voorbereide stacks zijn groen en de uitvoer noemt de stacks" {
  twee_stacks
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
  [[ "$output" == *"stacks: 02 03"* ]]
  [[ "$output" == *"stackinvarianten: OK"* ]]
}

@test "alleen stack 02 aangekondigd is groen" {
  maak_stack 02; sjabloon_installeren
  run verify abc123 "$HASH" --stacks "02"
  [ "$status" -eq 0 ]
}

@test "zonder --stacks en zonder link is de uitvoer die van vóór R17" {
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  [[ "$output" != *"stacks:"* ]]
  [[ "$output" != *"stackinvarianten"* ]]
}

@test "gebruiksfouten van de opties zijn exit 2" {
  run verify abc123 "$HASH" --pre-start
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --stacks "03"          # 02 ontbreekt
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --stacks "02 02"        # dubbel
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --stacks "02 x3"        # geen tweecijferig id
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --stacks ""
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --stacks
  [ "$status" -eq 2 ]
  run verify abc123 "$HASH" --onbekend
  [ "$status" -eq 2 ]
}

# --- 63: de template ------------------------------------------------------

@test "template geïnstalleerd zonder ingeschakelde instantie: geen exit 63" {
  sjabloon_installeren
  echo "afwijkend" >> "$SYSTEMD_DIR/forgejo-runner-cycle@.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]          # geen link en geen --stacks: gedrag als vóór R17
}

@test "ingeschakelde instantie zonder template onder SYSTEMD_DIR is exit 63" {
  instantie_inschakelen        # een link naar een template die er niet staat
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
  [[ "$output" == *"forgejo-runner-cycle@.service"* ]]
}

@test "ingeschakelde instantie met een afwijkende template is exit 63, ook zonder --stacks" {
  sjabloon_installeren; instantie_inschakelen
  echo "afwijkend" >> "$SYSTEMD_DIR/forgejo-runner-cycle@.service"
  run verify abc123 "$HASH"
  [ "$status" -eq 63 ]
}

@test "ingeschakelde instantie met de juiste template is groen zonder --stacks" {
  sjabloon_installeren; instantie_inschakelen
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
}

@test "met --stacks wordt de template altijd vergeleken: ontbrekend is exit 63" {
  maak_stack 02
  run verify abc123 "$HASH" --stacks "02"
  [ "$status" -eq 63 ]
}

# --- 64: eigendom van de per-stack-bestanden ---------------------------------

@test "per-stack-env van stack 03 die groepsschrijfbaar is, is exit 64 en laat stack 02 groen" {
  twee_stacks
  stat_zet "$STACKS_DIR/03/.env" "0 664"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
  [[ "$output" == *"stacks/03/.env"* ]]
}

@test "controller.toml, runner-config, state en stackmap van stack 03: elk een eigen exit 64" {
  twee_stacks
  for bestand in controller.toml runner-config.yml state ""; do
    pad="$STACKS_DIR/03${bestand:+/$bestand}"
    stat_zet "$pad" "1000 755"
    run verify abc123 "$HASH" --stacks "02 03"
    [ "$status" -eq 64 ]
    rm "$STATD/${pad//\//%}"
  done
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
}

@test "een aanwezige marker van een andere eigenaar is exit 64" {
  twee_stacks
  : > "$STACKS_DIR/03/state/cycle-op.marker"
  stat_zet "$STACKS_DIR/03/state/cycle-op.marker" "1000 644"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
  [[ "$output" == *"cycle-op.marker"* ]]
}

@test "een ontbrekend per-stack-bestand is exit 64" {
  twee_stacks
  rm "$STACKS_DIR/03/runner-config.yml"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
  [[ "$output" == *"ontbreekt"* ]]
}

@test "voor stack 02 vallen ook BUNDLE_COMMIT en een aanwezig trust-verdict onder exit 64" {
  twee_stacks
  stat_zet "$BUNDLE_COMMIT_FILE" "1000 644"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
  [[ "$output" == *"BUNDLE_COMMIT"* ]]
  rm "$STATD/${BUNDLE_COMMIT_FILE//\//%}"
  : > "$BUNDLE/trust-verdict.json"
  stat_zet "$BUNDLE/trust-verdict.json" "0 666"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
  [[ "$output" == *"trust-verdict.json"* ]]
}

@test "een afwezig trust-verdict is geen eigendomsfout" {
  twee_stacks
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
}

@test "zonder --stacks blijft de eigendomscontrole die van vóór R17 (de per-stack-bestanden tellen niet mee)" {
  twee_stacks
  stat_zet "$BUNDLE/.env" "1000 666"
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
}

# --- 66: statisch deel (stack_invariants.py) ---------------------------------

@test "dubbele bridge is exit 66" {
  twee_stacks; maak_stack 03 fr-dind0
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"bridge is niet uniek"* ]]
}

@test "dubbel volume is exit 66" {
  twee_stacks; maak_stack 03 fr-dind1 forgejo-runner-dind-data
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"volume is niet uniek"* ]]
}

@test "dubbel tokenbestand (zelfde inhoud onder een ander pad) is exit 66 zonder de inhoud te printen" {
  twee_stacks
  printf 'geheim-02' > "$STACKS_DIR/03/credentials/forgejo-token"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"tokeninhoud is niet uniek"* ]]
  [[ "$output" != *"geheim-02"* ]]
}

@test "afwijkende pins tussen per-stack-envs is exit 66 en noemt alleen de sleutel" {
  twee_stacks
  sed -i.bak 's#^DIND_IMAGE=.*#DIND_IMAGE=docker.io/library/docker@sha256:cccc#' "$STACKS_DIR/03/.env"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"DIND_IMAGE"* ]]
  [[ "$output" != *"cccc"* ]]
}

@test "twee stacks met dezelfde marker_path is exit 66" {
  twee_stacks
  sed -i.bak "s#^marker_path = .*#marker_path = \"$BUNDLE/state/cycle-op.marker\"#" "$STACKS_DIR/03/controller.toml"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"marker_path is niet uniek"* ]]
}

@test "een ontbrekende controller.toml van een aangekondigde stack is exit 64: eerst de eigendomsgate" {
  twee_stacks
  rm "$STACKS_DIR/03/controller.toml"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
}

@test "exit 64 gaat voor exit 66: eigendom vóór stackinvarianten" {
  twee_stacks; maak_stack 03 fr-dind0
  stat_zet "$STACKS_DIR/03/.env" "0 664"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 64 ]
}

@test "exit 66 (statisch) gaat voor exit 62: de invarianten vóór de hostlistener" {
  twee_stacks; maak_stack 03 fr-dind0
  printf 'LISTEN 0 128 0.0.0.0:2375 0.0.0.0:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
}

# --- 66: runtime-deel (setgelijkheid van de DinD-projecten) ----------------------

@test "ontbrekende DinD van stack 03 is exit 66 in de runtime-modus en groen met --pre-start" {
  twee_stacks
  dinds "abc forgejo-runner"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"forgejo-runner-03"* ]]
  run verify abc123 "$HASH" --stacks "02 03" --pre-start
  [ "$status" -eq 0 ]
}

@test "een vreemd project forgejo-runner-04 maskeert een ontbrekende -03 niet" {
  twee_stacks
  dinds "abc forgejo-runner" "ghi forgejo-runner-04"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
  [[ "$output" == *"forgejo-runner-03"* ]]
  [[ "$output" == *"forgejo-runner-04"* ]]
}

@test "een vreemd extra project is exit 66 ook als alle verwachte DinD's draaien" {
  twee_stacks
  dinds "abc forgejo-runner" "def forgejo-runner-03" "ghi forgejo-runner-04"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
}

@test "een DinD van een ander project dan forgejo-runner telt niet mee" {
  twee_stacks
  dinds "abc forgejo-runner" "def forgejo-runner-03" "zzz ander-project"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
}

# --- 65: de gedragsproef over alle DinD's -------------------------------------

@test "de guardproef neemt alle DinD's: bereikbare DinD van stack 03 is exit 65 en noemt zijn IP" {
  twee_stacks
  touch "$BATS_TEST_TMPDIR/probe-connect-172.31.0.2"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 65 ]
  [[ "$output" == *"172.31.0.2:2375"* ]]
}

@test "de guardproef neemt ook zonder --stacks alle bestaande DinD's" {
  twee_stacks
  touch "$BATS_TEST_TMPDIR/probe-connect-172.31.0.2"
  run verify abc123 "$HASH"
  [ "$status" -eq 65 ]
}

@test "een DinD zonder IP is exit 65, ook als een andere DinD wel een IP heeft" {
  twee_stacks
  echo " " > "$BATS_TEST_TMPDIR/ip-def"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 65 ]
}

@test "ontbreekt de DinD van stack 02, dan is het exit 65 (fail-closed), ook als -03 draait" {
  twee_stacks
  dinds "def forgejo-runner-03"
  run verify abc123 "$HASH" --stacks "02 03" --pre-start
  [ "$status" -eq 65 ]
}

@test "alleen de oude fr-dind0-regels zijn exit 65: de wildcardregels ontbreken" {
  twee_stacks
  : > "$REGELS"
  for p in 2375 2376; do
    echo "OUTPUT -o fr-dind0 -p tcp --dport $p -j REJECT --reject-with tcp-reset" >> "$REGELS"
  done
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 65 ]
}

@test "een hostlistener is exit 62 ook met --stacks, en vóór exit 65" {
  twee_stacks
  printf 'LISTEN 0 128 0.0.0.0:2376 0.0.0.0:*\n' >> "$BATS_TEST_TMPDIR/ss.txt"
  touch "$BATS_TEST_TMPDIR/probe-connect"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 62 ]
}

# --- de vier toestanden van de uitrolvolgorde (plan T4, fase 3) ------------------

@test "volgorde: template geïnstalleerd, instantie niet ingeschakeld: groen zonder --stacks" {
  sjabloon_installeren
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
}

@test "volgorde: voorbereid (stack 03 heeft nog geen DinD): --pre-start groen, runtime exit 66" {
  twee_stacks
  dinds "abc forgejo-runner"
  run verify abc123 "$HASH" --stacks "02 03" --pre-start
  [ "$status" -eq 0 ]
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 66 ]
}

@test "volgorde: alleen DinD (controller gestopt): statisch en runtime groen, geen link" {
  twee_stacks
  run verify abc123 "$HASH" --stacks "02 03" --pre-start
  [ "$status" -eq 0 ]
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
}

@test "volgorde: runner ingeschakeld: alle controles plus de guardproef op beide DinD's" {
  twee_stacks; instantie_inschakelen
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 0 ]
  run verify abc123 "$HASH"
  [ "$status" -eq 0 ]
  touch "$BATS_TEST_TMPDIR/probe-connect-172.31.0.2"
  run verify abc123 "$HASH" --stacks "02 03"
  [ "$status" -eq 65 ]
}
