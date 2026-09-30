# Proef van `doctortoets` na de delta van 30 september 2026

Bewijs bij D1 van de delta in [implementatieplan-forgejo-17.0.md](../../implementatieplan-forgejo-17.0.md)
(Review record, "Delta 30 september 2026"). Er is geen host geraakt: de invoer zijn de doctor-logs die het
15.0.9-venster in de repository heeft vastgelegd, de functies zijn uit het planbestand geëxtraheerd.

## 1. Wat er beproefd is

In het 15.0.9-venster werd `doctortoets` rood op een waarschuwing die in beide logs stond en waarin alleen
het aantal verschilde (verweesde repo-archieven, 261 → 32). De delta laat `doctortoets` een `[W]`-regel die
alleen in losse getallen of eenheden afwijkt van een `[W]`-regel van dezelfde check in het vóór-log, tonen
als `G`-regel in plaats van als nieuwe bevinding. De vijf andere functies (`doctorlog`, `doctorschoon`,
`doctorsamenvatting`, `doctorvolledig`, `doctorbaseline`) zijn niet gewijzigd.

De proef draait de nieuwe functie en, voor dezelfde invoer, de functie van de GO-commit, zodat zichtbaar is
waar de twee verschillen.

## 2. Invoer en reproductie

Echte logs, branch `ops/forgejo-15.0.9`, commit `9dd9763` (PR #81), map
`docs/forgejo-runner-pool/evidence/forgejo-15.0.9/`:

| Bestand in de proef | Pad in die map | Regels | sha256 |
|---|---|---|---|
| `doctor-pre-venster.log` | `doctor-pre-venster.log` (stap 2.6, 15.0.2, 15:25 lokaal) | 653 | `eb0a207016e81a5ecb882af4a763353dd33e2a8ac5c53c01fcfec2c52f607054` |
| `doctor-post.log` | `doctor-post.log` (stap 4.5, 15.0.9, 15:31 lokaal) | 555 | `910c13364e7e7d6572bc9e0ccea41ac0d61c7a5d8ff298fe1ff096d72aedb5f0` |
| `fase0-doctor-pre.log` | `fase0/doctor-pre.log` (stap 0.4, 15.0.2, 15:11 lokaal) | 653 | `80d5e93267ce4a6310e5a9e3167c95244d9b29e4bb331f515e2a4bf3523fe860` |

Functieblokken: `oud.sh` is het blok van `doctorlog` tot en met `doctortoets` uit het plan op de GO-commit
`e650382` (sha256 `a3b9b3e1754c9a2ef2bc1f4c6a8d984d22279502b5fa9b369234ff51954008b1`), `nieuw.sh` hetzelfde
blok uit het plan na de delta (sha256 `a72396b3c1d4edd109cd042fb3285ff29a01b183f635ade70ec827635115eb2d`).
Tot de regel `doctortoets() {` zijn de twee bestanden byte-gelijk.

Reproductie vanaf de repository-root, op een checkout van de branch met de delta:

```sh
ex() { awk '/^doctorlog\(\) \{/{p=1} p{print} p&&/^}$/&&f{exit} /^doctortoets\(\)/{f=1}'; }
E=docs/forgejo-runner-pool/evidence/forgejo-15.0.9; D=$(mktemp -d)
git show e650382:docs/forgejo-runner-pool/implementatieplan-forgejo-17.0.md | ex > "$D/oud.sh"
ex < docs/forgejo-runner-pool/implementatieplan-forgejo-17.0.md > "$D/nieuw.sh"
git show 9dd9763:$E/doctor-pre-venster.log > "$D/doctor-pre-venster.log"
git show 9dd9763:$E/doctor-post.log        > "$D/doctor-post.log"
git show 9dd9763:$E/fase0/doctor-pre.log   > "$D/fase0-doctor-pre.log"
# het proefscript uit §3 opslaan als "$D/proef.sh", dan:
docker run --rm -v "$D:/d:ro" ubuntu:24.04 bash /d/proef.sh
```

Omgevingen (alle vier geven dezelfde uitvoer, op de kopregel, de naam van de tijdelijke map en de
kolombreedte van `uniq -c` na):

| Omgeving | awk | sed | bash |
|---|---|---|---|
| `ubuntu:24.04` (de uitvoer in §4) | mawk 1.3.4 20240123 | GNU sed 4.9 | 5.2.21 |
| `debian:bookworm` | mawk 1.3.4 20200120 | GNU sed 4.9 | 5.2.15 |
| `postgres:17-alpine` | busybox awk 1.37.0 | busybox sed | 5.3.9 |
| macOS (zonder container, paden aangepast) | awk version 20200816 | BSD sed | 5.3.9 |

Niet gemeten: gawk, en de awk van `scrum4me-server` zelf. Stap 0.6 van het plan noteert welke awk de host
heeft; de eerste run op de host is R.4, dagen vóór het venster.

## 3. Proefscript

```sh
#!/usr/bin/env bash
# Proef van doctortoets na de delta van 30 sep: de echte doctor-logs van het 15.0.9-venster + foutinvoer.
# /d/oud.sh = het functieblok uit het plan op de GO-commit e650382, /d/nieuw.sh = het blok uit het plan na de delta.
source /d/oud.sh; eval "$(declare -f doctortoets | sed '1s/doctortoets/doctortoets_oud/')"
source /d/nieuw.sh
echo "awk: $(readlink -f "$(command -v awk)") | $(sed --version 2>/dev/null | head -1) | bash $BASH_VERSION"
P=/d/doctor-pre-venster.log; Q=/d/doctor-post.log; F=/d/fase0-doctor-pre.log; T=$(mktemp -d)
geval() { echo; echo "=== $1"; shift; "$@" 2>&1 | cut -c1-210; local n=${PIPESTATUS[0]}; doctortoets_oud "$2" "$3" >/dev/null 2>&1; echo "exit=$n (functie van de GO-commit: exit=$?)"; }
mk() { printf '%s\n' "$@"; }
# --- afgeleid van de echte logs
awk '/^\[4\] /{print; print " - [W] iets heel anders"; next} {print}' "$Q" > $T/nieuw-w.log
sed 's/orphaned repo archive(s)/orphaned repo bundle(s)/; s/Found 32\/32/Found 31\/31/' "$Q" > $T/getal-en-woord.log
sed 's/Key on line 2 of/Key on line 7 of/' "$P" > $T/e-getal.log
awk '!d && /scrum4me\.git\/hooks\/update\.d\/gitea is out of date/ { sub(/scrum4me\.git/, "scrum5me.git"); d = 1 } {print}' "$P" > $T/pad-cijfer.log
awk '/^\[3\] /{c=1} c && /^OK$/ {print "ERROR"; c=0; next} {print}' "$Q" | sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 40\/40 (300 MiB\/300 MiB)/' > $T/ok-wordt-error.log
awk '/^\[4\] /{print; print " - [W] Found 5/5 (1 MiB/1 MiB) orphaned repo archive(s)"; next} {print}' "$Q" > $T/andere-check.log
sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 5000\/5000 (40 GiB\/40 GiB)/' "$Q" > $T/stijgt.log
grep -v 'orphaned repo archive' "$Q" > $T/w-weg.log
awk '/^\[3\] /{c=1} c && /^OK$/ {exit} {print}' "$Q" > $T/afgebroken.log
sed 's/^All done (checks: 28)\.$/All done (checks: 27)./' "$Q" > $T/telfout.log
: > $T/leeg.log
# --- synthetisch
mk '[1] Eerste' 'OK' '[2] Tweede' ' - [W] count=3 repos' ' - [W] Found no orphaned things' ' - [W] 3 repositories checked, 2 broken' "$(printf ' - [W] a\tb 1')" 'OK' '' 'All done (checks: 2).' > $T/syn-voor.log
mk '[1] Eerste' 'OK' '[2] Tweede' ' - [W] count=4 repos' ' - [W] Found no orphaned things' ' - [W] 3 repositories checked, 2 broken' "$(printf ' - [W] a\tb 1')" 'OK' '' 'All done (checks: 2).' > $T/syn-vast.log
mk '[1] Eerste' 'OK' '[2] Tweede' ' - [W] count=3 repos' ' - [W] Found 3 orphaned things' ' - [W] 3 repositories checked, 2 broken' "$(printf ' - [W] a\tb 1')" 'OK' '' 'All done (checks: 2).' > $T/syn-woord-wordt-getal.log
mk '[1] Eerste' 'OK' '[2] Tweede' ' - [W] count=3 repos' ' - [W] Found no orphaned things' ' - [W] 7 repositories checked, 0 broken' "$(printf ' - [W] a\tb 1')" 'OK' '' 'All done (checks: 2).' > $T/syn-los.log
mk '[1] Eerste' 'OK' '[2] Tweede' ' - [W] count=3 repos' ' - [W] Found no orphaned things' ' - [W] 3 repositories checked, 2 broken' "$(printf ' - [W] a\tc 2')" 'OK' '' 'All done (checks: 2).' > $T/syn-tab.log
mk '[1] Check paths and basic configuration' 'OK' 'Error whilst initializing the database: db.InitEngine: connection refused' > $T/syn-dbinit.log

echo; echo "##### A. de echte logs"
geval " 1. de les: vóór het venster (15.0.2) → na (15.0.9)"              doctortoets "$P" "$Q"
geval " 2. zelfde versie, een kwartier uiteen, geen herstart: 0.4 → 2.6"  doctortoets "$F" "$P"
geval " 3. identiek log"                                                  doctortoets "$Q" "$Q"
echo; echo "=== 4. omgekeerd (15.0.9 → 15.0.2): een ERROR, [E]-regels en 88 hook-[W]-regels zijn nieuw, de twee getalregels niet"
doctortoets "$Q" "$P" > $T/uit4.txt 2>&1; n=$?; cut -c1 $T/uit4.txt | sort | uniq -c | tr '\n' ' '; echo; grep -E '^(G|V)' $T/uit4.txt | cut -c1-150; tail -1 $T/uit4.txt
doctortoets_oud "$Q" "$P" >/dev/null 2>&1; echo "exit=$n (functie van de GO-commit: exit=$?)"

echo; echo "##### B. foutinvoer: wat rood moet blijven"
geval " 5. een nieuwe [W]-regel met andere tekst"                         doctortoets "$Q" $T/nieuw-w.log
geval " 6. [W]-regel: getal én een woord anders"                          doctortoets "$Q" $T/getal-en-woord.log
geval " 7. [E]-regel waarin alleen een getal verschilt (line 2 → line 7)" doctortoets "$P" $T/e-getal.log
geval " 8. [W]-regel: een cijfer in een padnaam anders (scrum4me → scrum5me)" doctortoets "$P" $T/pad-cijfer.log
geval " 9. check OK → ERROR terwijl zijn [W]-regel alleen in getal verschilt" doctortoets "$Q" $T/ok-wordt-error.log
geval "10. dezelfde [W]-vorm onder een check die hem niet had"            doctortoets "$Q" $T/andere-check.log
geval "11. getal vast aan een woord (count=3 → count=4)"                  doctortoets $T/syn-voor.log $T/syn-vast.log
geval "12. een getal waar eerst een woord stond (no → 3)"                 doctortoets $T/syn-voor.log $T/syn-woord-wordt-getal.log
geval "13. melding met een tab: het deel ná de tab verschilt"             doctortoets $T/syn-voor.log $T/syn-tab.log

echo; echo "##### C. wat groen wordt, met G-regels"
geval "14. losse getallen (3 → 7, 2 → 0)"                                 doctortoets $T/syn-voor.log $T/syn-los.log
geval "15. het getal stijgt sterk (32 → 5000, MiB → GiB)"                 doctortoets "$Q" $T/stijgt.log
geval "16. een [W]-regel verdwijnt"                                       doctortoets "$Q" $T/w-weg.log

echo; echo "##### D. volledigheid en fail-closed (ongewijzigd gedrag)"
geval "17. vóór-log ontbreekt"                                            doctortoets $T/bestaat-niet.log "$Q"
geval "18. na-log leeg"                                                   doctortoets "$P" $T/leeg.log
geval "19. na-log afgebroken: check zonder verdict"                       doctortoets "$P" $T/afgebroken.log
geval "20. afsluitregel noemt een ander aantal dan er verdicts zijn"      doctortoets "$P" $T/telfout.log
geval "21. na-log: vroege return na de eerste check"                      doctortoets "$P" $T/syn-dbinit.log
echo; echo "=== 22. de vergelijking zelf faalt (awk-stub: alleen het vergelijkende programma geeft exit 3)"
awk() { case "$*" in *gezien*) return 3 ;; *) command awk "$@" ;; esac; }
doctortoets "$P" "$Q"; echo "exit=$?"
unset -f awk
docker() { mk '[1] Eerste' 'OK' '[2] Tweede'; return 42; }               # doctor-stub: breekt af met exit 42
echo; echo "=== 23. keten van 4.5 / R4 stap 6 met een doctor die met exit 42 afbreekt"
doctorlog scrum4me-forgejo $T/r4.log && doctortoets "$P" $T/r4.log; echo "keten-exit=$?"
docker() { cat "$Q"; return 0; }                                          # doctor-stub: gezond, het echte na-log
echo; echo "=== 24. keten van 4.5 gezond, met de echte logs van de les"
doctorlog scrum4me-forgejo $T/post.log && doctortoets "$P" $T/post.log | cut -c1-210; echo "keten-exit=${PIPESTATUS[0]}"

echo; echo "##### E. waarom ook eenheden"
echo "=== 25. alleen cijfers vervangen is niet genoeg: de vorm van de echte regel vóór en na blijft dan verschillen"
for f in "$P" "$Q"; do doctorsamenvatting "$f" | awk -F'\t' '$1 == "I" && /orphaned repo archive/ { s = $3; gsub(/[0-9]+([.,][0-9]+)?/, "N", s); print s; exit }'; done
```

## 4. Uitvoer (`ubuntu:24.04`)

```text
awk: /usr/bin/mawk | sed (GNU sed) 4.9 | bash 5.2.21(1)-release

##### A. de echte logs

===  1. de les: vóór het venster (15.0.2) → na (15.0.9)
G	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 bestaande [W]-melding(en) met alleen een ander getal — de G-regels hierboven vastleggen)
exit=0 (functie van de GO-commit: exit=1)

===  2. zelfde versie, een kwartier uiteen, geen herstart: 0.4 → 2.6
G	Check if there are orphaned archives in storage	 - [W] Found 259/259 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 259/259 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 bestaande [W]-melding(en) met alleen een ander getal — de G-regels hierboven vastleggen)
exit=0 (functie van de GO-commit: exit=1)

===  3. identiek log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
exit=0 (functie van de GO-commit: exit=0)

=== 4. omgekeerd (15.0.9 → 15.0.2): een ERROR, [E]-regels en 88 hook-[W]-regels zijn nieuw, de twee getalregels niet
      1 D       2 G      93 I       1 V 
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 261/261 (1.3 GiB/1.3 GiB)
G	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orpha
V	Check if OpenSSH authorized_keys file is up-to-date	ERROR
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

##### B. foutinvoer: wat rood moet blijven

===  5. een nieuwe [W]-regel met andere tekst
I	Check if there are orphaned attachments in storage	 - [W] iets heel anders
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

===  6. [W]-regel: getal én een woord anders
I	Check if there are orphaned archives in storage	 - [W] Found 31/31 (218 MiB/218 MiB) orphaned repo bundle(s)
I	Check if there are orphaned storage files	 - [W] Found 31/31 (218 MiB/218 MiB) orphaned repo bundle(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

===  7. [E]-regel waarin alleen een getal verschilt (line 2 → line 7)
I	Check if OpenSSH authorized_keys file is up-to-date	 - [E] Key on line 7 of /data/git/.ssh/authorized_keys does not exist in database
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

===  8. [W]-regel: een cijfer in een padnaam anders (scrum4me → scrum5me)
I	Check if hook files are up-to-date and executable	 - [W] new hook file /data/git/repositories/janpeter/scrum5me.git/hooks/update.d/gitea is out of date
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

===  9. check OK → ERROR terwijl zijn [W]-regel alleen in getal verschilt
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 40/40 (300 MiB/300 MiB) orphaned repo archive(s)
V	Check if there are orphaned archives in storage	ERROR
G	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 40/40 (300 MiB/300 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

=== 10. dezelfde [W]-vorm onder een check die hem niet had
I	Check if there are orphaned attachments in storage	 - [W] Found 5/5 (1 MiB/1 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

=== 11. getal vast aan een woord (count=3 → count=4)
I	Tweede	 - [W] count=4 repos
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

=== 12. een getal waar eerst een woord stond (no → 3)
I	Tweede	 - [W] Found 3 orphaned things
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

=== 13. melding met een tab: het deel ná de tab verschilt
I	Tweede	 - [W] a	c 2
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (functie van de GO-commit: exit=1)

##### C. wat groen wordt, met G-regels

=== 14. losse getallen (3 → 7, 2 → 0)
G	Tweede	 - [W] 3 repositories checked, 2 broken	 - [W] 7 repositories checked, 0 broken
DOCTOR OK (volledige run, geen nieuwe bevindingen; 1 bestaande [W]-melding(en) met alleen een ander getal — de G-regels hierboven vastleggen)
exit=0 (functie van de GO-commit: exit=1)

=== 15. het getal stijgt sterk (32 → 5000, MiB → GiB)
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 5000/5000 (40 GiB/40 GiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 5000/5000 (40 GiB/40 GiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 bestaande [W]-melding(en) met alleen een ander getal — de G-regels hierboven vastleggen)
exit=0 (functie van de GO-commit: exit=1)

=== 16. een [W]-regel verdwijnt
DOCTOR OK (volledige run, geen nieuwe bevindingen)
exit=0 (functie van de GO-commit: exit=0)

##### D. volledigheid en fail-closed (ongewijzigd gedrag)

=== 17. vóór-log ontbreekt
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/bestaat-niet.log ontbreekt of is onleesbaar — STOP
exit=1 (functie van de GO-commit: exit=1)

=== 18. na-log leeg
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/leeg.log bevat geen checkverdicts — STOP
exit=1 (functie van de GO-commit: exit=1)

=== 19. na-log afgebroken: check zonder verdict
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/afgebroken.log is onvolledig (een check zonder verdict) — STOP
exit=1 (functie van de GO-commit: exit=1)

=== 20. afsluitregel noemt een ander aantal dan er verdicts zijn
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/telfout.log sluit niet af met "All done (checks: 28)." (gevonden: "27") — de run is niet aantoonbaar volledig — STOP
exit=1 (functie van de GO-commit: exit=1)

=== 21. na-log: vroege return na de eerste check
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/syn-dbinit.log sluit niet af met "All done (checks: 1)." (gevonden: "niets") — de run is niet aantoonbaar volledig — STOP
exit=1 (functie van de GO-commit: exit=1)

=== 22. de vergelijking zelf faalt (awk-stub: alleen het vergelijkende programma geeft exit 3)
DOCTOR ROOD: de vergelijking zelf mislukte — STOP
exit=1

=== 23. keten van 4.5 / R4 stap 6 met een doctor die met exit 42 afbreekt
DOCTOR-RUN MISLUKT (exit 42) — STOP; /tmp/tmp.XXXXXXXXXX/r4.log is onvolledig
keten-exit=1

=== 24. keten van 4.5 gezond, met de echte logs van de les
doctor exit 0 → /tmp/tmp.XXXXXXXXXX/post.log
G	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 bestaande [W]-melding(en) met alleen een ander getal — de G-regels hierboven vastleggen)
keten-exit=0

##### E. waarom ook eenheden
=== 25. alleen cijfers vervangen is niet genoeg: de vorm van de echte regel vóór en na blijft dan verschillen
 - [W] Found N/N (N GiB/N GiB) orphaned repo archive(s)
 - [W] Found N/N (N MiB/N MiB) orphaned repo archive(s)
```

## 5. Lezing

- **De les is gereproduceerd en opgelost (1, 24).** De functie van de GO-commit geeft exit 1 op de logs van
  het 15.0.9-venster; de nieuwe geeft exit 0 en toont de twee regels als `G`-regels met de tekst van vóór
  en na.
- **Het getal beweegt ook zonder herstart (2).** Tussen stap 0.4 en stap 2.6 van dat venster, een kwartier
  uiteen op dezelfde draaiende 15.0.2, ging het aantal van 259 naar 261. De oude functie was daar ook rood.
  In dit plan ligt tussen de baseline van 0.4 en de proef van R.4 meer dan een kwartier.
- **Wat rood moet zijn, is rood (4–13, 17–23).** Een nieuwe `[W]`-regel, een `[W]`-regel waarin ook een
  woord verschilt, een `[E]`-regel waarin alleen een getal verschilt, een cijfer in een padnaam, een check
  die van `OK` naar `ERROR` gaat terwijl zijn waarschuwing alleen in getal verschilt, dezelfde vorm onder een
  andere check, een getal dat aan een woord vastzit, een getal op de plaats van een woord, en een melding
  met een tab waarin het deel na de tab verschilt. De volledigheidseisen en de fail-closed-paden gedragen
  zich als voorheen, en een mislukte vergelijking geeft `DOCTOR ROOD` (22).
- **De twee versies verschillen alleen waar dat de bedoeling is.** In de 21 gevallen waarin beide zijn
  gedraaid: vier keer oud rood en nieuw groen (1, 2, 14, 15 — de gevallen met alleen een ander getal),
  vijftien keer beide rood, twee keer beide groen (3, 16).
- **Eenheden horen erbij (25).** Alleen cijfers vervangen laat `GiB` tegenover `MiB` staan; de echte regel
  wisselde van eenheid.

Grenzen van de tolerantie, zoals ze ook in het plan staan: de richting telt niet (15: 32 → 5000 is een
`G`-regel), en een los getal in een `[W]`-regel dat een identificatie is in plaats van een aantal, valt er
ook onder (14 laat zien dat elk los getal meetelt). Daarom worden `G`-regels getoond en vastgelegd en niet
weggelaten.
