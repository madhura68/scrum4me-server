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

# Een bestaande hook die wij niet hebben gezet (bijvoorbeeld de compose-hook)
# overschrijven we niet: die zou stilletjes verdwijnen.
MARKER='# Geinstalleerd door forgejo-runner/scripts/install-git-hooks.sh'
if [ -e "$DOEL/pre-commit" ] && ! grep -qF "$MARKER" "$DOEL/pre-commit"; then
  printf 'install-git-hooks: %s/pre-commit bestaat al en is niet door dit script geinstalleerd; niet overschreven\n' "$DOEL" >&2
  exit 3
fi

cat > "$DOEL/pre-commit" <<EOS
#!/usr/bin/env bash
$MARKER
exec "$SCRIPT_DIR/secret-scan.sh"
EOS
chmod +x "$DOEL/pre-commit"
printf 'pre-commit hook geinstalleerd in %s\n' "$DOEL"
