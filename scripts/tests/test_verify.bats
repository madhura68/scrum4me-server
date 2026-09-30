#!/usr/bin/env bats
# scripts/tests/test_verify.bats — aggregatielogica van scripts/verify.sh (T-153).
# Hermetisch: VERIFY_ROOT wijst naar een tijdelijke nep-repo met kleine testbestanden;
# er wordt niets uit de echte repo gedraaid.

setup() {
  VERIFY="$BATS_TEST_DIRNAME/../verify.sh"
  FAKE="$(mktemp -d)"
  mkdir -p "$FAKE/forgejo-runner/tests" "$FAKE/scripts/tests"
  cat >"$FAKE/forgejo-runner/tests/test_ok.py" <<'PY'
import unittest

class T(unittest.TestCase):
    def test_slaagt(self):
        self.assertTrue(True)

    @unittest.skip("bewust overgeslagen")
    def test_overgeslagen(self):
        pass

    @unittest.expectedFailure
    def test_verwacht_falen(self):
        self.fail("hoort te falen")

if __name__ == "__main__":
    unittest.main()
PY
  cat >"$FAKE/forgejo-runner/tests/test_ok.bats" <<'BATS'
#!/usr/bin/env bats
@test "bats slaagt" { true; }
@test "bats skip" { skip "geen docker"; }
BATS
  cat >"$FAKE/scripts/tool.sh" <<'SH'
#!/usr/bin/env bash
echo hallo
SH
  export VERIFY_ROOT="$FAKE"
}

teardown() { rm -rf "$FAKE"; }

@test "help: exit 0 en noemt VERIFY_INTEGRATION" {
  run bash "$VERIFY" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *VERIFY_INTEGRATION* ]]
}

@test "alles groen: exit 0, skips met reden, expected failure apart geteld" {
  run bash "$VERIFY"
  [ "$status" -eq 0 ]
  [[ "$output" == *"RESULTAAT: GESLAAGD"* ]]
  [[ "$output" == *"test_overgeslagen"*"bewust overgeslagen"* ]]
  [[ "$output" == *"bats skip"*"geen docker"* ]]
  [[ "$output" == *"expected failure: 1"* ]]
}

@test "een falende Python-test: exit != 0 en het falende bestand staat in het rapport" {
  cat >"$FAKE/scripts/tests/test_kapot.py" <<'PY'
import unittest

class T(unittest.TestCase):
    def test_faalt(self):
        self.fail("kapot")

if __name__ == "__main__":
    unittest.main()
PY
  run bash "$VERIFY"
  [ "$status" -ne 0 ]
  [[ "$output" == *"RESULTAAT: GEFAALD"* ]]
  [[ "$output" == *"Gefaald:"*"scripts/tests/test_kapot.py"* ]]
  # de groene onderdelen blijven gewoon in de samenvatting staan
  [[ "$output" == *"bats "*"PASS"* ]]
  [[ "$output" == *"py "*"FAIL"* ]]
}

@test "een falende bats-test terwijl de rest groen is: exit != 0" {
  cat >"$FAKE/scripts/tests/kapot.bats" <<'BATS'
#!/usr/bin/env bats
@test "faalt" { false; }
BATS
  run bash "$VERIFY"
  [ "$status" -ne 0 ]
  [[ "$output" == *"scripts/tests/kapot.bats"* ]]
  [[ "$output" == *"py "*"PASS"* ]]
}

@test "een shellcheck-bevinding: exit != 0" {
  printf '#!/usr/bin/env bash\necho $y\n' >"$FAKE/scripts/slecht.sh"
  run bash "$VERIFY" --only shellcheck
  [ "$status" -ne 0 ]
  [[ "$output" == *"scripts/slecht.sh"* ]]
}

@test "integratietest is standaard uitgesloten en wordt als zodanig gemeld" {
  printf '#!/usr/bin/env bats\n@test "zwaar" { false; }\n' >"$FAKE/forgejo-runner/tests/test_compose_runner_exec.bats"
  run bash "$VERIFY" --only bats
  [ "$status" -eq 0 ]
  [[ "$output" == *"Bewust niet gedraaid"*"test_compose_runner_exec.bats"* ]]
}

@test "geen .pyc of __pycache__ in de nep-repo na een run" {
  run bash "$VERIFY" --only py
  [ "$status" -eq 0 ]
  [ -z "$(find "$FAKE" -name '*.pyc' -o -name __pycache__)" ]
}

@test "onbekende --only-waarde: exit 2" {
  run bash "$VERIFY" --only nonsens
  [ "$status" -eq 2 ]
}
