"""Integratie tegen een wegwerp-postgres:17. Alleen met REC_PG_INTEGRATION=1, op een host met Docker.

Raakt de productie-Postgres niet: eigen container `rec-it` op 127.0.0.1:55432.
"""
import io
import os
import subprocess
import tempfile
import time
import unittest

from _load import load

rec = load()

OLD = "a" * 64
NEW = "b" * 64
ROLE = "r_it"
NAME = "rec-it"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rotate-env-credential")


def sh(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


@unittest.skipUnless(os.environ.get("REC_PG_INTEGRATION") == "1", "REC_PG_INTEGRATION=1 niet gezet")
class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sh(["docker", "rm", "-f", NAME])
        r = sh(["docker", "run", "-d", "--rm", "--pull", "never", "--name", NAME, "-p", "127.0.0.1:55432:5432",
                "-e", "POSTGRES_PASSWORD=itpw", "-e", "POSTGRES_USER=scrum4me", "-e", "POSTGRES_DB=scrum4me",
                "postgres:17", "-c", "log_statement=all"])
        assert r.returncode == 0, r.stderr
        for _ in range(60):
            if sh(["docker", "exec", NAME, "pg_isready", "-U", "scrum4me", "-h", "127.0.0.1"]).returncode == 0:
                break
            time.sleep(1)
        r = sh(["docker", "exec", "-i", NAME, "psql", "-U", "scrum4me", "-d", "scrum4me", "-v", "ON_ERROR_STOP=1"],
               input=f"CREATE ROLE {ROLE} LOGIN PASSWORD '{OLD}';\n")
        assert r.returncode == 0, r.stderr
        cls.tmp = tempfile.TemporaryDirectory()
        cls.new_file = os.path.join(cls.tmp.name, "new.env")
        cls.old_file = os.path.join(cls.tmp.name, "old.env")
        for path, pw in ((cls.new_file, NEW), (cls.old_file, OLD)):
            with open(path, "w") as f:
                f.write(f"DATABASE_URL=postgresql://{ROLE}:{pw}@127.0.0.1:55432/scrum4me?schema=public\n")

    @classmethod
    def tearDownClass(cls):
        sh(["docker", "rm", "-f", NAME])
        cls.tmp.cleanup()

    def cli(self, argv, stdin=""):
        # als subprocess, zoals het runbook het aanroept: secret alleen op stdin
        return sh([SCRIPT] + argv, input=stdin)

    def test_rotation_end_to_end(self):
        r = self.cli(["probe", "--role", ROLE, "--file", self.old_file, "--expect", "ok"])
        self.assertEqual(r.returncode, 0, r.stderr)

        r = self.cli(["alter-role", "--role", ROLE, "--container", NAME], NEW + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok alter-role", r.stdout)

        r = self.cli(["probe", "--role", ROLE, "--file", self.new_file, "--expect", "ok"])
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cli(["probe", "--role", ROLE, "--file", self.old_file, "--expect", "reject"])
        self.assertEqual(r.returncode, 0, r.stderr)

        logs = sh(["docker", "logs", NAME])
        self.assertIn("ALTER ROLE", logs.stdout + logs.stderr)  # log_statement=all logt de statement wel
        self.assertNotIn(NEW, logs.stdout + logs.stderr)

    def test_missing_role(self):
        r = self.cli(["alter-role", "--role", "r_bestaat_niet", "--container", NAME], NEW)
        self.assertEqual(r.returncode, 1)
        self.assertIn("role missing", r.stderr)
        self.assertNotIn(NEW, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
