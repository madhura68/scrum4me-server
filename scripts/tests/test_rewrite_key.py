import glob
import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from _load import load

rec = load()

OLD = "0123456789abcdef0123456789abcdef01234567"
NEW = "fedcba9876543210fedcba9876543210fedcba98"
OTHER = "9999999999999999999999999999999999999999"
B64 = "Q3Jvc3MtYXBwLXRva2VuLXZhbHVlLWJhc2U2NHVybA_x"


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    rc = rec.main(argv, stdin=io.StringIO(stdin), out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text, mode=0o600):
        p = os.path.join(self.dir, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        return p

    def read(self, p):
        with open(p) as f:
            return f.read()

    def assertNoLeak(self, *texts):
        for t in texts:
            for s in (OLD, NEW, OTHER, B64):
                self.assertNotIn(s, t)


class RewriteKeyTest(Base):
    def test_env_variants(self):
        f = self.write("w.env", f'FORGEJO_TOKEN={OLD}\nexport FORGEJO_TOKEN="{OLD}"\nFORGEJO_TOKEN = \'{OLD}\'\nKEEP=1\n')
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", f], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), f'FORGEJO_TOKEN={NEW}\nexport FORGEJO_TOKEN="{NEW}"\nFORGEJO_TOKEN = \'{NEW}\'\nKEEP=1\n')
        self.assertIn("vervangen=3", out)
        self.assertNoLeak(out, err)

    def test_json_and_toml(self):
        j = self.write("c.json", json.dumps({"mcpServers": {"s": {"env": {"SCRUM4ME_TOKEN": OLD, "X": "y"}}}}, indent=2))
        t = self.write("c.toml", f'[mcp_servers.s.env]\nSCRUM4ME_TOKEN = "{OLD}"\n')
        rc, out, err = run(["rewrite-key", "--key", "SCRUM4ME_TOKEN", "--file", j, "--file", t], f"{OLD}\n{NEW}")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(self.read(j))["mcpServers"]["s"]["env"]["SCRUM4ME_TOKEN"], NEW)
        self.assertIn(f'SCRUM4ME_TOKEN = "{NEW}"', self.read(t))

    def test_only_value_equal_to_old_is_replaced(self):
        a = self.write("a.env", f"FORGEJO_TOKEN={OLD}\n")
        b = self.write("b.env", f"FORGEJO_TOKEN={OTHER}\nFORGEJO_TOKEN={OLD}\n")
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", a, "--file", b], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(b), f"FORGEJO_TOKEN={OTHER}\nFORGEJO_TOKEN={NEW}\n")

    def test_prefix_and_suffix_keys_not_matched(self):
        f = self.write("w.env", f"MY_FORGEJO_TOKEN={OLD}\nFORGEJO_TOKEN_OLD={OLD}\nFORGEJO_TOKEN={OLD}\n")
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", f], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), f"MY_FORGEJO_TOKEN={OLD}\nFORGEJO_TOKEN_OLD={OLD}\nFORGEJO_TOKEN={NEW}\n")

    def test_base64url_token(self):
        f = self.write("w.env", f"SCRUM4ME_TOKEN={B64}\n")
        rc, out, err = run(["rewrite-key", "--key", "SCRUM4ME_TOKEN", "--file", f], f"{B64}\n{NEW}\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), f"SCRUM4ME_TOKEN={NEW}\n")
        self.assertNoLeak(out, err)

    def test_whole_file(self):
        f = self.write("tag.token", OLD + "\n", mode=0o640)
        rc, out, err = run(["rewrite-key", "--whole-file", "--file", f], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), NEW + "\n")
        self.assertEqual(os.stat(f).st_mode & 0o777, 0o640)

    def test_whole_file_other_value_refused(self):
        f = self.write("tag.token", OTHER + "\n")
        rc, out, err = run(["rewrite-key", "--whole-file", "--file", f], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(f), OTHER + "\n")
        self.assertNoLeak(out, err)

    def test_zero_matches_refuses_all(self):
        a = self.write("a.env", f"FORGEJO_TOKEN={OLD}\n")
        b = self.write("b.env", f"FORGEJO_TOKEN={OTHER}\n")
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", a, "--file", b], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(a), f"FORGEJO_TOKEN={OLD}\n")
        self.assertEqual(glob.glob(a + ".bak-*"), [])
        self.assertIn(b, out + err)
        self.assertNoLeak(out, err)

    def test_stdin_refusals(self):
        f = self.write("w.env", f"FORGEJO_TOKEN={OLD}\n")
        for bad in (f"{OLD}\n", f"{OLD}\n{OLD}\n", f"{OLD}\n{NEW} x\n", "short\nalsoshort\n", f'{OLD}\n"{NEW}"\n', ""):
            rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", f], bad)
            self.assertEqual(rc, 2, repr(bad))
            self.assertEqual(self.read(f), f"FORGEJO_TOKEN={OLD}\n")
            self.assertNoLeak(out, err)

    def test_key_or_whole_file_required(self):
        f = self.write("w.env", f"FORGEJO_TOKEN={OLD}\n")
        rc, out, err = run(["rewrite-key", "--file", f], f"{OLD}\n{NEW}\n")
        self.assertEqual(rc, 2)

    def test_dry_run_reads_only_old(self):
        f = self.write("w.env", f"FORGEJO_TOKEN={OLD}\n")
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", f, "--dry-run"], f"{OLD}\n")
        self.assertEqual(rc, 0, err)
        self.assertIn("treffers=1", out)
        self.assertEqual(glob.glob(f + ".bak-*"), [])
        self.assertNoLeak(out, err)

    def test_rollback_restores(self):
        f = self.write("w.env", f"FORGEJO_TOKEN={OLD}\n")
        rc, out, err = run(["rewrite-key", "--key", "FORGEJO_TOKEN", "--file", f], f"{OLD}\n{NEW}\n")
        stamp = out.split("stamp=")[1].split()[0]
        rc, out, err = run(["rollback", "--stamp", stamp, "--file", f])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), f"FORGEJO_TOKEN={OLD}\n")

    def test_interrupt_midbatch_restores(self):
        files = [self.write(f"{i}.env", f"FORGEJO_TOKEN={OLD}\n") for i in range(3)]
        real = os.replace

        def boom(src, dst):
            if dst == files[1]:
                raise KeyboardInterrupt()
            return real(src, dst)

        with mock.patch.object(rec.os, "replace", side_effect=boom):
            with self.assertRaises(KeyboardInterrupt):
                run(["rewrite-key", "--key", "FORGEJO_TOKEN"] + sum([["--file", x] for x in files], []), f"{OLD}\n{NEW}\n")
        for x in files:
            self.assertEqual(self.read(x), f"FORGEJO_TOKEN={OLD}\n")


class ClassesTest(Base):
    def test_labels_without_values(self):
        a = self.write("a.env", f"FORGEJO_TOKEN={OLD}\n")
        b = self.write("b.json", json.dumps({"FORGEJO_TOKEN": OLD}))
        c = self.write("c.env", f"FORGEJO_TOKEN={OTHER}\n")
        rc, out, err = run(["classes", "--key", "FORGEJO_TOKEN", a, b, c])
        self.assertEqual(rc, 0, err)
        labels = {line.split()[-1]: line.split()[1] for line in out.splitlines() if line.strip()}
        self.assertEqual(labels[a], labels[b])
        self.assertNotEqual(labels[a], labels[c])
        self.assertNoLeak(out, err)
        self.assertIsNone(re.search(r"[0-9a-f]{16,}", out))

    def test_whole_file_classes(self):
        a = self.write("a.token", OLD + "\n")
        rc, out, err = run(["classes", "--whole-file", a])
        self.assertEqual(rc, 0, err)
        self.assertIn("waarde-A", out)
        self.assertNoLeak(out, err)


if __name__ == "__main__":
    unittest.main()
