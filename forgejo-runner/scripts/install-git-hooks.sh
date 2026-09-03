#!/usr/bin/env bash
# forgejo-runner/scripts/install-git-hooks.sh
# Installeert secret-scan.sh als pre-commit hook in een werkboom.
# Respecteert core.hooksPath: staat die gezet, dan installeert hij daar.
set -euo pipefail

WERKBOOM="${1:-}"
if [ -z "$WERKBOOM" ] || { [ ! -d "$WERKBOOM/.git" ] && [ ! -f "$WERKBOOM/.git" ]; }; then
  printf 'gebruik: install-git-hooks.sh WERKBOOM\n' >&2 ; exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_PATH="$(git -C "$WERKBOOM" config --get core.hooksPath || true)"
if [ -n "$HOOKS_PATH" ]; then
  case "$HOOKS_PATH" in
    /*) DOEL="$HOOKS_PATH" ;;
    *)  DOEL="$WERKBOOM/$HOOKS_PATH" ;;
  esac
else
  DOEL="$(git -C "$WERKBOOM" rev-parse --git-path hooks)"
  case "$DOEL" in
    /*) : ;;
    *)  DOEL="$WERKBOOM/$DOEL" ;;
  esac
fi
mkdir -p "$DOEL"

cat > "$DOEL/pre-commit" <<EOS
#!/usr/bin/env bash
# Geinstalleerd door forgejo-runner/scripts/install-git-hooks.sh
exec "$SCRIPT_DIR/secret-scan.sh"
EOS
chmod +x "$DOEL/pre-commit"
printf 'pre-commit hook geinstalleerd in %s\n' "$DOEL"
