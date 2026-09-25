import glob
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from _load import load

rec = load()

OLD = "a" * 64
NEW = "b" * 64
OTHER = "c" * 64
ROLE = "scrum4me_web_runtime"


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    rc = rec.main(argv, stdin=io.StringIO(stdin), out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        for root, dirs, _ in os.walk(self.dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o700)
        self._tmp.cleanup()

    def write(self, name, text, mode=0o600):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def read(self, path):
        with open(path) as f:
            return f.read()

    def backups(self, path):
        return glob.glob(path + ".bak-*")

    def assertNoLeak(self, *texts):
        for t in texts:
            for secret in (OLD, NEW, OTHER):
                self.assertNotIn(secret, t)


ENV = (
    f"DATABASE_URL=postgresql://{ROLE}:{OLD}@h:5432/db?schema=public\n"
    f"MIGRATE_URL=postgresql://scrum4me:{OTHER}@h/db\n"
)


class RewriteTest(Base):
    def test_env_only_role_password_changes(self):
        f = self.write("w.env", ENV)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW + "\n")
        self.assertEqual(rc, 0, err)
        lines = self.read(f).splitlines()
        self.assertEqual(lines[0], f"DATABASE_URL=postgresql://{ROLE}:{NEW}@h:5432/db?schema=public")
        self.assertEqual(lines[1], f"MIGRATE_URL=postgresql://scrum4me:{OTHER}@h/db")
        self.assertIn("vervangen=1", out)
        self.assertNoLeak(out, err)

    def test_json_and_toml(self):
        j = self.write(".claude.json", json.dumps({"mcpServers": {"s": {"env": {"DATABASE_URL": f"postgresql://{ROLE}:{OLD}@h/db"}}}}, indent=2))
        t = self.write("config.toml", f'[mcp_servers.s.env]\nDATABASE_URL = "postgresql://{ROLE}:{OLD}@h/db"\n')
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", j, "--file", t], NEW)
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(self.read(j))["mcpServers"]["s"]["env"]["DATABASE_URL"], f"postgresql://{ROLE}:{NEW}@h/db")
        self.assertIn(f"{ROLE}:{NEW}@", self.read(t))
        self.assertNotIn(OLD, self.read(t))
        self.assertNoLeak(out, err)

    def test_prefix_role_not_matched(self):
        f = self.write("w.env", f"URL=postgresql://{ROLE}:{OLD}@h/db\n")
        before = self.read(f)
        rc, out, err = run(["rewrite", "--role", "scrum4me", "--file", f], NEW)
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(f), before)
        self.assertEqual(self.backups(f), [])
        self.assertNoLeak(out, err)

    def test_mode_owner_preserved_and_backup_600(self):
        f = self.write("w.env", ENV, mode=0o640)
        uid = os.stat(f).st_uid
        if os.geteuid() == 0:
            os.chown(f, 65534, os.stat(f).st_gid)
            uid = 65534
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW)
        self.assertEqual(rc, 0, err)
        st = os.stat(f)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o640)
        self.assertEqual(st.st_uid, uid)
        [bak] = self.backups(f)
        self.assertEqual(stat.S_IMODE(os.stat(bak).st_mode), 0o600)
        self.assertEqual(os.stat(bak).st_uid, uid)
        self.assertEqual(self.read(bak), ENV)

    @unittest.skipUnless(hasattr(os, "listxattr") and shutil.which("setfacl") and shutil.which("getfacl"),
                         "POSIX-ACL's alleen op Linux met setfacl")
    def test_posix_acl_preserved(self):
        # Scrum4Me/.env leest ops-agent via een ACL; os.replace mag die niet wegpoetsen
        f = self.write("w.env", ENV, mode=0o600)
        subprocess.run(["setfacl", "-m", "u:nobody:rw", f], check=True)
        before = subprocess.run(["getfacl", "-cp", f], capture_output=True, text=True, check=True).stdout
        self.assertIn("user:nobody:rw-", before)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW)
        self.assertEqual(rc, 0, err)
        after = subprocess.run(["getfacl", "-cp", f], capture_output=True, text=True, check=True).stdout
        self.assertEqual(after, before)
        [bak] = self.backups(f)
        bak_acl = subprocess.run(["getfacl", "-cp", bak], capture_output=True, text=True, check=True).stdout
        self.assertNotIn("nobody", bak_acl)  # back-up blijft strikt 0600, zonder extra rechten
        stamp = out.split("stamp=")[1].split()[0]
        rc, out, err = run(["rollback", "--stamp", stamp, "--file", f])
        self.assertEqual(rc, 0, err)
        self.assertEqual(subprocess.run(["getfacl", "-cp", f], capture_output=True, text=True, check=True).stdout, before)

    def test_warns_on_wide_mode(self):
        f = self.write("w.env", ENV, mode=0o670)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW)
        self.assertEqual(rc, 0, err)
        self.assertIn("WARN", out + err)
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o670)

    def test_zero_matches_refuses_all(self):
        f1 = self.write("a.env", ENV)
        f2 = self.write("b.env", "NOTHING=here\n")
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f1, "--file", f2], NEW)
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(f1), ENV)
        self.assertEqual(self.backups(f1), [])
        self.assertIn(f2, out + err)
        self.assertNoLeak(out, err)

    def test_midbatch_failure_rolls_back(self):
        files = [self.write(f"{i}.env", ENV) for i in range(3)]
        real_replace = os.replace

        def failing_replace(src, dst):
            if dst == files[2]:
                raise OSError("simulated")
            return real_replace(src, dst)

        with mock.patch.object(rec.os, "replace", side_effect=failing_replace):
            rc, out, err = run(["rewrite", "--role", ROLE] + sum([["--file", f] for f in files], []), NEW)
        self.assertEqual(rc, 1)
        for f in files:
            self.assertEqual(self.read(f), ENV)
        self.assertIn("teruggezet: 2", out + err)
        self.assertIn("stamp=", out + err)
        self.assertNoLeak(out, err)
        self.assertEqual([p for p in os.listdir(self.dir) if not p.endswith(".env") and ".bak-" not in p], [])

    def test_interrupt_midbatch_restores_and_reraises(self):
        files = [self.write(f"{i}.env", ENV) for i in range(3)]
        real_replace = os.replace

        def interrupting_replace(src, dst):
            if dst == files[1]:
                raise KeyboardInterrupt()
            return real_replace(src, dst)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rec.os, "replace", side_effect=interrupting_replace):
            with self.assertRaises(KeyboardInterrupt):
                rec.main(["rewrite", "--role", ROLE] + sum([["--file", f] for f in files], []),
                         stdin=io.StringIO(NEW), out=out, err=err)
        for f in files:
            self.assertEqual(self.read(f), ENV)
        self.assertIn("stamp=", out.getvalue())
        self.assertIn("teruggezet: 1", err.getvalue())
        self.assertNoLeak(out.getvalue(), err.getvalue())

    def test_sigterm_midbatch_restores(self):
        import signal
        files = [self.write(f"{i}.env", ENV) for i in range(2)]
        real_replace = os.replace

        def terminating_replace(src, dst):
            if dst == files[1]:
                os.kill(os.getpid(), signal.SIGTERM)
            return real_replace(src, dst)

        before = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(rec.os, "replace", side_effect=terminating_replace):
            with self.assertRaises(KeyboardInterrupt):
                run(["rewrite", "--role", ROLE] + sum([["--file", f] for f in files], []), NEW)
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        for f in files:
            self.assertEqual(self.read(f), ENV)

    def test_broken_stdout_midbatch_restores(self):
        files = [self.write(f"{i}.env", ENV) for i in range(2)]

        class Breaking(io.StringIO):
            def write(self, text):
                if text.startswith("ok "):
                    raise BrokenPipeError(32, "Broken pipe")
                return super().write(text)

        rc = rec.main(["rewrite", "--role", ROLE] + sum([["--file", f] for f in files], []),
                      stdin=io.StringIO(NEW), out=Breaking(), err=io.StringIO())
        self.assertEqual(rc, 1)
        for f in files:
            self.assertEqual(self.read(f), ENV)

    def test_changed_during_write_refuses(self):
        f = self.write("w.env", ENV)
        real_fsync = os.fsync
        state = {"done": False}

        def meddling_fsync(fd):
            if not state["done"]:
                state["done"] = True
                with open(f, "a") as h:
                    h.write("EXTERNAL=1\n")
            return real_fsync(fd)

        with mock.patch.object(rec.os, "fsync", side_effect=meddling_fsync):
            rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW)
        self.assertEqual(rc, 1)
        self.assertIn("EXTERNAL=1", self.read(f))
        self.assertIn(OLD, self.read(f))
        self.assertNoLeak(out, err)
        self.assertEqual([p for p in os.listdir(self.dir) if p != "w.env" and ".bak-" not in p], [])

    def test_stdin_variants(self):
        for ok in (NEW + "\n", NEW + "\r\n", NEW):
            f = self.write("w.env", ENV)
            rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], ok)
            self.assertEqual(rc, 0, repr(ok))
            self.assertIn(NEW, self.read(f))
        for bad in ("", "\n", NEW + "\n" + NEW + "\n", "B" * 64, "b" * 63, " " + NEW):
            f = self.write("w.env", ENV)
            rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], bad)
            self.assertEqual(rc, 2, repr(bad))
            self.assertEqual(self.read(f), ENV)
            self.assertNoLeak(out, err)
            self.assertNotIn("B" * 64, out + err)

    def test_invalid_role_refused(self):
        f = self.write("w.env", ENV)
        rc, out, err = run(["rewrite", "--role", "x'; drop", "--file", f], NEW)
        self.assertEqual(rc, 2)
        self.assertEqual(self.read(f), ENV)

    def test_dry_run_no_write_no_stdin(self):
        f = self.write("w.env", ENV)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f, "--dry-run"], "")
        self.assertEqual(rc, 0, err)
        self.assertIn("treffers=1", out)
        self.assertEqual(self.read(f), ENV)
        self.assertEqual(self.backups(f), [])
        self.assertNoLeak(out, err)


class RollbackTest(Base):
    def test_rollback_byte_identical(self):
        f = self.write("w.env", ENV, mode=0o640)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f], NEW)
        self.assertEqual(rc, 0, err)
        stamp = out.split("stamp=")[1].split()[0]
        rc, out, err = run(["rollback", "--stamp", stamp, "--file", f])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(f), ENV)
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o640)
        self.assertNoLeak(out, err)

    def test_rollback_missing_backup_touches_nothing(self):
        f1 = self.write("a.env", ENV)
        f2 = self.write("b.env", ENV)
        rc, out, err = run(["rewrite", "--role", ROLE, "--file", f1], NEW)
        stamp = out.split("stamp=")[1].split()[0]
        after = self.read(f1)
        rc, out, err = run(["rollback", "--stamp", stamp, "--file", f1, "--file", f2])
        self.assertEqual(rc, 1)
        self.assertEqual(self.read(f1), after)
        self.assertIn(f2, out + err)


if __name__ == "__main__":
    unittest.main()
