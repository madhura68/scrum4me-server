#!/usr/bin/env bash
# forgejo-runner/scripts/secret-scan.sh
# Blokkeert secrets voordat ze in Git belanden (§6.1).
# Zonder argumenten scant hij de staged blobs (inclusief hernoemde bestanden);
# met argumenten scant hij die bestanden uit de werkboom.
# Exit 0 schoon, 70 bij een treffer, 71 als de scan zelf niet kon draaien
# (fail closed: een scan die niets kan lezen mag nooit als schoon gelden).
# Alle treffers worden gemeld, niet alleen de eerste, zodat één commitpoging
# het hele plaatje geeft.
# Bash-3.2-veilig (macOS): geen mapfile, geen process substitution voor git.
set -uo pipefail

FOUT=71

TMPDIR_SCAN="$(mktemp -d)" || { printf 'secret-scan: kan geen tijdelijke map maken\n' >&2 ; exit "$FOUT"; }
trap 'rm -rf "$TMPDIR_SCAN"' EXIT
INHOUD="$TMPDIR_SCAN/inhoud"
LIJST="$TMPDIR_SCAN/lijst"

# Staged modus leest de blob uit de index, niet het werkbestand: `git add -p`
# kan een secret stagen terwijl het werkbestand schoon is.
MODUS=staged
if [ "$#" -gt 0 ]; then
  MODUS=argumenten
  : > "$LIJST"
  for pad in "$@"; do printf '%s\0' "$pad" >> "$LIJST"; done
else
  if ! git diff --cached --name-only -z --diff-filter=ACMR > "$LIJST"; then
    printf 'secret-scan: git diff --cached faalde; scan niet uitgevoerd\n' >&2
    exit "$FOUT"
  fi
fi

# Waarde-tokens die legitiem in de bundel staan worden uit de regel gehaald
# vóór het matchen, niet de hele regel uitgesloten: een uitzondering die de
# regel meeneemt laat een echte token erachter ongemoeid.
strip_toegestaan() {
  sed -E \
    -e 's/sha256:[0-9a-fA-F]{64}/ /g' \
    -e 's/token_url/ /g' \
    -e 's/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/ /g'
}

# Sleutelnaam (naam mag eromheen doorlopen, zoals de compose-hook), optionele
# aanhalingstekens, : of =, dan een waarde van minstens 20 tekens. De waarde
# begint niet met / (pad, zoals de bindmount van het tokenbestand) en niet met
# $ (interpolatie). Testfixtures gebruiken een waarde < 20 tekens.
# "credential" telt alleen als eindstuk van de sleutelnaam: zonder die beperking
# blokkeert CREDENTIAL_ERROR: State.CREDENTIAL_ERROR in de cyclecontroller.
TOKEN_RE='((token|secret|password|passwd|pass|api_key|apikey|private_key|dsn|database_url)[A-Za-z0-9_]*|credentials?)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9_+=.-][A-Za-z0-9_/+=.-]{19,}'

TREFFER=0
while IFS= read -r -d '' pad; do
  # 1. Bestandsnamen die per definitie een secret dragen. .env.example is de
  #    bundelsjabloon zonder waarden en valt hier bewust buiten.
  naam="${pad##*/}"
  case "$naam" in
    .env.example) : ;;
    forgejo-token|.env|.env.*|*.env|*.key|*.pem|*.token)
      printf 'secret-scan: %s is een secretbestand en hoort niet in Git\n' "$pad" >&2
      TREFFER=1 ; continue ;;
  esac

  if [ "$MODUS" = staged ]; then
    if ! git show ":$pad" > "$INHOUD"; then
      printf 'secret-scan: kan de staged inhoud van %s niet lezen; scan niet uitgevoerd\n' "$pad" >&2
      exit "$FOUT"
    fi
  else
    [ -f "$pad" ] || continue
    if ! cat -- "$pad" > "$INHOUD"; then
      printf 'secret-scan: kan %s niet lezen; scan niet uitgevoerd\n' "$pad" >&2
      exit "$FOUT"
    fi
  fi

  # 2. Private sleutels (PKCS#1, PKCS#8, versleuteld, OPENSSH, PGP, ...).
  if grep -qE 'BEGIN [A-Z ]*PRIVATE KEY' "$INHOUD"; then
    printf 'secret-scan: %s bevat een private sleutel\n' "$pad" >&2
    TREFFER=1 ; continue
  fi

  # 3. Een token-achtige waarde achter een sleutelnaam, in yaml-, env- of
  #    json-vorm, hoofdletterongevoelig (ISS-8 was RUNNER_REGISTRATION_TOKEN=...).
  if strip_toegestaan < "$INHOUD" | grep -qiE "$TOKEN_RE"; then
    printf 'secret-scan: %s bevat een tokenachtige waarde\n' "$pad" >&2
    TREFFER=1 ; continue
  fi
done < "$LIJST"

[ "$TREFFER" -eq 0 ] || exit 70
