# Proef van `doctortoets` na de delta van 30 september 2026

Bewijs bij D1 van de delta in [implementatieplan-forgejo-17.0.md](../../implementatieplan-forgejo-17.0.md)
(Review record, "Delta 30 september 2026"). Er is geen host geraakt: de invoer zijn de doctor-logs die het
15.0.9-venster in de repository heeft vastgelegd, de functies zijn uit het planbestand geëxtraheerd.

## 1. Wat er beproefd is

In het 15.0.9-venster werd `doctortoets` rood op een waarschuwing die in beide logs stond en waarin alleen
het aantal verschilde: verweesde repo-archieven, 261 → 32 na een herstart. De delta geeft `doctortoets`
precies één uitzondering: de waarschuwing `Found N/N (… /…) orphaned repo archive(s)`, in dezelfde check als
in het vóór-log, met een gelijk of lager aantal, telt niet als nieuw en komt als `G`-regel in de uitvoer.
Per check mag er niet meer van die waarschuwingen zijn dan vóór; een hoger aantal is nieuw. De vijf andere
functies (`doctorlog`, `doctorschoon`, `doctorsamenvatting`, `doctorvolledig`, `doctorbaseline`) zijn niet
gewijzigd.

De eerste versie (delta-ronde 1, commit `615b616`) normaliseerde getallen in alle `[W]`-regels. De reviewer
toonde dat daarmee `Found 0 broken repositories` → `Found 9 broken repositories` en een extra gelijkvormige
waarschuwing groen werden; die versie draait hieronder mee als derde kolom.

## 2. Invoer en reproductie

Echte logs, branch `ops/forgejo-15.0.9`, commit `9dd9763` (PR #81), map
`docs/forgejo-runner-pool/evidence/forgejo-15.0.9/`:

| Bestand in de proef | Pad in die map | Regels | sha256 |
|---|---|---|---|
| `doctor-pre-venster.log` | `doctor-pre-venster.log` (stap 2.6, 15.0.2, 15:25 lokaal) | 653 | `eb0a207016e81a5ecb882af4a763353dd33e2a8ac5c53c01fcfec2c52f607054` |
| `doctor-post.log` | `doctor-post.log` (stap 4.5, 15.0.9, 15:31 lokaal) | 555 | `910c13364e7e7d6572bc9e0ccea41ac0d61c7a5d8ff298fe1ff096d72aedb5f0` |
| `fase0-doctor-pre.log` | `fase0/doctor-pre.log` (stap 0.4, 15.0.2, 15:11 lokaal) | 653 | `80d5e93267ce4a6310e5a9e3167c95244d9b29e4bb331f515e2a4bf3523fe860` |

Functieblokken, telkens van `doctorlog() {` tot en met de sluitaccolade van `doctortoets`:

| Bestand in de proef | Bron | sha256 |
|---|---|---|
| `oud.sh` | het plan op de GO-commit `e650382` | `a3b9b3e1754c9a2ef2bc1f4c6a8d984d22279502b5fa9b369234ff51954008b1` |
| `ronde1.sh` | het plan op `615b616` (delta-ronde 1) | `a72396b3c1d4edd109cd042fb3285ff29a01b183f635ade70ec827635115eb2d` |
| `nieuw.sh` | het plan na de fix van ronde 1 (de commit die dit bestand begeleidt) | `9ff00d32dc3db8e0d4280c5023a974aaeddeb51f705ed58a6b946c10992e628e` |

Tot de regel `doctortoets() {` zijn de drie bestanden byte-gelijk.

Reproductie vanaf de repository-root, op een checkout van de branch met de delta:

```sh
ex() { awk '/^doctorlog\(\) \{/{p=1} p{print} p&&/^}$/&&f{exit} /^doctortoets\(\)/{f=1}'; }
P=docs/forgejo-runner-pool/implementatieplan-forgejo-17.0.md; E=docs/forgejo-runner-pool/evidence/forgejo-15.0.9; D=$(mktemp -d)
git show e650382:$P | ex > "$D/oud.sh"
git show 615b616:$P | ex > "$D/ronde1.sh"
ex < $P > "$D/nieuw.sh"
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
# Proef van doctortoets na delta-ronde 1: de echte doctor-logs van het 15.0.9-venster + foutinvoer.
# /d/oud.sh = functieblok op de GO-commit e650382, /d/ronde1.sh = blok op 615b616 (delta-ronde 1), /d/nieuw.sh = blok na de fix van ronde 1.
source /d/oud.sh;    eval "$(declare -f doctortoets | sed '1s/doctortoets/doctortoets_go/')"
source /d/ronde1.sh; eval "$(declare -f doctortoets | sed '1s/doctortoets/doctortoets_r1/')"
source /d/nieuw.sh
echo "awk: $(readlink -f "$(command -v awk)") | $(sed --version 2>/dev/null | head -1) | bash $BASH_VERSION"
P=/d/doctor-pre-venster.log; Q=/d/doctor-post.log; F=/d/fase0-doctor-pre.log; T=$(mktemp -d)
geval() { echo; echo "=== $1"; shift; "$@" 2>&1 | cut -c1-210; local n=${PIPESTATUS[0]} g r
          doctortoets_go "$2" "$3" >/dev/null 2>&1; g=$?; doctortoets_r1 "$2" "$3" >/dev/null 2>&1; r=$?
          echo "exit=$n (GO-commit: $g, ronde 1: $r)"; }
mk() { printf '%s\n' "$@"; }
A1='Check if there are orphaned archives in storage'
# --- afgeleid van de echte logs
awk '/^\[4\] /{print; print " - [W] iets heel anders"; next} {print}' "$Q" > $T/nieuw-w.log
sed 's/orphaned repo archive(s)/orphaned repo bundle(s)/; s/Found 32\/32/Found 31\/31/' "$Q" > $T/getal-en-woord.log
sed 's/Key on line 2 of/Key on line 7 of/' "$P" > $T/e-getal.log
awk '!d && /scrum4me\.git\/hooks\/update\.d\/gitea is out of date/ { sub(/scrum4me\.git/, "scrum5me.git"); d = 1 } {print}' "$P" > $T/pad-cijfer.log
awk '/^\[3\] /{c=1} c && /^OK$/ {print "ERROR"; c=0; next} {print}' "$Q" | sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 20\/20 (150 MiB\/150 MiB)/' > $T/ok-wordt-error.log
awk '/^\[4\] /{print; print " - [W] Found 5/5 (1 MiB/1 MiB) orphaned repo archive(s)"; next} {print}' "$Q" > $T/andere-check.log
sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 5000\/5000 (40 GiB\/40 GiB)/' "$Q" > $T/stijgt.log
sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 32\/32 (219 MiB\/219 MiB)/' "$Q" > $T/zelfde-aantal.log
awk '/^\[3\] /{print; print " - [W] Found 7/7 (9 MiB/9 MiB) orphaned repo archive(s)"; next} {print}' "$Q" > $T/extra-archief.log
awk '/^\[3\] /{print; print " - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)"; next} {print}' "$Q" > $T/dubbel-archief.log
sed "s/orphaned repo archive(s)\$/orphaned repo archive(s)$(printf '\t')en meer/" "$Q" > $T/archief-tab.log
grep -v 'orphaned repo archive' "$Q" > $T/w-weg.log
awk '/^\[3\] /{c=1} c && /^OK$/ {exit} {print}' "$Q" > $T/afgebroken.log
sed 's/^All done (checks: 28)\.$/All done (checks: 27)./' "$Q" > $T/telfout.log
: > $T/leeg.log
# --- synthetisch (de gevallen van de reviewer uit ronde 1 en varianten)
mk '[1] Een' 'OK' '[2] Twee' ' - [W] Found 0 broken repositories' ' - [W] count=3 repos' 'OK' '' 'All done (checks: 2).' > $T/syn-voor.log
mk '[1] Een' 'OK' '[2] Twee' ' - [W] Found 9 broken repositories' ' - [W] count=3 repos' 'OK' '' 'All done (checks: 2).' > $T/syn-stijgt.log
mk '[1] Een' 'OK' '[2] Twee' ' - [W] Found 0 broken repositories' ' - [W] Found 9 broken repositories' ' - [W] count=3 repos' 'OK' '' 'All done (checks: 2).' > $T/syn-extra.log
mk '[1] Een' 'OK' '[2] Twee' ' - [W] Found 0 broken repositories' ' - [W] count=4 repos' 'OK' '' 'All done (checks: 2).' > $T/syn-vast.log
mk '[1] Check paths and basic configuration' 'OK' 'Error whilst initializing the database: db.InitEngine: connection refused' > $T/syn-dbinit.log

echo; echo "##### A. de echte logs"
geval " 1. de les: vóór het venster (15.0.2) → na (15.0.9), archieven 261 → 32" doctortoets "$P" "$Q"
geval " 2. 0.4 → 2.6 van dat venster, archieven 259 → 261 (hoger)"            doctortoets "$F" "$P"
geval " 3. identiek log"                                                      doctortoets "$Q" "$Q"
echo; echo "=== 4. omgekeerd (15.0.9 → 15.0.2): ERROR, [E]-regels, 88 hook-[W]-regels en het hogere archiefaantal zijn nieuw"
doctortoets "$Q" "$P" > $T/uit4.txt 2>&1; n=$?; cut -c1 $T/uit4.txt | sort | uniq -c | tr -s ' \n' ' '; echo; grep -E '^(G|V)|archive' $T/uit4.txt | cut -c1-150; tail -1 $T/uit4.txt
doctortoets_go "$Q" "$P" >/dev/null 2>&1; g=$?; doctortoets_r1 "$Q" "$P" >/dev/null 2>&1; echo "exit=$n (GO-commit: $g, ronde 1: $?)"

echo; echo "##### B. foutinvoer: wat rood moet zijn"
geval " 5. een [W]-regel die alleen een getal verandert, 0 → 9 broken (reviewer ronde 1)" doctortoets $T/syn-voor.log $T/syn-stijgt.log
geval " 6. een extra gelijkvormige [W]-regel (reviewer ronde 1)"                       doctortoets $T/syn-voor.log $T/syn-extra.log
geval " 7. getal vast aan een woord (count=3 → count=4)"                               doctortoets $T/syn-voor.log $T/syn-vast.log
geval " 8. het archiefaantal stijgt (32 → 5000)"                                       doctortoets "$Q" $T/stijgt.log
geval " 9. een tweede archiefwaarschuwing in dezelfde check"                            doctortoets "$Q" $T/extra-archief.log
geval "10. dezelfde archiefwaarschuwing twee keer in dezelfde check"                    doctortoets "$Q" $T/dubbel-archief.log
geval "11. archiefwaarschuwing onder een check die hem niet had"                       doctortoets "$Q" $T/andere-check.log
geval "12. archiefregel: getal én een woord anders"                                    doctortoets "$Q" $T/getal-en-woord.log
geval "13. archiefregel met een tab en extra tekst erachter"                           doctortoets "$Q" $T/archief-tab.log
geval "14. check OK → ERROR terwijl zijn archiefaantal daalt"                          doctortoets "$Q" $T/ok-wordt-error.log
geval "15. een nieuwe [W]-regel met andere tekst"                                      doctortoets "$Q" $T/nieuw-w.log
geval "16. [E]-regel waarin alleen een getal verschilt (line 2 → line 7)"              doctortoets "$P" $T/e-getal.log
geval "17. [W]-regel: een cijfer in een padnaam anders (scrum4me → scrum5me)"          doctortoets "$P" $T/pad-cijfer.log

echo; echo "##### C. wat groen is"
geval "18. archiefaantal gelijk, grootte anders (218 → 219 MiB)"                       doctortoets "$Q" $T/zelfde-aantal.log
geval "19. de archiefwaarschuwing verdwijnt"                                           doctortoets "$Q" $T/w-weg.log

echo; echo "##### D. volledigheid en fail-closed (gedrag van de GO-commit)"
geval "20. vóór-log ontbreekt"                                                        doctortoets $T/bestaat-niet.log "$Q"
geval "21. na-log leeg"                                                               doctortoets "$P" $T/leeg.log
geval "22. na-log afgebroken: check zonder verdict"                                   doctortoets "$P" $T/afgebroken.log
geval "23. afsluitregel noemt een ander aantal dan er verdicts zijn"                  doctortoets "$P" $T/telfout.log
geval "24. na-log: vroege return na de eerste check"                                  doctortoets "$P" $T/syn-dbinit.log
echo; echo "=== 25. de vergelijking zelf faalt (awk-stub: alleen het vergelijkende programma geeft exit 3)"
awk() { case "$*" in *gezien*) return 3 ;; *) command awk "$@" ;; esac; }
doctortoets "$P" "$Q"; echo "exit=$?"
unset -f awk
docker() { mk '[1] Een' 'OK' '[2] Twee'; return 42; }                    # doctor-stub: breekt af met exit 42
echo; echo "=== 26. keten van 4.5 / R4 stap 6 met een doctor die met exit 42 afbreekt"
doctorlog scrum4me-forgejo $T/r4.log && doctortoets "$P" $T/r4.log; echo "keten-exit=$?"
docker() { cat "$Q"; return 0; }                                          # doctor-stub: gezond, het echte na-log
echo; echo "=== 27. keten van 4.5 gezond, met de echte logs van de les"
doctorlog scrum4me-forgejo $T/post.log && doctortoets "$P" $T/post.log | cut -c1-210; echo "keten-exit=${PIPESTATUS[0]}"
```

## 4. Uitvoer (`ubuntu:24.04`)

```text
awk: /usr/bin/mawk | sed (GNU sed) 4.9 | bash 5.2.21(1)-release

##### A. de echte logs

===  1. de les: vóór het venster (15.0.2) → na (15.0.9), archieven 261 → 32
G	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 waarschuwing(en) over verweesde repo-archieven met een gelijk of lager aantal — de G-regels hierboven vastleggen)
exit=0 (GO-commit: 1, ronde 1: 0)

===  2. 0.4 → 2.6 van dat venster, archieven 259 → 261 (hoger)
I	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 0)

===  3. identiek log
DOCTOR OK (volledige run, geen nieuwe bevindingen)
exit=0 (GO-commit: 0, ronde 1: 0)

=== 4. omgekeerd (15.0.9 → 15.0.2): ERROR, [E]-regels, 88 hook-[W]-regels en het hogere archiefaantal zijn nieuw
 1 D 95 I 1 V 
I	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
V	Check if OpenSSH authorized_keys file is up-to-date	ERROR
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

##### B. foutinvoer: wat rood moet zijn

===  5. een [W]-regel die alleen een getal verandert, 0 → 9 broken (reviewer ronde 1)
I	Twee	 - [W] Found 9 broken repositories
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 0)

===  6. een extra gelijkvormige [W]-regel (reviewer ronde 1)
I	Twee	 - [W] Found 9 broken repositories
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 0)

===  7. getal vast aan een woord (count=3 → count=4)
I	Twee	 - [W] count=4 repos
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

===  8. het archiefaantal stijgt (32 → 5000)
I	Check if there are orphaned archives in storage	 - [W] Found 5000/5000 (40 GiB/40 GiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 5000/5000 (40 GiB/40 GiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 0)

===  9. een tweede archiefwaarschuwing in dezelfde check
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 7/7 (9 MiB/9 MiB) orphaned repo archive(s)
I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 0)

=== 10. dezelfde archiefwaarschuwing twee keer in dezelfde check
I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 0, ronde 1: 0)

=== 11. archiefwaarschuwing onder een check die hem niet had
I	Check if there are orphaned attachments in storage	 - [W] Found 5/5 (1 MiB/1 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 12. archiefregel: getal én een woord anders
I	Check if there are orphaned archives in storage	 - [W] Found 31/31 (218 MiB/218 MiB) orphaned repo bundle(s)
I	Check if there are orphaned storage files	 - [W] Found 31/31 (218 MiB/218 MiB) orphaned repo bundle(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 13. archiefregel met een tab en extra tekst erachter
I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	en meer
I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	en meer
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 14. check OK → ERROR terwijl zijn archiefaantal daalt
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 20/20 (150 MiB/150 MiB) orphaned repo archive(s)
V	Check if there are orphaned archives in storage	ERROR
G	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 20/20 (150 MiB/150 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 15. een nieuwe [W]-regel met andere tekst
I	Check if there are orphaned attachments in storage	 - [W] iets heel anders
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 16. [E]-regel waarin alleen een getal verschilt (line 2 → line 7)
I	Check if OpenSSH authorized_keys file is up-to-date	 - [E] Key on line 7 of /data/git/.ssh/authorized_keys does not exist in database
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 17. [W]-regel: een cijfer in een padnaam anders (scrum4me → scrum5me)
I	Check if hook files are up-to-date and executable	 - [W] new hook file /data/git/repositories/janpeter/scrum5me.git/hooks/update.d/gitea is out of date
DOCTOR ROOD: nieuwe bevindingen hierboven (elke regel die niet met G begint) — beoordelen, onverklaard = STOP
exit=1 (GO-commit: 1, ronde 1: 1)

##### C. wat groen is

=== 18. archiefaantal gelijk, grootte anders (218 → 219 MiB)
G	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 32/32 (219 MiB/219 MiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)	 - [W] Found 32/32 (219 MiB/219 MiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 waarschuwing(en) over verweesde repo-archieven met een gelijk of lager aantal — de G-regels hierboven vastleggen)
exit=0 (GO-commit: 1, ronde 1: 0)

=== 19. de archiefwaarschuwing verdwijnt
DOCTOR OK (volledige run, geen nieuwe bevindingen)
exit=0 (GO-commit: 0, ronde 1: 0)

##### D. volledigheid en fail-closed (gedrag van de GO-commit)

=== 20. vóór-log ontbreekt
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/bestaat-niet.log ontbreekt of is onleesbaar — STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 21. na-log leeg
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/leeg.log bevat geen checkverdicts — STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 22. na-log afgebroken: check zonder verdict
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/afgebroken.log is onvolledig (een check zonder verdict) — STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 23. afsluitregel noemt een ander aantal dan er verdicts zijn
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/telfout.log sluit niet af met "All done (checks: 28)." (gevonden: "27") — de run is niet aantoonbaar volledig — STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 24. na-log: vroege return na de eerste check
DOCTOR ROOD: /tmp/tmp.XXXXXXXXXX/syn-dbinit.log sluit niet af met "All done (checks: 1)." (gevonden: "niets") — de run is niet aantoonbaar volledig — STOP
exit=1 (GO-commit: 1, ronde 1: 1)

=== 25. de vergelijking zelf faalt (awk-stub: alleen het vergelijkende programma geeft exit 3)
DOCTOR ROOD: de vergelijking zelf mislukte — STOP
exit=1

=== 26. keten van 4.5 / R4 stap 6 met een doctor die met exit 42 afbreekt
DOCTOR-RUN MISLUKT (exit 42) — STOP; /tmp/tmp.XXXXXXXXXX/r4.log is onvolledig
keten-exit=1

=== 27. keten van 4.5 gezond, met de echte logs van de les
doctor exit 0 → /tmp/tmp.XXXXXXXXXX/post.log
G	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
G	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR OK (volledige run, geen nieuwe bevindingen; 2 waarschuwing(en) over verweesde repo-archieven met een gelijk of lager aantal — de G-regels hierboven vastleggen)
keten-exit=0
```

## 5. Lezing

- **De les is opgelost (1, 27).** De functie van de GO-commit geeft exit 1 op de logs van het 15.0.9-venster;
  de nieuwe geeft exit 0 en toont de twee archiefregels als `G`-regels met de tekst van vóór en na.
- **De gevallen van de reviewer uit ronde 1 zijn rood (5, 6).** Een `[W]`-regel waarin alleen een getal
  stijgt en een extra gelijkvormige waarschuwing waren groen in de versie van ronde 1 en zijn nu rood, zoals
  in de GO-functie.
- **Een hoger archiefaantal is rood (2, 8).** Ook het echte geval: tussen stap 0.4 en stap 2.6 van het
  15.0.9-venster, een kwartier uiteen op dezelfde draaiende forge, ging het aantal van 259 naar 261. Het plan
  vergelijkt die twee logs niet met `doctortoets`; R.4 wel met een baseline van dagen oud, en daar wordt een
  hoger aantal beoordeeld zoals elke nieuwe bevinding.
- **Per check geteld (9, 10, 11).** Een tweede archiefwaarschuwing in dezelfde check, dezelfde waarschuwing
  twee keer, en de waarschuwing onder een check die hem vóór niet had, zijn nieuw. Geval 10 is het enige
  waarin de nieuwe functie strenger is dan de GO-functie: die las het na-log als verzameling en zag een
  dubbele, identieke regel niet.
- **Alle andere tekst blijft letterlijk (7, 12–17).** Een getal vast aan een woord, een archiefregel met een
  ander woord of met extra tekst na een tab, een check die van `OK` naar `ERROR` gaat, een nieuwe
  `[W]`-regel, een `[E]`-regel met alleen een ander getal en een cijfer in een padnaam: allemaal rood.
- **Volledigheid en fail-closed (20–26)** gedragen zich als in de GO-functie; een mislukte vergelijking geeft
  `DOCTOR ROOD` (25).
- **Samen:** in de 24 gevallen waarin de drie versies zijn vergeleken, verschilt de nieuwe van de GO-functie
  alleen in 1 en 18 (groen bij een lager of gelijk archiefaantal) en in 10 (rood bij een dubbele
  archiefwaarschuwing).
