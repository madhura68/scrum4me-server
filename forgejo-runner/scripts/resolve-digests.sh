#!/usr/bin/env bash
# forgejo-runner/scripts/resolve-digests.sh
# Zet een mutable tag om in een registry-gevalideerde digest.
# Een lokale image-ID telt niet: §4 van het migratieontwerp eist dat de digest
# vanaf de registry bevestigd is.
#
# Geeft de INDEX-digest (manifest list) terug, niet de digest van één
# platform-manifest. Dat is de digest die `docker pull <tag>` in RepoDigests
# vastlegt en waarmee images.json uit stap A dus vergelijkbaar is. Voor een tag
# met één enkel manifest is het simpelweg die manifest-digest.
set -euo pipefail

[ $# -gt 0 ] || { printf 'gebruik: resolve-digests.sh TAG [TAG...]\n' >&2 ; exit 2 ; }

for tag in "$@"; do
  digest="$(docker buildx imagetools inspect "$tag" --format '{{.Manifest.Digest}}' 2>/dev/null || true)"
  [[ "$digest" == sha256:* ]] || { printf 'kon geen digest resolven voor %s\n' "$tag" >&2 ; exit 1 ; }
  repo="${tag%%:*}"
  printf '%s\t%s@%s\n' "$tag" "$repo" "$digest"
done
