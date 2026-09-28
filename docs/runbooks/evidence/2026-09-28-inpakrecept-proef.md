# Inpakrecept — proef van `compose-inpak`, 28 september 2026

Hoort bij T-130 (scrum4me-server PBI-23, ST-035) en bij onderdeel E van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Aanleiding.** Het inpakrecept verwijdert bestanden op een productiehost. In de reviewrondes van het
ontwerp bleek tweemaal dat een procedure die zonder proef was opgeschreven fout was. Het recept staat
daarom in een script, `scripts/compose-inpak`, met tests die elke toets afzonderlijk bewijzen.

**Methode.** De tests draaien op scrum4me-server in een map van `mktemp -d`, met alleen
proefbestanden. `/srv` is niet geraakt. Ze gebruiken GNU tar en worden op macOS overgeslagen.
`docker compose ls` is in de tests vervangen door een functie die een vaste stand teruggeeft; het
gedrag van Compose zelf is bewezen met de droogloop en de echte uitvoering.

## Wat de tests bewijzen

| Receptstap | Test |
|---|---|
| 1. Lijst zonder globs | `test_list_refuses_globs_relative_paths_and_duplicates` |
| 2. Opnieuw toetsen vooraf | `test_changed_file_before_run_stops_before_the_tar`, `test_registered_config_on_the_list_stops`, `test_file_under_the_active_release_stops`, `test_symlink_on_the_list_stops` |
| 3. Tar met mode 600, nooit overschrijven | `test_run_packs_reads_back_and_removes`, `test_existing_tar_is_never_overwritten` |
| 4. Teruglezen vóór verwijderen | `test_change_between_first_check_and_tar_is_caught_by_the_read_back` |
| 5. Hertoets per bestand, stoppen laat de rest staan | `test_change_between_read_back_and_removal_keeps_the_rest`, `test_file_that_becomes_registered_during_removal_is_kept`, `test_active_release_that_moves_during_removal_is_kept` |
| 6. Natoets | `test_post_check_reports_a_changed_stack` |
| Droogloop wijzigt niets | `test_plan_changes_nothing` |
| Geen bestandsinhoud in MANIFEST of SHA256SUMS | `test_sidecars_hold_no_file_content` |

Het stoppad uit stap 2 van de taak (een bestand wijzigen nadat de lijst is vastgelegd) is
`test_change_between_read_back_and_removal_keeps_the_rest`: het recept verwijdert het eerste
bestand, stopt bij het gewijzigde tweede en laat het tweede en derde staan.

## Mutaties

Zes mutaties schakelen elk één veiligheidstoets in het script uit. Bij elke mutatie faalt minstens
één test.

| # | Uitgeschakeld | Falende tests |
|---|---|---|
| 1 | Hertoets vlak voor het verwijderen | 4 |
| 2 | Vergelijken bij het teruglezen | 1 |
| 3 | Toets op geregistreerde configbestanden | 2 |
| 4 | Toets op de actieve release | 2 |
| 5 | Weigeren van een bestaand doel | 1 |
| 6 | Natoets | 1 |

De eerste versie van de tests ving mutatie 2 niet: er was geen test voor het teruglezen zelf. De
test `test_change_between_first_check_and_tar_is_caught_by_the_read_back` is daarna toegevoegd.

## Droogloop met de echte lijsten

Vóór het akkoord van JP is `compose-inpak plan` op scrum4me-server gedraaid met lijst A en lijst B.
Beide gaven "alle toetsen geslaagd; er is niets gewijzigd", en `/srv/_attic` en de backupmap waren
daarna ongewijzigd. De uitvoering staat in
[2026-09-28-compose-opruiming-scrum4me-server.md](2026-09-28-compose-opruiming-scrum4me-server.md).

## Uitvoer

```text
host: scrum4me-server  Python 3.14.4  tar (GNU tar) 1.35  2026-09-28T16:42:39Z
script: e6d6308c3598359cebca2d9ce55c525d2a96e99acace5ac56b7e524a24c39dc9
--- origineel, volledige uitvoer ---
test_active_release_that_moves_during_removal_is_kept ... ok
test_change_between_first_check_and_tar_is_caught_by_the_read_back ... ok
test_change_between_read_back_and_removal_keeps_the_rest ... ok
test_changed_file_before_run_stops_before_the_tar ... ok
test_existing_tar_is_never_overwritten ... ok
test_file_that_becomes_registered_during_removal_is_kept ... ok
test_file_under_the_active_release_stops ... ok
test_list_refuses_globs_relative_paths_and_duplicates ... ok
test_plan_changes_nothing ... ok
test_post_check_reports_a_changed_stack ... ok
test_registered_config_on_the_list_stops ... ok
test_run_packs_reads_back_and_removes ... ok
test_sidecars_hold_no_file_content ... ok
test_symlink_on_the_list_stops ... ok

----------------------------------------------------------------------
Ran 14 tests

OK
--- mutatie 1: geen hertoets vlak voor het verwijderen ---
FAIL: test_active_release_that_moves_during_removal_is_kept
FAIL: test_change_between_read_back_and_removal_keeps_the_rest
FAIL: test_file_that_becomes_registered_during_removal_is_kept
FAIL: test_post_check_reports_a_changed_stack
Ran 14 tests
FAILED (failures=4)
--- mutatie 2: teruglezen vergelijkt de hashes niet ---
FAIL: test_change_between_first_check_and_tar_is_caught_by_the_read_back
Ran 14 tests
FAILED (failures=1)
--- mutatie 3: geen toets op geregistreerde configbestanden ---
FAIL: test_file_that_becomes_registered_during_removal_is_kept
FAIL: test_registered_config_on_the_list_stops
Ran 14 tests
FAILED (failures=2)
--- mutatie 4: geen toets op de actieve release ---
FAIL: test_active_release_that_moves_during_removal_is_kept
FAIL: test_file_under_the_active_release_stops
Ran 14 tests
FAILED (failures=2)
--- mutatie 5: bestaand doel wordt overschreven ---
FAIL: test_existing_tar_is_never_overwritten
Ran 14 tests
FAILED (failures=1)
--- mutatie 6: geen natoets ---
FAIL: test_post_check_reports_a_changed_stack
Ran 14 tests
FAILED (failures=1)
```

## mutaties.sh

```sh
# Draait de tests tegen het origineel en tegen zes mutaties die elk een veiligheidstoets uitschakelen.
set -u
echo "host: $(hostname)  $(python3 --version)  $(tar --version | head -1)  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "script: $(sha256sum compose-inpak | cut -d' ' -f1)"
cp compose-inpak origineel
run() { PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_compose_inpak.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED' | sed -E 's/ \(tests\.[^)]*\)//; s/ in [0-9.]+s//'; }
mut() { python3 - "$1" "$2" <<'PY'
import sys
s = open('origineel').read(); a = sys.argv[1].replace('\\n', '\n'); b = sys.argv[2].replace('\\n', '\n')
assert s.count(a) == 1, a
open('compose-inpak', 'w').write(s.replace(a, b))
PY
}
echo "--- origineel, volledige uitvoer ---"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests/test_compose_inpak.py 2>&1 | sed -E 's/ \(tests\.[^)]*\)//; s/ in [0-9.]+s//'
echo "--- mutatie 1: geen hertoets vlak voor het verwijderen ---"
mut '            check_entry(digest, path, compose_ls(), args.current_link)\n' '            pass\n'; run
echo "--- mutatie 2: teruglezen vergelijkt de hashes niet ---"
mut '            if sha256_file(os.path.join(tmp, rel)) != digest:\n' '            if False:\n'; run
echo "--- mutatie 3: geen toets op geregistreerde configbestanden ---"
mut '    if path in registered or real in {os.path.realpath(c) for c in registered}:\n' '    if False:\n'; run
echo "--- mutatie 4: geen toets op de actieve release ---"
mut '        if real == target or real.startswith(target + os.sep):\n' '        if False:\n'; run
echo "--- mutatie 5: bestaand doel wordt overschreven ---"
mut '        if os.path.lexists(target):\n' '        if False:\n'; run
echo "--- mutatie 6: geen natoets ---"
mut '    if rows_after != rows_before:\n' '    if False:\n'; run
```
