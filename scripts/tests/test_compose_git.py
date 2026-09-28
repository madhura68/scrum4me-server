import hashlib
import importlib.machinery
import importlib.util
import io
import os
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join(SCRIPTS, "compose-git-init")
HOOK = os.path.join(SCRIPTS, "compose-git-pre-commit")

# Proefwaarden zijn korter dan 20 tekens: de secret-scan van deze repo weigert langere.
DUMMY = "proefwaarde"
CLEAN = "services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}\n"
LITERAL = f"services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: {DUMMY}\n"
URL = f"services:\n  web:\n    environment:\n      UPSTREAM: postgresql://app:{DUMMY}@db/app\n"


def load():
    loader = importlib.machinery.SourceFileLoader("compose_git_init", INIT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        os.environ["GIT_CONFIG_SYSTEM"] = os.devnull
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            os.environ.pop(k, None)
        self.mod = load()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(os.path.realpath(self._tmp.name), "compose")
        os.makedirs(self.dir)
        self.compose = self.put("docker-compose.yml", CLEAN)
        self.env = self.put(".env", f"POSTGRES_PASSWORD={DUMMY}\n")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def put(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def init(self, *files, extra=()):
        out, err = io.StringIO(), io.StringIO()
        argv = list(extra) + [self.dir] + list(files or ["docker-compose.yml"])
        rc = self.mod.main(argv, out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    def git(self, *args, check=False):
        res = subprocess.run(["git", "-C", self.dir] + list(args), capture_output=True, text=True)
        if check and res.returncode != 0:
            self.fail(f"git {' '.join(args)}: {res.stderr}")
        return res

    def tracked(self):
        return sorted(self.git("ls-files", check=True).stdout.split())

    def head(self):
        return self.git("rev-parse", "HEAD", check=True).stdout.strip()


class InitTest(Base):
    def test_init_tracks_exactly_the_allowlist(self):
        rc, _, err = self.init()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.tracked(), [".gitignore", "docker-compose.yml"])
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("rev-list", "--count", "HEAD", check=True).stdout.strip(), "1")

    def test_init_leaves_the_files_unchanged(self):
        before = (digest(self.compose), digest(self.env))
        self.init()
        self.assertEqual((digest(self.compose), digest(self.env)), before)

    def test_git_dir_is_private_and_the_hook_equals_its_source(self):
        self.init()
        git_dir = os.path.join(self.dir, ".git")
        self.assertEqual(stat.S_IMODE(os.stat(git_dir).st_mode), 0o700)
        hook = os.path.join(git_dir, "hooks", "pre-commit")
        self.assertEqual(digest(hook), digest(HOOK))
        self.assertTrue(os.access(hook, os.X_OK))

    def test_identity_lives_in_the_repo(self):
        self.init()
        self.assertNotEqual(self.git("config", "--local", "user.name").stdout.strip(), "")
        self.assertNotEqual(self.git("config", "--local", "user.email").stdout.strip(), "")

    def test_several_files_can_be_on_the_allowlist(self):
        self.put("docker-compose.override.yml", CLEAN)
        rc, _, _ = self.init("docker-compose.yml", "docker-compose.override.yml")
        self.assertEqual(rc, 0)
        self.assertEqual(self.tracked(), [".gitignore", "docker-compose.override.yml", "docker-compose.yml"])

    def test_dry_run_changes_nothing(self):
        before = sorted(os.listdir(self.dir))
        rc, out, _ = self.init(extra=["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(self.dir)), before)
        self.assertIn("docker-compose.yml", out)

    def test_refuses_to_run_as_root(self):
        with mock.patch.object(os, "geteuid", return_value=0):
            rc, _, err = self.init()
        self.assertEqual(rc, 1)
        self.assertIn("root", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".git")))

    def test_refuses_an_existing_repo(self):
        self.git("init", "-q", check=True)
        rc, _, err = self.init()
        self.assertEqual(rc, 1)
        self.assertIn("al een git-repo", err)

    def test_refuses_an_existing_gitignore(self):
        self.put(".gitignore", "bestaand\n")
        rc, _, err = self.init()
        self.assertEqual(rc, 1)
        with open(os.path.join(self.dir, ".gitignore")) as f:
            self.assertEqual(f.read(), "bestaand\n")
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".git")))

    def test_refuses_a_missing_file_a_path_and_a_symlink(self):
        os.symlink(self.compose, os.path.join(self.dir, "link.yml"))
        for name in ("ontbreekt.yml", "sub/docker-compose.yml", "../docker-compose.yml", "link.yml", ".env"):
            rc, _, err = self.init(name)
            self.assertEqual(rc, 1, name)
            self.assertNotEqual(err, "", name)
            self.assertFalse(os.path.exists(os.path.join(self.dir, ".git")), name)

    def test_a_failure_during_the_install_leaves_no_half_repo(self):
        before = digest(self.compose)
        real = self.mod.git

        def failing(directory, *args):
            if args and args[0] == "commit":
                raise subprocess.CalledProcessError(1, ["git", "-C", directory, "commit"], stderr="proef")
            return real(directory, *args)

        with mock.patch.object(self.mod, "git", side_effect=failing):
            rc, _, err = self.init()
        self.assertEqual(rc, 1)
        self.assertNotEqual(err, "")
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".git")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".gitignore")))
        self.assertEqual(digest(self.compose), before)

    def test_literal_secret_in_an_allowlist_file_stops_and_leaves_no_repo(self):
        self.put("docker-compose.yml", LITERAL)
        rc, _, err = self.init()
        self.assertEqual(rc, 1)
        self.assertIn("POSTGRES_PASSWORD", err)
        self.assertNotIn(DUMMY, err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".git")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".gitignore")))


class HookTest(Base):
    def setUp(self):
        super().setUp()
        rc, _, err = self.init()
        self.assertEqual((rc, err), (0, ""))
        self.first = self.head()

    def commit(self, message="proef"):
        return self.git("commit", "-q", "-m", message)

    def test_plain_add_outside_the_allowlist_is_refused(self):
        res = self.git("add", ".env")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_commit_with_a_forced_path_outside_the_allowlist_is_refused(self):
        self.git("add", "-f", ".env", check=True)
        res = self.commit()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(".env", res.stderr)
        self.assertNotIn(DUMMY, res.stderr + res.stdout)
        self.assertEqual(self.head(), self.first)

    def test_a_harmless_file_outside_the_allowlist_is_refused_too(self):
        self.put("notitie.txt", "geen geheim\n")
        self.git("add", "-f", "notitie.txt", check=True)
        res = self.commit()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("notitie.txt", res.stderr)
        self.assertEqual(self.head(), self.first)

    def test_commit_with_a_literal_secret_is_refused(self):
        self.put("docker-compose.yml", LITERAL)
        self.git("add", "docker-compose.yml", check=True)
        res = self.commit()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("POSTGRES_PASSWORD", res.stderr)
        self.assertNotIn(DUMMY, res.stderr + res.stdout)
        self.assertEqual(self.head(), self.first)

    def test_commit_with_credentials_in_a_url_is_refused(self):
        self.put("docker-compose.yml", URL)
        self.git("add", "docker-compose.yml", check=True)
        res = self.commit()
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn(DUMMY, res.stderr + res.stdout)
        self.assertEqual(self.head(), self.first)

    def test_the_staged_content_is_judged_not_the_working_file(self):
        self.put("docker-compose.yml", LITERAL)
        self.git("add", "docker-compose.yml", check=True)
        self.put("docker-compose.yml", CLEAN)
        self.assertNotEqual(self.commit().returncode, 0)

    def test_commit_with_only_interpolated_values_passes(self):
        self.put("docker-compose.yml", CLEAN + "  web:\n    environment:\n      API_TOKEN: ${API_TOKEN}\n")
        self.git("add", "docker-compose.yml", check=True)
        res = self.commit()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotEqual(self.head(), self.first)

    def test_a_comment_with_a_secret_shaped_word_passes(self):
        self.put("docker-compose.yml", "# het PASSWORD: staat in de .env\n" + CLEAN)
        self.git("add", "docker-compose.yml", check=True)
        self.assertEqual(self.commit().returncode, 0)

    def test_the_allowlist_comes_from_gitignore(self):
        self.put("docker-compose.override.yml", CLEAN)
        with open(os.path.join(self.dir, ".gitignore"), "a") as f:
            f.write("!/docker-compose.override.yml\n")
        self.git("add", ".gitignore", "docker-compose.override.yml", check=True)
        res = self.commit()
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_a_secret_file_on_the_allowlist_is_refused(self):
        with open(os.path.join(self.dir, ".gitignore"), "a") as f:
            f.write("!/.env\n")
        self.git("add", ".gitignore", ".env", check=True)
        res = self.commit()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("hoort nooit op de allowlist", res.stderr)
        self.assertNotIn(DUMMY, res.stderr + res.stdout)
        self.assertEqual(self.head(), self.first)

    def test_lowercase_and_bare_keys_are_judged_too(self):
        for line in (f"password: {DUMMY}", f"TOKEN={DUMMY}", f"      - DSN={DUMMY}"):
            self.put("docker-compose.yml", CLEAN + line + "\n")
            self.git("add", "docker-compose.yml", check=True)
            res = self.commit()
            self.assertNotEqual(res.returncode, 0, line)
            self.assertNotIn(DUMMY, res.stderr + res.stdout, line)

    def test_a_path_as_value_passes(self):
        self.put("docker-compose.yml", CLEAN + "      POSTGRES_PASSWORD_FILE: /run/secrets/pg\n")
        self.git("add", "docker-compose.yml", check=True)
        self.assertEqual(self.commit().returncode, 0)

    def test_removing_a_tracked_file_is_allowed(self):
        self.git("rm", "-q", "--cached", "docker-compose.yml", check=True)
        self.assertEqual(self.commit().returncode, 0)


class RecoveryTest(Base):
    """Het herstelrecept uit het ontwerp, onderdeel B1: alleen de index, nooit het werkbestand."""

    def setUp(self):
        super().setUp()
        rc, _, err = self.init()
        self.assertEqual((rc, err), (0, ""))

    def blob_id(self, path):
        lines = [line for line in self.git("ls-files", "-s", "--", path, check=True).stdout.split("\n") if line]
        self.assertEqual(len(lines), 1)
        mode, blob, rest = lines[0].split(" ", 2)
        self.assertEqual(rest.split("\t")[0], "0")
        return blob

    def recover(self, name):
        path = os.path.join(self.dir, name)
        before = digest(path)
        blob = self.blob_id(name)
        self.assertEqual(self.git("cat-file", "-e", blob).returncode, 0)
        self.git("restore", "--staged", "--", name, check=True)
        self.assertEqual(digest(path), before)
        self.git("gc", "-q", "--prune=now", check=True)
        self.assertNotEqual(self.git("cat-file", "-e", blob).returncode, 0)

    def test_recovery_after_a_forced_path(self):
        self.git("add", "-f", ".env", check=True)
        self.assertNotEqual(self.git("commit", "-q", "-m", "proef").returncode, 0)
        self.recover(".env")
        self.assertEqual(self.tracked(), [".gitignore", "docker-compose.yml"])

    def test_recovery_after_a_literal_secret_in_a_tracked_file(self):
        self.put("docker-compose.yml", LITERAL)
        self.git("add", "docker-compose.yml", check=True)
        self.assertNotEqual(self.git("commit", "-q", "-m", "proef").returncode, 0)
        self.recover("docker-compose.yml")
        self.assertEqual(self.git("diff", "--cached", "--quiet").returncode, 0)
        self.assertIn("docker-compose.yml", self.tracked())


if __name__ == "__main__":
    unittest.main()
