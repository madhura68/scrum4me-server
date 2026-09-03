#!/usr/bin/env bash
# forgejo-runner/scripts/secret-scan.sh
# Blokkeert secrets voordat ze in Git belanden (§6.1).
# Zonder argumenten scant hij de staged bestanden.
# Exit 0 schoon, 70 bij een treffer. Alle treffers worden gemeld, niet alleen
# de eerste, zodat één commitpoging het hele plaatje geeft.
set -uo pipefail

bestanden=("$@")
if [ "${#bestanden[@]}" -eq 0 ]; then
  mapfile -t bestanden < <(git diff --cached --name-only --diff-filter=ACM)
fi
[ "${#bestanden[@]}" -gt 0 ] || exit 0

TREFFER=0
for pad in "${bestanden[@]}"; do
  [ -f "$pad" ] || continue

  # 1. Bestandsnamen die per definitie een secret dragen. .env.example is de
  #    bundelsjabloon zonder waarden en valt hier bewust buiten.
  case "$(basename "$pad")" in
    forgejo-token|*.key|*.pem|.env)
      printf 'secret-scan: %s is een secretbestand en hoort niet in Git\n' "$pad" >&2
      TREFFER=1 ; continue ;;
  esac

  # 2. Private sleutels.
  if grep -qE 'BEGIN (OPENSSH|RSA|EC|PGP|DSA) PRIVATE KEY' "$pad"; then
    printf 'secret-scan: %s bevat een private sleutel\n' "$pad" >&2
    TREFFER=1 ; continue
  fi

  # 3. Een token-achtige waarde achter een sleutelnaam, in yaml-, env- of
  #    json-vorm. Hoofdletterongevoelig: het lek van 31 augustus (ISS-8) was
  #    RUNNER_REGISTRATION_TOKEN=... in env-vorm. Digests, UUID's en de
  #    token_url-placeholder vallen bewust buiten: die staan legitiem in de
  #    bundel. De waarde mag niet met / beginnen: dan is het een pad, zoals
  #    de bindmount van het tokenbestand in compose.yaml.
  #    GEEN inhoud-gebaseerde uitzondering: een marker die met de regel
  #    meereist zou de gate laten omzeilen door hem aan een echte tokenregel
  #    toe te voegen. Testfixtures die een token nodig hebben gebruiken daarom
  #    een waarde die te kort is (<20 tekens) of duidelijk geen echt secret.
  if grep -niE '(token|secret|password)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9_+-][A-Za-z0-9_/+-]{19,}' "$pad" \
     | grep -vE 'sha256:|token_url|[0-9a-f]{8}-[0-9a-f]{4}-' >/dev/null; then
    printf 'secret-scan: %s bevat een tokenachtige waarde\n' "$pad" >&2
    TREFFER=1 ; continue
  fi
done

[ "$TREFFER" -eq 0 ] || exit 70
