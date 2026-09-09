# ISS-18 soft-trust-publicatie Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Laat een geldige soft-only trustmeting de pool niet stoppen, zonder harde, onleesbare of tegenstrijdige resultaten groen te maken.

**Architecture:** Behoud de bestaande shellinterface en echte CLI. Vang de CLI-exitcode op en valideer de resultaat-JSON met Python stdlib voordat het atomische controllerverdict wordt gepubliceerd. De scannerclassificatie, controller en timer veranderen niet.

**Tech Stack:** POSIX sh, Python 3 stdlib, unittest, Bats, ShellCheck.

**Spec:** `docs/forgejo-runner-pool/migratieontwerp.md` §7.7: zacht alarmeren en binnen 24 uur beoordelen, niet automatisch de pool stoppen. JP keurde op 2026-09-09 de gerichte publisherreparatie goed; geen bronselectie-uitbreiding. Dit plan concretiseert dat akkoord.

## Global Constraints

- Canonieke repo: `https://git.jp-visser.nl/janpeter/scrum4me-server`; uitgangspunt `29beecacfd1b424d34e997a2a3398b66b2153fbe`.
- Product `cmsx8zbdh0002hk7rcgxxr00k`, issue ISS-18 `cmtubs7kv0002qf1778ukgb9g`. ST-013.1 is verificatiewerk en mag niet voor deze codefix worden gebruikt.
- Geen mainmerge, hostuitrol, serviceherstart, Actions-toggle of proefdispatch in dit werkpakket. Geen tokens lezen of wijzigen. Geen label-, allowlist-, defaultbranch-, triggerpolicy- of controllerwijziging.
- Scanner blijft defaultbranch-only. Een groen verdict is geen commitgebonden attestation van Video-editor `ac86d64e24f2df26ae2f8a8917a701f09f7856d2`.
- Soft is geen permanente vrijstelling: journallog zichtbaar houden en beoordeling binnen 24 uur handhaven.
- Behoud CLI-argumenten, FORGEJO_URL-targetbinding, gemeten tijd, SHA256 van labels en allowlist, atomische vervanging van het verdict; mislukte nieuwe meting vervangt oud groen door rood.
- Geen nieuwe dependencies. Tests gebruiken uitsluitend tijdelijke bestanden en offline fixtures; geen Forgejo-, Docker- of DB-operaties.
- Codegereed is niet pool-DoD: §9 vereist zeven stabiele dagen, die deze lokale fix niet bewijst. ISS-18 blijft open tot afzonderlijk goedgekeurde uitrol en live verificatie.

## Besliscontract

| CLI-exit | Resultaat | Publisher |
|---|---|---|
| 0 | object; ok exact true; hard/unreadable/soft lege stringlijsten | groen, exit 0 |
| 10 | object; ok exact true; hard/unreadable leeg; soft niet-lege stringlijst | groen, exit 0, waarschuwing |
| 0/10 | ontbrekend, ongeldige JSON, dubbele keys, verkeerde types, tegenstrijdige lijsten/ok | rood, exit 3 |
| elke andere exit | ongeacht resultaatbestand | rood, exit 3 |

Het optionele bestaande `accepted` is informatief en beslist niet over groen. Onbekende velden veranderen de beslissing niet. JSON-constanten NaN/Infinity zijn ongeldig. Ontbrekende/niet-reguliere/onleesbare bindende bestanden zijn metingsfouten, ook als ze al vóór de CLI-aanroep ontbreken: rood en exit 3 indien de outputdirectory schrijfbaar is. Alleen ontbrekende/ongeldige argumenten zijn exit 2. Bij een onschrijfbare outputdirectory is atomisch vervangen onmogelijk: nonzero melden, geen succesclaim. Geen nieuwe durability-/crashgarantie. Als de Python-publicatie niet slaagt, schrijft de shell onafhankelijk een minimaal rood verdict met ok=false, measured_at en reason; target/hashes zijn alleen verplicht voor groen. De shellfallback gebruikt bewust geen on-geëscapete target in JSON en bewaart geen groen bij interpreteruitval.

## Task 1: Publishercontract herstellen met offline ketenbewijs

**Files:**

- Modify: `forgejo-runner/scripts/publish-trust-verdict.sh` — vlaggeninterface behouden; argumentvalidatie losmaken van bestandsvalidatie; hashfunctie en grep-publicatie vervangen; shellfallback behouden.
- Modify: `forgejo-runner/tests/test_publish_trust_verdict.bats` — bestaande succesfixture naar volledig CLI-contract brengen.
- Create: `forgejo-runner/tests/test_publish_trust_verdict.py` — echte publisher als subprocess, matrix en echte CLI met offline client.
- Modify: `forgejo-runner/README.md` — nieuwe exit0/10-semantiek, 24-uursbeoordeling, defaultbranchbeperking en afzonderlijke uitrolgate.

**Interfaces:** Consumeert `--cli-py P --labels L --allowlist A --target T --out O`. De CLI schrijft `trust-verdict.json` in een verse directory; exitcodes 0/10/20/30 blijven ongewijzigd. Produceert compact JSON-controllerverdict met `ok`, `measured_at`, bij groen `forgejo_target`/`labels_sha256`/`allowlist_sha256`, bij rood `reason`. Publisher exit 0 betekent bruikbaar groen, exit 3 mislukte meting/publicatie, exit 2 blijft gebruiksfout.

- [ ] Lees spec §7.7, publisher, `trust_scope.py::Verdict/classify`, `trust_scope_cli.py::main`, bestaande tests en `forgejo-runner/README.md`. Leg taak op IN_PROGRESS en log start in Scrum4Me. Gebruik de geïsoleerde branch `codex/iss-18-soft-trust`.
- [ ] Maak de onderstaande unittest-harness. Gebruik hem voor de volledige matrix daarna.

```python
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
GOOD = {"ok": True, "hard": [], "unreadable": [], "soft": []}

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.labels = self.path / "labels.txt"
        self.allow = self.path / "allow.yml"
        self.out = self.path / "verdict.json"
        self.labels.write_text("ubuntu-latest:docker://example@sha256:abc\n")
        self.allow.write_text('approved_by: "test"\nidentities:\n  - name: janpeter\nrepositories:\n  - full_name: janpeter/app\n    actions_enabled: true\n')
        self.old_green = dict(GOOD, forgejo_target="https://offline.invalid",
                              labels_sha256=hashlib.sha256(self.labels.read_bytes()).hexdigest(),
                              allowlist_sha256=hashlib.sha256(self.allow.read_bytes()).hexdigest())

    def invoke(self, source, env_override=None):
        cli = self.path / "cli.py"
        cli.write_text(source)
        self.out.write_text(json.dumps(dict(self.old_green, measured_at=int(time.time()))))
        env = dict(os.environ, FORGEJO_TOKEN="offline-test-only")
        env.update(env_override or {})
        return subprocess.run([
            str(ROOT / "scripts/publish-trust-verdict.sh"),
            "--cli-py", str(cli), "--labels", str(self.labels),
            "--allowlist", str(self.allow), "--target", "https://offline.invalid",
            "--out", str(self.out),
        ], env=env, capture_output=True, text=True, timeout=15)

    def fixture(self, rc, raw):
        return ("import os, pathlib, sys\n"
                "assert os.environ['FORGEJO_URL'] == 'https://offline.invalid'\n"
                "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
                + ("" if raw is None else f"(out/'trust-verdict.json').write_text({raw!r})\n")
                + f"sys.exit({rc})\n")

    def assert_result(self, result, green):
        self.assertEqual(result.returncode, 0 if green else 3, result.stderr)
        doc = json.loads(self.out.read_text())
        self.assertIs(doc["ok"], green)
        self.assertLess(abs(time.time() - doc["measured_at"]), 30)
        if green:
            self.assertEqual(doc["forgejo_target"], "https://offline.invalid")
            self.assertEqual(doc["labels_sha256"], hashlib.sha256(self.labels.read_bytes()).hexdigest())
            self.assertEqual(doc["allowlist_sha256"], hashlib.sha256(self.allow.read_bytes()).hexdigest())

    def test_soft_only_is_green(self):
        result = self.invoke(self.fixture(10, json.dumps(dict(GOOD, soft=["waarschuwing"]))))
        self.assert_result(result, True)
        self.assertIn("24 uur", result.stderr)

    def test_matrix(self):
        soft = dict(GOOD, soft=["waarschuwing"])
        cases = [(0, json.dumps(GOOD), True), (10, json.dumps(soft), True)]
        cases += [(rc, json.dumps(GOOD), False) for rc in (1, 20, 30, 137)]
        for rc in (0, 10):
            base = GOOD if rc == 0 else soft
            invalid = [None, "{", "[]", "null", '{"ok":true,"ok":false}',
                       json.dumps(dict(base, ok=False)), json.dumps(dict(base, ok=1)),
                       json.dumps(dict(base, ok="true")), json.dumps(dict(base, hard=["hard"])),
                       json.dumps(dict(base, unreadable=["onleesbaar"])),
                       json.dumps(dict(base, soft=[] if rc == 10 else ["zacht"])),
                       json.dumps(dict(base, extra=float("nan")))]
            for key in ("hard", "unreadable", "soft"):
                invalid += [json.dumps({k: v for k, v in base.items() if k != key})]
                invalid += [json.dumps(dict(base, **{key: v})) for v in (None, {}, "", [1])]
            invalid += [json.dumps(base)[:-1] + ',"ok":true}']
            cases += [(rc, raw, False) for raw in invalid]
        for rc, raw, green in cases:
            with self.subTest(rc=rc, raw=raw):
                self.assert_result(self.invoke(self.fixture(rc, raw)), green)

    def test_real_cli_soft_inventory(self):
        source = (f"import sys\nsys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
                  f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
                  "import trust_scope_cli\n"
                  "from test_trust_scope import FakeClient, REPO_ACTIONS\n"
                  "trust_scope_cli.ForgejoClient = lambda *_: FakeClient([REPO_ACTIONS])\n"
                  "sys.exit(trust_scope_cli.main())\n")
        result = self.invoke(source)
        self.assert_result(result, True)
        self.assertIn("ZACHT:", result.stderr)
        self.assertIn("geen workflowmap", result.stderr)

    def test_missing_or_nonregular_inputs_invalidate_old_green(self):
        for path in (self.labels, self.allow):
            original = path.read_bytes()
            for kind in ("missing", "directory", "dangling-link"):
                with self.subTest(path=path.name, kind=kind):
                    path.unlink()
                    if kind == "directory":
                        path.mkdir()
                    elif kind == "dangling-link":
                        path.symlink_to(self.path / "absent")
                    result = self.invoke(self.fixture(0, json.dumps(GOOD)))
                    self.assert_result(result, False)
                    if kind == "directory":
                        path.rmdir()
                    elif kind == "dangling-link":
                        path.unlink()
                    path.write_bytes(original)

    def test_interpreter_failure_invalidates_old_green(self):
        bin_dir = self.path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "python3"
        for rc in (127, 1, 3):
            with self.subTest(rc=rc):
                fake.write_text(f"#!/bin/sh\nexit {rc}\n")
                fake.chmod(0o755)
                result = self.invoke("", {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]})
                self.assert_result(result, False)

    def test_missing_flags_remain_usage_errors(self):
        result = subprocess.run([str(ROOT / "scripts/publish-trust-verdict.sh")],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)

if __name__ == "__main__":
    unittest.main()
```

- [ ] Run `cd forgejo-runner && python3 tests/test_publish_trust_verdict.py`: soft-only en echte-CLI-test moeten rood zijn door de bestaande publisher-exit 3, niet door fixture/importfouten. Log RED-bewijs. De offline launcher vervangt alleen het netwerkclientobject; inventory, classify, main, JSON en exitcode zijn echt. Er bestaat geen productie-`--inventory`-optie en die wordt niet toegevoegd.
- [ ] Vervang in de bestaande Bats-succesfixture `{"ok":true}` door `{"ok":true,"hard":[],"unreadable":[],"soft":[]}`. Behoud beide oorspronkelijke tests.
- [ ] Verwijder `hashtool()`. Vervang uitsluitend in de argumentvalidatie `[ -f "$LABELS" ]` en `[ -f "$ALLOWLIST" ]` door respectievelijk `[ -n "$LABELS" ]` en `[ -n "$ALLOWLIST" ]`: aangeleverde paden zijn argumenten, hun bestaan is metingsvalidatie. Vervang alles vanaf het huidige `if ! FORGEJO_URL=...` door dit blok. Behoud `WORK` en cleanup-trap en pas de header aan naar geldige exit0/10-publicatie.

```sh
CLI_RC=0
if [ -f "$LABELS" ] && [ -r "$LABELS" ] && [ -f "$ALLOWLIST" ] && [ -r "$ALLOWLIST" ]; then
  FORGEJO_URL="$TARGET" python3 "$CLI_PY" --allowlist "$ALLOWLIST" --labels "$LABELS" --out "$WORK" || CLI_RC=$?
else
  CLI_RC=30
  echo "trustmeting mislukt: labels/allowlist ontbreken of zijn geen leesbare reguliere bestanden" >&2
fi
PUB_RC=0
python3 - "$WORK/trust-verdict.json" "$CLI_RC" "$LABELS" "$ALLOWLIST" "$TARGET" "$OUT" <<'PY' || PUB_RC=$?
import hashlib
import json
import os
from pathlib import Path
import sys
import time

source, rc, labels, allowlist, target, output = sys.argv[1:]
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("dubbele JSON-key")
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError("ongeldige JSON-constante")

doc = {"ok": False, "measured_at": int(time.time()), "forgejo_target": target}
try:
    if rc not in ("0", "10"):
        raise ValueError("CLI-exit " + rc)
    verdict = json.loads(Path(source).read_text(encoding="utf-8"),
                         object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(verdict, dict) or verdict.get("ok") is not True:
        raise ValueError("ongeldig ok-veld")
    for key in ("hard", "unreadable", "soft"):
        value = verdict.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ongeldige lijst: " + key)
    if verdict["hard"] or verdict["unreadable"] or bool(verdict["soft"]) != (rc == "10"):
        raise ValueError("exitcode en resultaat spreken elkaar tegen")
    doc["labels_sha256"] = hashlib.sha256(Path(labels).read_bytes()).hexdigest()
    doc["allowlist_sha256"] = hashlib.sha256(Path(allowlist).read_bytes()).hexdigest()
    doc["ok"] = True
except (OSError, ValueError, RecursionError) as exc:
    doc["reason"] = "meting mislukt"
    print("trustmeting mislukt; actief verdict wordt geïnvalideerd: " + str(exc), file=sys.stderr)

tmp = Path(output + ".tmp." + str(os.getpid()))
try:
    tmp.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, output)
except OSError as exc:
    print("verdictpublicatie mislukt: " + str(exc), file=sys.stderr)
    sys.exit(3)
if doc["ok"] and rc == "10":
    print("trustmeting groen met zachte afwijkingen; binnen 24 uur beoordelen", file=sys.stderr)
sys.exit(0 if doc["ok"] else 3)
PY
if [ "$PUB_RC" -ne 0 ]; then
  # Ook als python3 zelf uitvalt moet oud groen verdwijnen. Bij normale exit3
  # is dit een tweede, veilige rode vervanging; de detailreden staat in stderr.
  ITMP="$OUT.tmp.$$"
  if printf '{"ok":false,"measured_at":%s,"reason":"meting of publicatie mislukt"}\n' \
    "$(date +%s)" > "$ITMP" && mv -f "$ITMP" "$OUT"; then
    echo "trustmeting/publicatie mislukt; actief verdict geïnvalideerd" >&2
  else
    echo "FOUT: actief verdict kon niet worden geïnvalideerd" >&2
  fi
  exit 3
fi
```

- [ ] Voeg README-tekst toe: "Een geldige CLI-exit 0 of soft-only exit 10 publiceert groen. Zachte meldingen blijven via stderr in het servicejournal zichtbaar en moeten binnen 24 uur worden beoordeeld. Hard/onleesbaar, onverwachte exits en ongeldige of tegenstrijdige JSON invalideren oud groen. De scanner onderzoekt de defaultbranch, niet de geselecteerde featurecommit. Merge en hostuitrol vereisen afzonderlijk akkoord."
- [ ] Run gericht: `cd forgejo-runner && python3 tests/test_publish_trust_verdict.py && bats tests/test_publish_trust_verdict.bats tests/test_trust_timer_contract.bats && shellcheck -x scripts/publish-trust-verdict.sh`. Alle controles groen. Verifieer dat de regressietest zonder fix rood blijft; geen testverwachtingen versoepelen.
- [ ] Run volledige bestaande verificatie vanaf `forgejo-runner`: `bats tests/*.bats`, `for f in tests/test_*.py; do python3 "$f" || exit; done`, `shellcheck -x scripts/*.sh`. Log aantallen en eventuele bestaande waarschuwingen; geen ontbrekende runs als geslaagd registreren.
- [ ] Review `git diff --check` en `git diff --stat`; alleen bovengenoemde bestanden plus dit plan/reviewbewijs. Commit: `fix(forgejo-runner): preserve soft-only trust verdicts`.
- [ ] Laat de codedelta onafhankelijk reviewen via requesting-code-review; verifieer bevindingen, herstel uitsluitend binnen scope, herhaal gerichte en volledige tests na relevante wijzigingen. Bewaar review als `docs/forgejo-runner-pool/reviews/2026-09-09-iss-18-publisher.md` met exact review-SHA en verdict. Geen GO verzinnen.
- [ ] Publiceer branch op origin, verifieer remote SHA, log commit/tests/implementatie bij de eigen Scrum4Me-taak en actualiseer ISS-18. Gebruik `verify_task_against_plan(task_id, worktree_path)` waar jobbinding bestaat; zonder active job eventuele toolbeperking melden en de handmatige planscope-vergelijking vastleggen.
- [ ] Stop bij afzonderlijk merge-/uitrolakkoord. Handoff noemt exacte commit, review, tests, niet-uitgevoerde live verificatie en rollback via canonieke vorige bundelcommit. Geen issue sluiten of poolacceptatie claimen.

## Review record

Planrevision 2. Ronde 1 op `3d73461c397a249d0dcc268f228f84f45719165e`:

- mac:codex: 0 BLOCKER / 1 MAJOR / 0 MINOR, VERDICT: NO-GO. Reply `ea5e2c9b-2669-46e6-aaa1-2458e0dc4d54`. Geaccepteerd: bestandscheck vóór CLI kon exit2 geven met behouden oud groen. Gecontroleerd tegen publisher:24-25. R2 scheidt argumenten en operationele bestandsvalidatie en test ontbrekende bestanden/directories/dangling links vóór de aanroep.
- scrum4me-server:claude: 0 BLOCKER / 0 MAJOR / 1 MINOR, VERDICT: GO. Reply `f9b54ae9-030c-41c7-81dd-b9b44e31b943`. Geaccepteerd: Python-uitval omzeilde de nieuwe invalidatie. R2 behoudt een onafhankelijke shellfallback voor iedere niet-nul publisherexit, inclusief onverwachte exit3 zonder publicatie. Tests injecteren 127/1/3 via PATH. Rood vereist geen target/hashbinding; groen onveranderd volledig gebonden.
- Beide reviewers hebben de echte offline CLI-keten en de voorgestelde publisher succesvol beproefd in tijdelijke directories; mac:codex bevestigde ook RED tegen de oude publisher. Dit is planreviewbewijs, geen geïmplementeerde of uitgerolde fix.

Ronde 2 op `6d7022eaf71f2157501d7441a30b45fecf7a0238`: beide reviewers 0 BLOCKER / 0 MAJOR / 0 MINOR, beiden `VERDICT: GO`. Beide R1-fixes bevestigd, geen resterende bevindingen. mac:codex reply `78137024-b811-4cbf-a567-2001831ca46c`; scrum4me-server:claude reply `9e0fe639-6c33-4540-8c4d-b6c56b771330`. Zie `docs/forgejo-runner-pool/reviews/2026-09-09-iss-18-plan.md` voor samengevat bewijs. Deze toevoeging registreert uitsluitend ontvangen reviewresultaten; de beoordeelde taak en snippets zijn ongewijzigd.

Planstatus: dubbele GO; wacht op JP-gate vóór Scrum4Me-ceremony voor één begrensde implementatietaak, gevolgd door de verplichte ceremony-hardstop. Bestaand routeakkoord is geen mainmerge of hostuitrolakkoord.
