import hashlib
import importlib.machinery
import importlib.util
import io
import os
import stat
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "compose-inpak")


def load():
    loader = importlib.machinery.SourceFileLoader("compose_inpak", SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def gnu_tar():
    try:
        res = subprocess.run(["tar", "--version"], capture_output=True, text=True)
    except OSError:
        return False
    return "GNU tar" in res.stdout


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@unittest.skipUnless(gnu_tar(), "vereist GNU tar; draai deze tests op de host")
class InpakTest(unittest.TestCase):
    def setUp(self):
        self._umask = os.umask(0o022)
        self.mod = load()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.live = self.put("live/docker-compose.yml", "services: {}\n")
        self.rows = [("proef", "running(1)", self.live)]
        self.mod.compose_ls = lambda: sorted(self.rows)
        self.copies = [
            self.put("live/docker-compose.yml.bak.1", "kopie een\n"),
            self.put("live/docker-compose.yml.bak.2", "kopie twee\n"),
            self.put("ander/docker-compose.yml.orig", "kopie drie\n"),
        ]
        self.list = self.write_list(self.copies)
        self.tar = os.path.join(self.root, "attic", "compose-history.tar")

    def tearDown(self):
        os.umask(self._umask)
        self._tmp.cleanup()

    def put(self, rel, content):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def write_list(self, paths, name="lijst.txt"):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            for p in paths:
                f.write(f"{digest(p)}  {p}\n")
        return path

    def call(self, cmd, *extra, lst=None):
        argv = [cmd, "--list", lst or self.list, "--tar", self.tar, "--base", self.root]
        if cmd == "run":
            argv += ["--expires", "2026-12-27"]
        out, err = io.StringIO(), io.StringIO()
        rc = self.mod.main(argv + list(extra), out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    def exists(self, paths):
        return [os.path.exists(p) for p in paths]

    def test_plan_changes_nothing(self):
        rc, out, _ = self.call("plan")
        self.assertEqual(rc, 0)
        self.assertEqual(self.exists(self.copies), [True, True, True])
        self.assertFalse(os.path.exists(os.path.dirname(self.tar)))
        self.assertIn("er is niets gewijzigd", out)

    def test_run_packs_reads_back_and_removes(self):
        before = [digest(p) for p in self.copies]
        live_before = digest(self.live)
        rc, out, err = self.call("run")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.exists(self.copies), [False, False, False])
        self.assertEqual(digest(self.live), live_before)
        manifest = self.tar[:-4] + ".MANIFEST.txt"
        sums = self.tar[:-4] + ".SHA256SUMS"
        for p in (self.tar, manifest, sums):
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600, p)
        # het terugzetcommando uit het MANIFEST levert de bestanden byte-gelijk terug
        with tempfile.TemporaryDirectory() as back:
            subprocess.run(["tar", "-xpf", self.tar, "-C", back], check=True)
            restored = [digest(os.path.join(back, os.path.relpath(p, self.root))) for p in self.copies]
        self.assertEqual(restored, before)
        with open(manifest) as f:
            text = f.read()
        self.assertIn("verwijderen na: 2026-12-27", text)
        self.assertIn(f"tar -xpf {self.tar} -C {self.root} live/docker-compose.yml.bak.1", text)

    def test_sidecars_hold_no_file_content(self):
        self.call("run")
        for p in (self.tar[:-4] + ".MANIFEST.txt", self.tar[:-4] + ".SHA256SUMS"):
            with open(p) as f:
                self.assertNotIn("kopie", f.read())

    def test_changed_file_before_run_stops_before_the_tar(self):
        with open(self.copies[1], "a") as f:
            f.write("later gewijzigd\n")
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("sha256 wijkt af", err)
        self.assertEqual(self.exists(self.copies), [True, True, True])
        self.assertFalse(os.path.exists(self.tar))

    def test_change_between_first_check_and_tar_is_caught_by_the_read_back(self):
        def tamper():
            with open(self.copies[1], "a") as f:
                f.write("gewijzigd na de eerste toets\n")
        self.mod.before_tar = tamper
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("teruggelezen bestand wijkt af", err)
        self.assertEqual(self.exists(self.copies), [True, True, True])

    def test_registered_config_on_the_list_stops(self):
        lst = self.write_list(self.copies + [self.live], "lijst-met-live.txt")
        rc, _, err = self.call("run", lst=lst)
        self.assertEqual(rc, 1)
        self.assertIn("geregistreerd configbestand", err)
        self.assertEqual(self.exists(self.copies + [self.live]), [True] * 4)
        self.assertFalse(os.path.exists(self.tar))

    def test_file_under_the_active_release_stops(self):
        old = self.put("releases/a/compose.yaml", "release a\n")
        active = self.put("releases/b/compose.yaml", "release b\n")
        link = os.path.join(self.root, "current")
        os.symlink(os.path.join(self.root, "releases", "b"), link)
        lst = self.write_list([old, active], "lijst-releases.txt")
        rc, _, err = self.call("run", "--current-link", link, lst=lst)
        self.assertEqual(rc, 1)
        self.assertIn("onder de actieve release", err)
        self.assertEqual(self.exists([old, active]), [True, True])

    def test_change_between_read_back_and_removal_keeps_the_rest(self):
        def tamper(path):
            if path == self.copies[1]:
                with open(path, "a") as f:
                    f.write("gewijzigd tijdens de opruiming\n")
        self.mod.before_remove = tamper
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("gestopt na 1 van 3", err)
        self.assertEqual(self.exists(self.copies), [False, True, True])
        self.assertTrue(os.path.exists(self.tar))

    def test_file_that_becomes_registered_during_removal_is_kept(self):
        def register(path):
            if path == self.copies[1]:
                self.rows.append(("proef2", "running(1)", path))
        self.mod.before_remove = register
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("geregistreerd configbestand", err)
        self.assertEqual(self.exists(self.copies), [False, True, True])

    def test_active_release_that_moves_during_removal_is_kept(self):
        a = self.put("releases/a/compose.yaml", "release a\n")
        b = self.put("releases/b/compose.yaml", "release b\n")
        self.put("releases/c/compose.yaml", "release c\n")
        link = os.path.join(self.root, "current")
        os.symlink(os.path.join(self.root, "releases", "c"), link)

        def move(path):
            if path == b:
                os.remove(link)
                os.symlink(os.path.join(self.root, "releases", "b"), link)
        self.mod.before_remove = move
        lst = self.write_list([a, b], "lijst-releases.txt")
        rc, _, err = self.call("run", "--current-link", link, lst=lst)
        self.assertEqual(rc, 1)
        self.assertIn("onder de actieve release", err)
        self.assertEqual(self.exists([a, b]), [False, True])

    def test_existing_tar_is_never_overwritten(self):
        os.makedirs(os.path.dirname(self.tar))
        with open(self.tar, "w") as f:
            f.write("bestaand\n")
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("wordt niet overschreven", err)
        with open(self.tar) as f:
            self.assertEqual(f.read(), "bestaand\n")
        self.assertEqual(self.exists(self.copies), [True, True, True])

    def test_symlink_on_the_list_stops(self):
        link = os.path.join(self.root, "live", "docker-compose.yml.bak.link")
        os.symlink(self.copies[0], link)
        lst = os.path.join(self.root, "lijst-link.txt")
        with open(lst, "w") as f:
            f.write(f"{digest(self.copies[0])}  {link}\n")
        rc, _, err = self.call("run", lst=lst)
        self.assertEqual(rc, 1)
        self.assertIn("geen gewoon bestand", err)

    def test_list_refuses_globs_relative_paths_and_duplicates(self):
        d = digest(self.copies[0])
        for name, line in (
            ("glob", f"{d}  {self.root}/live/*.bak"),
            ("relatief", f"{d}  live/docker-compose.yml.bak.1"),
            ("dubbel", f"{d}  {self.copies[0]}\n{d}  {self.copies[0]}"),
            ("hash", f"geen-hash  {self.copies[0]}"),
        ):
            lst = os.path.join(self.root, f"lijst-{name}.txt")
            with open(lst, "w") as f:
                f.write(line + "\n")
            rc, _, err = self.call("plan", lst=lst)
            self.assertEqual(rc, 1, name)
            self.assertIn("lijst regel", err, name)
        self.assertEqual(self.exists(self.copies), [True, True, True])

    def test_post_check_reports_a_changed_stack(self):
        calls = {"n": 0}

        def ls():
            calls["n"] += 1
            # vooraf 1x, per bestand 1x, daarna de natoets
            if calls["n"] > 1 + len(self.copies):
                return [("proef", "exited(1)", self.live)]
            return sorted(self.rows)
        self.mod.compose_ls = ls
        rc, _, err = self.call("run")
        self.assertEqual(rc, 1)
        self.assertIn("natoets", err)
        self.assertTrue(os.path.exists(self.tar))


if __name__ == "__main__":
    unittest.main()
