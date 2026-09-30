import io
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from _load import SCRIPT as _SCRIPT, load

rec = load()

OLD = "a" * 64
NEW = "b" * 64
ROLE = "scrum4me_web_runtime"
VERIFIER_RE = re.compile(r"^SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]{24}\$[A-Za-z0-9+/=]{44}:[A-Za-z0-9+/=]{44}$")


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    rc = rec.main(argv, stdin=io.StringIO(stdin), out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


def done(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class ScramTest(unittest.TestCase):
    def test_format_and_determinism(self):
        v1 = rec.scram_verifier(OLD, b"\x00" * 16)
        v2 = rec.scram_verifier(OLD, b"\x00" * 16)
        self.assertRegex(v1, VERIFIER_RE)
        self.assertEqual(v1, v2)
        self.assertNotEqual(v1, rec.scram_verifier(OLD, b"\x01" * 16))
        self.assertNotIn(OLD, v1)


class ParseDsnTest(unittest.TestCase):
    def test_query_and_default_port(self):
        text = f'X="postgresql://{ROLE}:{OLD}@10.0.0.1/db?schema=public&connection_limit=5"\n'
        d = rec.parse_dsn(text, ROLE)
        self.assertEqual((d["host"], d["port"], d["user"], d["dbname"], d["password"]),
                         ("10.0.0.1", "5432", ROLE, "db", OLD))

    def test_explicit_port_and_percent_encoding(self):
        d = rec.parse_dsn(f"U=postgres://{ROLE}:p%40ss@h.example:6543/s4m\n", ROLE)
        self.assertEqual((d["host"], d["port"], d["password"], d["dbname"]), ("h.example", "6543", "p@ss", "s4m"))

    def test_missing_role_refuses(self):
        with self.assertRaises(rec.Refusal):
            rec.parse_dsn("U=postgresql://other:x@h/db\n", ROLE)


class AlterRoleTest(unittest.TestCase):
    def test_secret_and_verifier_via_stdin_not_argv(self):
        with mock.patch.object(rec.subprocess, "run", return_value=done(0, "DO\nALTER ROLE\n")) as m:
            rc, out, err = run(["alter-role", "--role", ROLE], NEW + "\n")
        self.assertEqual(rc, 0, err)
        args, kwargs = m.call_args
        argv = " ".join(args[0])
        self.assertNotIn(NEW, argv)
        self.assertNotIn("SCRAM", argv)
        self.assertEqual(args[0][:4], ["docker", "exec", "-i", "scrum4me-postgres"])
        self.assertIn(f'ALTER ROLE "{ROLE}" PASSWORD \'SCRAM-SHA-256$4096:', kwargs["input"])
        self.assertNotIn(NEW, kwargs["input"])
        self.assertRegex(out, rf"ok alter-role {ROLE} T_alter=\d{{4}}-\d\d-\d\dT")
        self.assertNotIn(NEW, out + err)

    def test_psql_failure_reports_without_verifier(self):
        with mock.patch.object(rec.subprocess, "run", return_value=done(3, "", "ERROR:  role missing\nCONTEXT: ...SCRAM-SHA-256$4096:zzz\n")):
            rc, out, err = run(["alter-role", "--role", ROLE], NEW)
        self.assertEqual(rc, 1)
        self.assertIn("role missing", err)
        self.assertNotIn("SCRAM", out + err)
        self.assertNotIn(NEW, out + err)

    def test_bad_secret_never_calls_docker(self):
        with mock.patch.object(rec.subprocess, "run") as m:
            rc, out, err = run(["alter-role", "--role", ROLE], "nope")
        self.assertEqual(rc, 2)
        m.assert_not_called()


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.file = os.path.join(self._tmp.name, "w.env")
        with open(self.file, "w") as f:
            f.write(f"DATABASE_URL=postgresql://{ROLE}:{OLD}@127.0.0.1:55432/scrum4me?schema=public\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _capture(self, result):
        seen = {}

        def fake_run(argv, **kw):
            envfile = argv[argv.index("--env-file") + 1]
            seen["argv"] = argv
            seen["mode"] = stat.S_IMODE(os.stat(envfile).st_mode)
            with open(envfile) as f:
                seen["env"] = f.read()
            seen["path"] = envfile
            if isinstance(result, BaseException):
                raise result
            return result
        return seen, fake_run

    def test_ok(self):
        seen, fake = self._capture(done(0, "1\n"))
        with mock.patch.object(rec.subprocess, "run", side_effect=fake):
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", "ok"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(seen["mode"], 0o600)
        self.assertIn(f"PGPASSWORD={OLD}\n", seen["env"])
        self.assertIn("PGPORT=55432\n", seen["env"])
        self.assertIn("PGDATABASE=scrum4me\n", seen["env"])
        self.assertNotIn(OLD, " ".join(seen["argv"]))
        self.assertIn("--pull", seen["argv"])
        self.assertFalse(os.path.exists(seen["path"]))
        self.assertNotIn(OLD, out + err)

    def test_reject(self):
        seen, fake = self._capture(done(2, "", 'psql: error: FATAL:  password authentication failed for user "x"\n'))
        with mock.patch.object(rec.subprocess, "run", side_effect=fake):
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", "reject"])
        self.assertEqual(rc, 0, err)
        rc, out, err = (None, None, None)

    def test_ok_expected_but_rejected_fails(self):
        _, fake = self._capture(done(2, "", "FATAL:  password authentication failed\n"))
        with mock.patch.object(rec.subprocess, "run", side_effect=fake):
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", "ok"])
        self.assertEqual(rc, 1)
        self.assertIn("auth", out + err)

    def test_network_error_is_not_reject(self):
        _, fake = self._capture(done(2, "", "psql: error: connection to server at \"127.0.0.1\", port 55432 failed: Connection refused\n"))
        with mock.patch.object(rec.subprocess, "run", side_effect=fake):
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", "reject"])
        self.assertEqual(rc, 1)
        self.assertIn("netwerk", out + err)

    def test_missing_file_is_clean_failure(self):
        with mock.patch.object(rec.subprocess, "run") as m:
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file + ".nope", "--expect", "ok"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", err)
        m.assert_not_called()

    def test_envfile_removed_on_exception(self):
        seen, fake = self._capture(KeyboardInterrupt())
        with mock.patch.object(rec.subprocess, "run", side_effect=fake):
            with self.assertRaises(KeyboardInterrupt):
                run(["probe", "--role", ROLE, "--file", self.file, "--expect", "ok"])
        self.assertFalse(os.path.exists(seen["path"]))


class ProbeSignalAndTimeoutTest(unittest.TestCase):
    """AUDIT-029: signalen en hangende subprocessen laten geen wachtwoordbestand of vage toestand achter."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.file = os.path.join(self._tmp.name, "w.env")
        with open(self.file, "w") as f:
            f.write(f"DATABASE_URL=postgresql://{ROLE}:{OLD}@127.0.0.1:55432/scrum4me\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_docker(self):
        bindir = os.path.join(self._tmp.name, "bin")
        os.mkdir(bindir)
        with open(os.path.join(bindir, "docker"), "w") as f:
            f.write("#!/bin/sh\nexec sleep 30\n")
        os.chmod(os.path.join(bindir, "docker"), 0o755)
        return bindir

    def test_sigterm_in_process_removes_envfile_and_restores_handler(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["path"] = argv[argv.index("--env-file") + 1]
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)  # de handler raise't hier

        before = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(rec.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(KeyboardInterrupt):
                run(["probe", "--role", ROLE, "--file", self.file, "--expect", "ok"])
        self.assertTrue(seen["path"])
        self.assertFalse(os.path.exists(seen["path"]))
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)

    def test_sigterm_real_process_leaves_no_temp_file(self):
        tmpdir = os.path.join(self._tmp.name, "tmp")
        os.mkdir(tmpdir)
        bindir = self._fake_docker()
        env = dict(os.environ, TMPDIR=tmpdir, PATH=bindir + os.pathsep + os.environ["PATH"])
        proc = subprocess.Popen(
            [sys.executable, _SCRIPT, "probe", "--role", ROLE, "--file", self.file, "--expect", "ok"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(100):
                if os.listdir(tmpdir):
                    break
                time.sleep(0.1)
            self.assertTrue(os.listdir(tmpdir), "tijdelijk bestand is nooit aangemaakt")
            time.sleep(0.5)  # docker-stub draait
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(os.listdir(tmpdir), [])

    def test_probe_timeout_is_failure_and_cleans_up(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["path"] = argv[argv.index("--env-file") + 1]
            seen["timeout"] = kw.get("timeout")
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

        for expect in ("ok", "reject"):
            with mock.patch.object(rec.subprocess, "run", side_effect=fake_run):
                rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", expect])
            self.assertEqual(rc, 1)
            self.assertIn("time-out", err)
            self.assertNotIn("geweigerd zoals verwacht", out)
            self.assertFalse(os.path.exists(seen["path"]))
        self.assertEqual(seen["timeout"], rec.SUBPROCESS_TIMEOUT)

    def test_alter_role_timeout_is_failure(self):
        def fake_run(argv, **kw):
            self.assertEqual(kw.get("timeout"), rec.SUBPROCESS_TIMEOUT)
            raise subprocess.TimeoutExpired(argv, kw["timeout"])

        with mock.patch.object(rec.subprocess, "run", side_effect=fake_run):
            rc, out, err = run(["alter-role", "--role", ROLE], NEW)
        self.assertEqual(rc, 1)
        self.assertIn("time-out", err)
        self.assertNotIn(NEW, out + err)

    def test_hanging_real_subprocess_times_out(self):
        # echte subprocess.run met een hangend commando; de constante is klein gemaakt voor de test
        bindir = self._fake_docker()
        with mock.patch.dict(os.environ, {"PATH": bindir + os.pathsep + os.environ["PATH"]}), \
                mock.patch.object(rec, "SUBPROCESS_TIMEOUT", 1):
            t0 = time.monotonic()
            rc, out, err = run(["probe", "--role", ROLE, "--file", self.file, "--expect", "ok"])
        self.assertEqual(rc, 1)
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn("time-out", err)


if __name__ == "__main__":
    unittest.main()
