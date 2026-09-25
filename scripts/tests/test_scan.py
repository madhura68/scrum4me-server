import io
import os
import tempfile
import unittest

from _load import load

rec = load()

OLD = "a" * 64
NEW = "b" * 64
ROLE = "scrum4me_web_runtime"


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    rc = rec.main(argv, stdin=io.StringIO(stdin), out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, content, binary=False):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if binary else "w") as f:
            f.write(content)
        return path

    def test_classes_and_exit(self):
        cur = self.put("a/current.env", f"URL=postgresql://{ROLE}:{NEW}@h/db\n")
        ph = self.put("a/doc.md", f"grep -E '{ROLE}:[^@]+@'\nURL=postgresql://{ROLE}:<pw>@h/db\n")
        leak = self.put("b/transcript.jsonl", '{"x":"noise"}\n' + f'{{"cmd":"postgresql://{ROLE}:{OLD}@h/db"}}\n')
        bak = self.put("a/current.env.bak-20260925T200000_000000Z", f"URL=postgresql://{ROLE}:{OLD}@h/db\n")
        self.put("b/blob.bin", b"\x00\x01" + f"{ROLE}:{OLD}@".encode(), binary=True)
        self.put("a/other.env", f"URL=postgresql://x{ROLE}:{OLD}@h/db\n")  # andere rol met ROLE als suffix
        rc, out, err = run(["scan", "--role", ROLE, self.root], NEW + "\n")
        self.assertEqual(rc, 1, err)
        self.assertIn(f"{cur}:1 huidig", out)
        self.assertIn(f"{ph}:1 placeholder/regex", out)
        self.assertIn(f"{ph}:2 placeholder/regex", out)
        self.assertIn(f"{leak}:2 ANDERS", out)
        self.assertIn(f"{bak}:1 ANDERS (backup)", out)
        self.assertNotIn("blob.bin", out)
        self.assertNotIn("other.env", out)
        for s in (OLD, NEW):
            self.assertNotIn(s, out + err)

    def test_only_backups_and_current_exit_zero(self):
        self.put("current.env", f"URL=postgresql://{ROLE}:{NEW}@h/db\n")
        self.put("current.env.bak-20260925T200000_000000Z", f"URL=postgresql://{ROLE}:{OLD}@h/db\n")
        rc, out, err = run(["scan", "--role", ROLE, self.root], NEW)
        self.assertEqual(rc, 0, out + err)

    def test_symlink_not_followed_and_unreadable_skipped(self):
        target = self.put("real/leak.env", f"URL=postgresql://{ROLE}:{OLD}@h/db\n")
        os.makedirs(os.path.join(self.root, "scan"))
        os.symlink(target, os.path.join(self.root, "scan", "link.env"))
        rc, out, err = run(["scan", "--role", ROLE, os.path.join(self.root, "scan")], NEW)
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("ANDERS", out)
        if os.geteuid() != 0:
            locked = self.put("scan/locked.env", "x\n")
            os.chmod(locked, 0)
            rc, out, err = run(["scan", "--role", ROLE, os.path.join(self.root, "scan")], NEW)
            self.assertIn(f"SKIP {locked}: geen toegang", out + err)

    def test_current_secret_outside_consumers_is_leak(self):
        cur = self.put("current.env", f"URL=postgresql://{ROLE}:{NEW}@h/db\n")
        tr = self.put("projects/t.jsonl", f'{{"x":"postgresql://{ROLE}:{NEW}@h/db"}}\n')
        rc, out, err = run(["scan", "--role", ROLE, "--consumer", cur, self.root], NEW)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{cur}:1 huidig", out)
        self.assertIn(f"{tr}:1 LEK", out)
        self.assertNotIn(NEW, out + err)

    def test_consumers_are_scanned_without_positional_paths(self):
        cur = self.put("current.env", f"URL=postgresql://{ROLE}:{OLD}@h/db\n")
        rc, out, err = run(["scan", "--role", ROLE, "--consumer", cur], NEW)
        self.assertEqual(rc, 1)
        self.assertIn(f"{cur}:1 ANDERS", out)

    def test_missing_path_is_not_green(self):
        self.put("current.env", f"URL=postgresql://{ROLE}:{NEW}@h/db\n")
        missing = os.path.join(self.root, "typo")
        rc, out, err = run(["scan", "--role", ROLE, self.root, missing], NEW)
        self.assertEqual(rc, 1)
        self.assertIn(f"MIST {missing}", out + err)

    def test_bad_secret_refused(self):
        rc, out, err = run(["scan", "--role", ROLE, self.root], "x")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
