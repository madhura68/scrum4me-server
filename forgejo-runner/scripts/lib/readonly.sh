# shellcheck shell=bash
# Read-only guard voor stap A van het runnerpool-migratieontwerp.
# Iedere Docker-aanroep in stap A loopt hierlangs. Alles wat niet expliciet
# read-only is, wordt geweigerd met exitcode 64.

ro_docker_is_allowed() {
  local one="${1:-}" two="${2:-}"
  case "$one $two" in
    "image inspect"|"image ls"|"image history"|\
    "volume ls"|"volume inspect"|\
    "network ls"|"network inspect"|\
    "container inspect"|"container ls"|\
    "system df"|"compose config"|"manifest inspect")
      return 0 ;;
  esac
  case "$one" in
    ps|images|inspect|info|version|logs|stats|top|port|diff)
      return 0 ;;
  esac
  return 1
}

ro_docker() {
  if ! ro_docker_is_allowed "${1:-}" "${2:-}"; then
    printf 'readonly-guard: geweigerd: docker %s\n' "$*" >&2
    return 64
  fi
  docker "$@"
}
