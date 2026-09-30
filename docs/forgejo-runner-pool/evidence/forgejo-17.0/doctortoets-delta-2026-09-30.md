# De archiefregel bij `doctortoets` — bewijs bij de delta van 30 september 2026

Bewijs bij D1 van de delta in [implementatieplan-forgejo-17.0.md](../../implementatieplan-forgejo-17.0.md)
(Review record, "Delta 30 september 2026"). Er is geen host geraakt: de invoer zijn de doctor-logs die het
15.0.9-venster in de repository heeft vastgelegd.

## 1. Wat er beproefd is

In het 15.0.9-venster werd `doctortoets` rood op een waarschuwing die in beide logs stond en waarin alleen
het aantal verschilde: verweesde repo-archieven, 261 → 32 na een herstart. De delta laat de functies
**ongewijzigd** en geeft de operator een beoordelingsregel, de archiefregel (D1) in het plan: een
`DOCTOR ROOD` met de uitkomst *nieuwe bevindingen hierboven* is verklaard als elke getoonde regel

1. een `I`-regel is met precies de vorm ` - [W] Found A/A (S E/S E) orphaned repo archive(s)`, met twee gelijke
   aantallen en twee gelijke groottes;
2. hoort bij een check die zo'n regel precies één keer in het vóór-log én precies één keer in het na-log
   heeft;
3. een aantal A heeft dat niet hoger is, en een omvang S E die niet groter is, dan in die vóór-regel.

Elke andere getoonde regel is een nieuwe bevinding.

De eerste twee versies van de delta bouwden een uitzondering in `doctortoets` zelf; de reviewer vond in
delta-ronde 1 en 2 telkens een verslechtering die daardoor groen werd (een stijgend aantal in een andere
waarschuwing, een extra waarschuwing, en een lager aantal met een veel grotere omvang). Deze versie haalt
de code-uitzondering weg.

De proef laat zien wat de operator in R.4, 4.5 en R4 stap 6 te zien krijgt: de uitvoer van de
ongewijzigde `doctortoets`, en de archiefregels van vóór en na met het commando dat de archiefregel noemt.
Per geval staat in §4 wat de regel dan zegt.

## 2. Invoer en reproductie

Echte logs, branch `ops/forgejo-15.0.9`, commit `9dd9763` (PR #81), map
`docs/forgejo-runner-pool/evidence/forgejo-15.0.9/`:

| Bestand in de proef | Pad in die map | Regels | sha256 |
|---|---|---|---|
| `doctor-pre-venster.log` | `doctor-pre-venster.log` (stap 2.6, 15.0.2, 15:25 lokaal) | 653 | `eb0a207016e81a5ecb882af4a763353dd33e2a8ac5c53c01fcfec2c52f607054` |
| `doctor-post.log` | `doctor-post.log` (stap 4.5, 15.0.9, 15:31 lokaal) | 555 | `910c13364e7e7d6572bc9e0ccea41ac0d61c7a5d8ff298fe1ff096d72aedb5f0` |
| `fase0-doctor-pre.log` | `fase0/doctor-pre.log` (stap 0.4, 15.0.2, 15:11 lokaal) | 653 | `80d5e93267ce4a6310e5a9e3167c95244d9b29e4bb331f515e2a4bf3523fe860` |

Functieblok `oud.sh`: van `doctorlog() {` tot en met de sluitaccolade van `doctortoets`, sha256
`a3b9b3e1754c9a2ef2bc1f4c6a8d984d22279502b5fa9b369234ff51954008b1`. Dat blok is gelijk in het 17.0-plan op
de GO-commit `e650382`, in het 17.0-plan na deze delta, en in het 15.0.9-plan op `9dd9763`.

```sh
ex() { awk '/^doctorlog\(\) \{/{p=1} p{print} p&&/^}$/&&f{exit} /^doctortoets\(\)/{f=1}'; }
P=docs/forgejo-runner-pool/implementatieplan-forgejo-17.0.md; E=docs/forgejo-runner-pool/evidence/forgejo-15.0.9; D=$(mktemp -d)
ex < $P > "$D/oud.sh"                                        # sha256 a3b9b3e1…, gelijk aan de twee regels hieronder
git show e650382:$P | ex | shasum -a 256
git show 9dd9763:docs/forgejo-runner-pool/implementatieplan-forgejo-15.0.9.md | ex | shasum -a 256
git show 9dd9763:$E/doctor-pre-venster.log > "$D/doctor-pre-venster.log"
git show 9dd9763:$E/doctor-post.log        > "$D/doctor-post.log"
git show 9dd9763:$E/fase0/doctor-pre.log   > "$D/fase0-doctor-pre.log"
# het proefscript uit §3 opslaan als "$D/proef.sh", dan:
docker run --rm -v "$D:/d:ro" ubuntu:24.04 bash /d/proef.sh
```

## 3. Proefscript

```sh
#!/usr/bin/env bash
# Wat de operator ziet: doctortoets (ongewijzigd, GO-commit) plus het opzoeken van de vóór-regel, op de echte logs van het 15.0.9-venster en op afgeleide invoer.
source /d/oud.sh
P=/d/doctor-pre-venster.log; Q=/d/doctor-post.log; F=/d/fase0-doctor-pre.log; T=$(mktemp -d)
toon() { echo; echo "=== $1"; echo "--- doctortoets:"; doctortoets "$2" "$3" | cut -c1-160; echo "exit=${PIPESTATUS[0]}"
         echo "--- archiefregels vóór en na: doctorsamenvatting \"<log>\" | grep 'orphaned repo archive'"
         for l in "$2" "$3"; do doctorsamenvatting "$l" | grep 'orphaned repo archive' | sed "s|^|$([ "$l" = "$2" ] && echo vóór || echo na)\t|" | cut -c1-160; done; }
sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 31\/31 (100 GiB\/100 GiB)/' "$Q" > $T/omvang-groeit.log
sed 's/Found 32\/32 (218 MiB\/218 MiB)/Found 30\/32 (218 MiB\/218 MiB)/' "$Q" > $T/ongelijk.log
awk '/^\[3\] /{print; print " - [W] Found 7/7 (9 MiB/9 MiB) orphaned repo archive(s)"; next} {print}' "$Q" > $T/tweede.log
awk '/^\[4\] /{print; print " - [W] Found 9 broken repositories"; next} {print}' "$Q" > $T/andere-w.log
toon "1. de les: vóór het venster (15.0.2) → na (15.0.9)"   "$P" "$Q"
toon "2. 0.4 → 2.6 van dat venster (zelfde draaiende forge)" "$F" "$P"
toon "3. aantal lager, omvang groter (reviewer ronde 2)"     "$Q" $T/omvang-groeit.log
toon "4. twee ongelijke aantallen in één regel"             "$Q" $T/ongelijk.log
toon "5. een tweede archiefregel in dezelfde check"         "$Q" $T/tweede.log
toon "6. een andere [W]-regel (reviewer ronde 1)"            "$Q" $T/andere-w.log
```

## 4. Uitvoer (`ubuntu:24.04`, mawk 1.3.4, GNU sed 4.9, bash 5.2) en wat de archiefregel zegt

```text
=== 1. de les: vóór het venster (15.0.2) → na (15.0.9)
--- doctortoets:
I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)

=== 2. 0.4 → 2.6 van dat venster (zelfde draaiende forge)
--- doctortoets:
I	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 259/259 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 259/259 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 261/261 (1.3 GiB/1.3 GiB) orphaned repo archive(s)

=== 3. aantal lager, omvang groter (reviewer ronde 2)
--- doctortoets:
I	Check if there are orphaned archives in storage	 - [W] Found 31/31 (100 GiB/100 GiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 31/31 (100 GiB/100 GiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 31/31 (100 GiB/100 GiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 31/31 (100 GiB/100 GiB) orphaned repo archive(s)

=== 4. twee ongelijke aantallen in één regel
--- doctortoets:
I	Check if there are orphaned archives in storage	 - [W] Found 30/32 (218 MiB/218 MiB) orphaned repo archive(s)
I	Check if there are orphaned storage files	 - [W] Found 30/32 (218 MiB/218 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 30/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 30/32 (218 MiB/218 MiB) orphaned repo archive(s)

=== 5. een tweede archiefregel in dezelfde check
--- doctortoets:
I	Check if there are orphaned archives in storage	 - [W] Found 7/7 (9 MiB/9 MiB) orphaned repo archive(s)
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 7/7 (9 MiB/9 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)

=== 6. een andere [W]-regel (reviewer ronde 1)
--- doctortoets:
I	Check if there are orphaned attachments in storage	 - [W] Found 9 broken repositories
DOCTOR ROOD: nieuwe bevindingen hierboven — beoordelen, onverklaard = STOP
exit=1
--- archiefregels vóór en na: doctorsamenvatting "<log>" | grep 'orphaned repo archive'
vóór	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
vóór	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned archives in storage	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
na	I	Check if there are orphaned storage files	 - [W] Found 32/32 (218 MiB/218 MiB) orphaned repo archive(s)
```

| Geval | Getoonde regels | Archiefregel | Waarom |
|---|---|---|---|
| 1. de les, 15.0.2 → 15.0.9 | twee archiefregels | **verklaard** | vorm klopt; één regel per check in beide logs; 32 ≤ 261 en 218 MiB ≤ 1,3 GiB |
| 2. stap 0.4 → 2.6, zelfde forge | twee archiefregels | nieuw | 261 > 259 (voorwaarde 3) |
| 3. aantal lager, omvang groter | twee archiefregels | nieuw | 100 GiB > 218 MiB (voorwaarde 3) |
| 4. ongelijke aantallen in één regel | twee archiefregels | nieuw | 30/32 is niet de vorm A/A (voorwaarde 1) |
| 5. tweede archiefregel in een check | één archiefregel | nieuw | het na-log heeft in die check twee archiefregels (voorwaarde 2); alleen het `grep` op het na-log laat dat zien |
| 6. een andere `[W]`-regel | één regel | nieuw | geen archiefregel (voorwaarde 1) |

Geval 2 is echt: tussen stap 0.4 en stap 2.6 van het 15.0.9-venster, een kwartier uiteen op dezelfde
draaiende forge, steeg het aantal. Het plan vergelijkt die twee logs niet met `doctortoets`; R.4 vergelijkt
wel met een baseline van dagen oud, en daar wordt een hoger aantal beoordeeld zoals elke nieuwe bevinding.
