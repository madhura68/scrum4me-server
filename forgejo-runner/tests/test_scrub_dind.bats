#!/usr/bin/env bats
# forgejo-runner/tests/test_scrub_dind.bats
# De fenced scrub uit §7.9: alles binnen de eigen DinD verdwijnt behalve
# jobimages uit de digest-allowlist, en het BEWIJS achteraf bepaalt de exitcode
# (0 schoon, 50 restobject, 51 tijdsoverschrijding). Het docker-commando is
# een nepper die uit statebestanden leest en iedere aanroep logt.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/forgejo-runner/scripts/scrub-dind.sh"
  ALLOW="$BATS_TEST_TMPDIR/allow.txt"
  echo "catthehacker/ubuntu@sha256:abc	2147483648" > "$ALLOW"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  STATE="$BATS_TEST_TMPDIR/state"
  mkdir -p "$STATE"
  : > "$STATE/containers" ; : > "$STATE/volumes"
  printf 'bridge\nhost\nnone\n' > "$STATE/networks"
  echo "catthehacker/ubuntu@sha256:abc" > "$STATE/images"
  echo "0B" > "$STATE/buildcache"
  : > "$STATE/calls"
  cat > "$FAKE_BIN/docker" <<EOS
#!/usr/bin/env bash
STATE="$STATE"
echo "\$*" >> "\$STATE/calls"
case "\$*" in
  *"ps -aq"*)          cat "\$STATE/containers" ;;
  *"volume ls -q"*)    cat "\$STATE/volumes" ;;
  *"network ls"*)      cat "\$STATE/networks" ;;
  *"images --digests"*|*"image ls"*) cat "\$STATE/images" ;;
  *"system df"*)       printf 'Images\\t1GB\\nContainers\\t0B\\nLocal Volumes\\t0B\\nBuild Cache\\t%s\\n' "\$(cat "\$STATE/buildcache")" ;;
  *"builder prune"*|*"rm "*|*"volume rm"*|*"network rm"*|*"rmi"*) : ;;
esac
EOS
  chmod +x "$FAKE_BIN/docker"
  PATH="$FAKE_BIN:$PATH"
}

scrub() { bash "$SCRIPT" --endpoint tcp://127.0.0.1:2375 --allow "$ALLOW" "$@"; }

@test "schone dind levert exit 0" {
  run scrub
  [ "$status" -eq 0 ]
  [[ "$output" == *"containers: OK"* ]]
  [[ "$output" == *"buildcache: OK"* ]]
}

@test "een achtergebleven container faalt met 50" {
  echo "c1" > "$STATE/containers"
  run scrub
  [ "$status" -eq 50 ]
  [[ "$output" == *"container"* ]]
}

@test "een achtergebleven volume faalt met 50" {
  echo "v1" > "$STATE/volumes"
  run scrub
  [ "$status" -eq 50 ]
}

@test "een niet-standaardnetwerk faalt met 50" {
  echo "vreemd" >> "$STATE/networks"
  run scrub
  [ "$status" -eq 50 ]
}

@test "een image buiten de allowlist faalt met 50" {
  echo "zelfgebouwd@sha256:def" >> "$STATE/images"
  run scrub
  [ "$status" -eq 50 ]
  [[ "$output" == *"image"* ]]
}

@test "resterende buildcache faalt met 50" {
  # §7.9 stap 8: geen buildcache. De plancode ruimde hem op maar bewees het niet.
  echo "512MB" > "$STATE/buildcache"
  run scrub
  [ "$status" -eq 50 ]
  [[ "$output" == *"buildcache: FAIL"* ]]
}

@test "de scrub probeert een niet-toegestane image te verwijderen en een toegestane niet" {
  echo "zelfgebouwd@sha256:def" >> "$STATE/images"
  run scrub
  grep -q 'rmi -f zelfgebouwd@sha256:def' "$STATE/calls"
  run grep -c 'rmi -f catthehacker/ubuntu@sha256:abc' "$STATE/calls"
  [ "$output" = "0" ]
}

@test "een dangling image zonder digest wordt niet als toegestaan gezien" {
  echo "<none>@<none>" >> "$STATE/images"
  run scrub
  [ "$status" -eq 50 ]
}

@test "commentaarregels in de allowlist tellen niet als toegestane image" {
  printf '# uitleg\n\ncatthehacker/ubuntu@sha256:abc\t1\n' > "$ALLOW"
  echo "#@sha256:zzz" >> "$STATE/images"
  run scrub
  [ "$status" -eq 50 ]
}

@test "tijdsoverschrijding faalt met 51" {
  SCRUB_MAX_SECONDS=-1 run scrub
  [ "$status" -eq 51 ]
}

@test "ieder docker-commando gaat naar het opgegeven endpoint" {
  run scrub
  run grep -vc -- '^-H tcp://127.0.0.1:2375 ' "$STATE/calls"
  [ "$output" = "0" ]
}

@test "gebruikt nooit de host-docker-socket" {
  run grep -c 'docker.sock' "$SCRIPT"
  [ "$output" = "0" ]
}

@test "is POSIX sh, want docker:dind is Alpine zonder bash" {
  head -1 "$SCRIPT" | grep -qE '^#!/bin/sh$'
  shellcheck -s sh "$SCRIPT"
}

@test "een ontbrekende allowlist is een gebruiksfout, geen stille scrub" {
  run bash "$SCRIPT" --endpoint tcp://127.0.0.1:2375 --allow "$BATS_TEST_TMPDIR/bestaat-niet"
  [ "$status" -eq 2 ]
}
