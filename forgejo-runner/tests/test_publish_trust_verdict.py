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
                    try:
                        result = self.invoke(self.fixture(0, json.dumps(GOOD)))
                        self.assert_result(result, False)
                    finally:
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
