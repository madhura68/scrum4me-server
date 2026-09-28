# Compose-git — proef van `compose-git-init` en de hook, 28 september 2026

Hoort bij T-131 (scrum4me-server PBI-23, ST-036) en bij onderdeel B1 van
`docs/superpowers/specs/2026-09-28-compose-kopieen-structureel-design.md`.

**Wat er is gebouwd.** `scripts/compose-git-init` maakt van een live compose-map een lokale
git-repo met een allowlist. `scripts/compose-git-pre-commit` is de hook die het installeert. De
tests staan in `scripts/tests/test_compose_git.py`.

**Methode.** De tests draaien in een map van `tempfile`, met `GIT_CONFIG_GLOBAL` en
`GIT_CONFIG_SYSTEM` op `/dev/null`. Ze zijn gedraaid op mac en op beide hosts in een map van
`mktemp -d`. Geen host is gewijzigd. Proefwaarden zijn korter dan 20 tekens.

## Uitkomst

| Waar | Tests | Uitkomst |
|---|---|---|
| mac, vóór de scripts bestonden | 22 | 22 fouten: `compose-git-init` ontbreekt |
| mac | 27 | geslaagd |
| scrum4me-server (Python 3.14.4, git 2.53.0) | 27 | geslaagd |
| max2 (Python 3.14.4, git 2.53.0) | 27 | geslaagd |
| mac, volledige suite van de repo | 95 | geslaagd, 17 overgeslagen |

## Acceptatie uit het taakplan

| # | Eis | Test |
|---|---|---|
| 1 | `git add <naam>` buiten de allowlist weigert | `test_plain_add_outside_the_allowlist_is_refused` |
| 2 | Commit met een geforceerd pad buiten de allowlist wordt geweigerd | `test_commit_with_a_forced_path_outside_the_allowlist_is_refused`, `test_a_harmless_file_outside_the_allowlist_is_refused_too` |
| 3 | Commit met een letterlijke proefwaarde wordt geweigerd | `test_commit_with_a_literal_secret_is_refused` |
| 4 | Commit met alleen geïnterpoleerde waarden slaagt | `test_commit_with_only_interpolated_values_passes` |
| 5 | Herstelrecept voor een nieuw pad en voor een gevolgd bestand | `test_recovery_after_a_forced_path`, `test_recovery_after_a_literal_secret_in_a_tracked_file` |
| 6 | De installatie laat de bestanden ongewijzigd | `test_init_leaves_the_files_unchanged` |
| 7 | De secret-scan van deze repo laat de commit door | de commit van deze taak |

## Mutaties

Elf mutaties schakelen elk één toets uit. Tien laten minstens één test falen.

| # | Uitgeschakeld | Gevangen |
|---|---|---|
| 1 | Hook toetst het pad niet tegen de allowlist | ja |
| 2 | Hook toetst de inhoud niet | ja |
| 3 | Hook toetst geen URL met credentials | ja |
| 4 | Hook leest het werkbestand in plaats van de index | ja |
| 5 | Hook weigert geen secretbestand op de allowlist | ja |
| 6 | Patroon is hoofdlettergevoelig | ja |
| 7 | `.git` krijgt geen mode 700 | ja |
| 8 | Geen opruiming na een fout tijdens de installatie | ja |
| 9 | Installatie toetst de bestanden niet op letterlijke waarden | ja |
| 10 | Installatie weigert root niet | ja |
| 11 | Installatie overschrijft een bestaande `.gitignore` | nee |

Mutatie 11 is niet te vangen zolang de toets vooraf werkt: die weigert een bestaande
`.gitignore` al voordat het script iets schrijft (`test_refuses_an_existing_gitignore`). Het
exclusief openen is een tweede slot achter het eerste.

**Drie gaten die de mutaties lieten zien.** De eerste versie van de tests ving mutatie 1, 3 en 8
niet. Bij 1 en 3 slaagde de test om de verkeerde reden: het proefbestand werd geweigerd door een
andere toets dan de bedoelde. Bij 8 faalde de installatie vóórdat er een repo was, dus er viel
niets op te ruimen. Er zijn drie tests bijgekomen die elk één toets afzonderlijk raken.

## Patroontoets op de live bestanden

De hook is strenger dan de patroontoets uit het meetbewijs: hij kijkt ook naar kleine letters en
naar sleutels zonder voorvoegsel. Om te weten of de installatie op de hosts (T-135) daardoor
vastloopt, is de toets read-only over de live bestanden gedraaid. Alleen bestandsnaam,
regelnummer en sleutelnaam zijn getoond.

| Host | Bestand | Treffers |
|---|---|---|
| scrum4me-server | `/srv/scrum4me/compose/docker-compose.yml` | 0 |
| scrum4me-server | `/srv/scrum4me/forgejo/docker-compose.yml` | 0 |
| scrum4me-server | `/srv/scrum4me/forgejo/runner-config.yaml` | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.yml` | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.override.yml` | 0 |
| max2 | `/srv/scrum4me/compose/docker-compose.codex.yml` | 0 |

## Grenzen

- De hook draait pas bij de commit. `git add` heeft de blob dan al geschreven, en een geweigerde
  commit haalt hem niet weg. De hersteltests bewijzen het herstel, niet de hook.
- De patroontoets is geen volledige scan. Een secret onder een sleutelnaam zonder een van de
  bekende woorden ziet hij niet, tenzij het een URL met credentials is.
- `git commit --no-verify` slaat de hook over. De hostregel verbiedt dat niet met techniek.

## Uitvoer scrum4me-server

```text
######## scrum4me-server ########
Linux  Python 3.14.4  git version 2.53.0  2026-09-28T17:12:33Z
init: 5d1e70633a0e232c0b019dbf40111476ffc1a85229bba248c7c5a145cf5cd782
hook: 51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6
--- origineel, volledige uitvoer ---

----------------------------------------------------------------------
Ran 27 tests

OK
--- mutatie 1: hook toetst het pad niet tegen de allowlist ---
FAIL: test_a_harmless_file_outside_the_allowlist_is_refused_too
Ran 27 tests
FAILED (failures=1)
--- mutatie 2: hook toetst de inhoud niet ---
FAIL: test_commit_with_a_literal_secret_is_refused
FAIL: test_commit_with_credentials_in_a_url_is_refused
FAIL: test_lowercase_and_bare_keys_are_judged_too
FAIL: test_the_staged_content_is_judged_not_the_working_file
FAIL: test_recovery_after_a_literal_secret_in_a_tracked_file
Ran 27 tests
FAILED (failures=5)
--- mutatie 3: hook toetst geen URL met credentials ---
FAIL: test_commit_with_credentials_in_a_url_is_refused
Ran 27 tests
FAILED (failures=1)
--- mutatie 4: hook leest het werkbestand in plaats van de index ---
FAIL: test_the_staged_content_is_judged_not_the_working_file
Ran 27 tests
FAILED (failures=1)
--- mutatie 5: hook weigert geen secretbestand op de allowlist ---
FAIL: test_a_secret_file_on_the_allowlist_is_refused
Ran 27 tests
FAILED (failures=1)
--- mutatie 6: patroon is hoofdlettergevoelig ---
FAIL: test_lowercase_and_bare_keys_are_judged_too
Ran 27 tests
FAILED (failures=1)
--- mutatie 7: init zet .git niet op 700 ---
FAIL: test_git_dir_is_private_and_the_hook_equals_its_source
Ran 27 tests
FAILED (failures=1)
--- mutatie 8: init ruimt niet op na een fout ---
FAIL: test_a_failure_during_the_install_leaves_no_half_repo
Ran 27 tests
FAILED (failures=1)
--- mutatie 9: init toetst de allowlist-bestanden niet op letterlijke waarden ---
FAIL: test_literal_secret_in_an_allowlist_file_stops_and_leaves_no_repo
Ran 27 tests
FAILED (failures=1)
--- mutatie 10: init weigert root niet ---
FAIL: test_refuses_to_run_as_root
Ran 27 tests
FAILED (failures=1)
--- mutatie 11: init overschrijft een bestaande .gitignore ---
Ran 27 tests
OK
--- patroontoets op de live bestanden (alleen namen) ---
/srv/scrum4me/compose/docker-compose.yml: 433 regels, 0 treffer(s)
/srv/scrum4me/forgejo/docker-compose.yml: 156 regels, 0 treffer(s)
/srv/scrum4me/forgejo/runner-config.yaml: 30 regels, 0 treffer(s)
```

## Uitvoer max2

```text
######## max2 ########
Linux  Python 3.14.4  git version 2.53.0  2026-09-28T17:13:14Z
init: 5d1e70633a0e232c0b019dbf40111476ffc1a85229bba248c7c5a145cf5cd782
hook: 51d6eac0e0b98e649fb384c8db81aad48b1222c4909949d997201e7d7c86c5d6
--- origineel, volledige uitvoer ---

----------------------------------------------------------------------
Ran 27 tests

OK
--- mutatie 1: hook toetst het pad niet tegen de allowlist ---
FAIL: test_a_harmless_file_outside_the_allowlist_is_refused_too
Ran 27 tests
FAILED (failures=1)
--- mutatie 2: hook toetst de inhoud niet ---
FAIL: test_commit_with_a_literal_secret_is_refused
FAIL: test_commit_with_credentials_in_a_url_is_refused
FAIL: test_lowercase_and_bare_keys_are_judged_too
FAIL: test_the_staged_content_is_judged_not_the_working_file
FAIL: test_recovery_after_a_literal_secret_in_a_tracked_file
Ran 27 tests
FAILED (failures=5)
--- mutatie 3: hook toetst geen URL met credentials ---
FAIL: test_commit_with_credentials_in_a_url_is_refused
Ran 27 tests
FAILED (failures=1)
--- mutatie 4: hook leest het werkbestand in plaats van de index ---
FAIL: test_the_staged_content_is_judged_not_the_working_file
Ran 27 tests
FAILED (failures=1)
--- mutatie 5: hook weigert geen secretbestand op de allowlist ---
FAIL: test_a_secret_file_on_the_allowlist_is_refused
Ran 27 tests
FAILED (failures=1)
--- mutatie 6: patroon is hoofdlettergevoelig ---
FAIL: test_lowercase_and_bare_keys_are_judged_too
Ran 27 tests
FAILED (failures=1)
--- mutatie 7: init zet .git niet op 700 ---
FAIL: test_git_dir_is_private_and_the_hook_equals_its_source
Ran 27 tests
FAILED (failures=1)
--- mutatie 8: init ruimt niet op na een fout ---
FAIL: test_a_failure_during_the_install_leaves_no_half_repo
Ran 27 tests
FAILED (failures=1)
--- mutatie 9: init toetst de allowlist-bestanden niet op letterlijke waarden ---
FAIL: test_literal_secret_in_an_allowlist_file_stops_and_leaves_no_repo
Ran 27 tests
FAILED (failures=1)
--- mutatie 10: init weigert root niet ---
FAIL: test_refuses_to_run_as_root
Ran 27 tests
FAILED (failures=1)
--- mutatie 11: init overschrijft een bestaande .gitignore ---
Ran 27 tests
OK
--- patroontoets op de live bestanden (alleen namen) ---
/srv/scrum4me/compose/docker-compose.yml: 112 regels, 0 treffer(s)
/srv/scrum4me/compose/docker-compose.override.yml: 16 regels, 0 treffer(s)
/srv/scrum4me/compose/docker-compose.codex.yml: 49 regels, 0 treffer(s)
```

## compose-git-mutaties.sh

```sh
# Draait de tests tegen het origineel en tegen mutaties die elk een toets uitschakelen.
set -u
cd "$1"
echo "$(uname -s)  $(python3 --version)  $(git --version)  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "init: $(sha256sum compose-git-init | cut -d' ' -f1)"
echo "hook: $(sha256sum compose-git-pre-commit | cut -d' ' -f1)"
cp compose-git-init init.orig; cp compose-git-pre-commit hook.orig
run() { PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_compose_git.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED' | sed -E 's/ \(tests\.[^)]*\)//; s/ in [0-9.]+s//'; }
mut() { python3 - "$1" "$2" "$3" <<'PY'
import sys
f, a, b = sys.argv[1], sys.argv[2].replace('\\n', '\n'), sys.argv[3].replace('\\n', '\n')
s = open(f + ".orig" if False else {"compose-git-init": "init.orig", "compose-git-pre-commit": "hook.orig"}[f]).read()
assert s.count(a) == 1, a
open(f, 'w').write(s.replace(a, b))
PY
}
reset() { cp init.orig compose-git-init; cp hook.orig compose-git-pre-commit; }
echo "--- origineel, volledige uitvoer ---"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests/test_compose_git.py 2>&1 | sed -E 's/ \(tests\.[^)]*\)//; s/ in [0-9.]+s//'
echo "--- mutatie 1: hook toetst het pad niet tegen de allowlist ---"
mut compose-git-pre-commit '        if path not in allow:\n' '        if False:\n'; run; reset
echo "--- mutatie 2: hook toetst de inhoud niet ---"
mut compose-git-pre-commit '        for number, key in find_literals(text):\n' '        for number, key in []:\n'; run; reset
echo "--- mutatie 3: hook toetst geen URL met credentials ---"
mut compose-git-pre-commit '        if URL_CREDENTIALS_RE.search(line):\n' '        if False:\n'; run; reset
echo "--- mutatie 4: hook leest het werkbestand in plaats van de index ---"
mut compose-git-pre-commit '        text = git("show", ":" + path).decode("utf-8", errors="replace")\n' '        text = open(path, encoding="utf-8", errors="replace").read()\n'; run; reset
echo "--- mutatie 5: hook weigert geen secretbestand op de allowlist ---"
mut compose-git-pre-commit '        if forbidden_name(name):\n' '        if False:\n'; run; reset
echo "--- mutatie 6: patroon is hoofdlettergevoelig ---"
mut compose-git-pre-commit '    re.IGNORECASE)\n' '    0)\n'; run; reset
echo "--- mutatie 7: init zet .git niet op 700 ---"
mut compose-git-init '        os.chmod(git_dir, 0o700)\n' '        pass\n'; run; reset
echo "--- mutatie 8: init ruimt niet op na een fout ---"
mut compose-git-init '        shutil.rmtree(git_dir, ignore_errors=True)\n' '        pass\n'; run; reset
echo "--- mutatie 9: init toetst de allowlist-bestanden niet op letterlijke waarden ---"
mut compose-git-init '        if hits:\n' '        if False:\n'; run; reset
echo "--- mutatie 10: init weigert root niet ---"
mut compose-git-init '    if os.geteuid() == 0:\n' '    if False:\n'; run; reset
echo "--- mutatie 11: init overschrijft een bestaande .gitignore ---"
mut compose-git-init '        with open(ignore_path, "x", encoding="utf-8") as f:\n' '        with open(ignore_path, "w", encoding="utf-8") as f:\n'; run; reset
rm -f init.orig hook.orig
```

## patroon-live.py

```python
# READ-ONLY. Draait de patroontoets van de hook over live compose-bestanden.
# Toont alleen bestandsnaam, regelnummer en sleutelnaam, nooit een waarde.
import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("hook", "compose-git-pre-commit")
spec = importlib.util.spec_from_loader(loader.name, loader); hook = importlib.util.module_from_spec(spec); loader.exec_module(hook)
for path in sys.argv[1:]:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"{path}: niet leesbaar ({e.strerror})"); continue
    hits = hook.find_literals(text)
    print(f"{path}: {len(text.splitlines())} regels, {len(hits)} treffer(s)")
    for number, key in hits:
        print(f"    regel {number}: {key}")
```
