# forgejo-runner/tests/test_stack_invariants.py
# Het statische deel van exit 66 (R17 §6.1): per aangekondigde stack de effectieve
# waarden uit `docker compose config`, de controller.toml en de per-stack-env, en de
# invarianten tussen de stacks. De compose-aanroep is geinjecteerd; een rooktest
# draait tegen de echte compose als die er is.
import copy, hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from _harness import cr, VALID_TOML   # zet scripts/ op sys.path
import stack_invariants as si

BASIS_ENV = {
    "DIND_IMAGE": "docker.io/library/docker@sha256:" + "a" * 64,
    "RUNNER_IMAGE": "code.forgejo.org/forgejo/runner@sha256:" + "b" * 64,
    "DIND_CPU_QUOTA": "1150000", "DIND_MEM": "5368709120", "DIND_PIDS": "2048",
    "RUNNER_CPUS": "1.0", "RUNNER_MEM": "1073741824", "RUNNER_PIDS": "256",
}


class Opstelling:
    """Een wegwerpbundel (stack 02) met extra stacks onder stacks/<id>/."""

    def __init__(self, tmp, ids=("02", "03")):
        self.tmp = tmp
        self.bundle = os.path.join(tmp, "bundel")
        self.stacks_dir = os.path.join(tmp, "stacks")
        self.compose = {}          # projectnaam -> canned compose-JSON
        self.ids = list(ids)
        os.makedirs(self.bundle)
        with open(os.path.join(self.bundle, "compose.yaml"), "w") as fh:
            fh.write("x\n")
        for sid in ids:
            self.maak(sid)

    def map(self, sid):
        return self.bundle if sid == "02" else os.path.join(self.stacks_dir, sid)

    def project(self, sid):
        return "forgejo-runner" if sid == "02" else f"forgejo-runner-{sid}"

    def maak(self, sid, env_extra=None, **over):
        m = self.map(sid)
        for sub in ("credentials", "state"):
            os.makedirs(os.path.join(m, sub), exist_ok=True)
        n = int(sid) - 2
        bridge = over.get("bridge", f"fr-dind{n}")
        volume = over.get("volume", "forgejo-runner-dind-data" if sid == "02" else f"forgejo-runner-{sid}-dind-data")
        token = over.get("token", os.path.join(m, "credentials", "forgejo-token"))
        config = over.get("config", os.path.join(m, "runner-config.yml"))
        env = dict(BASIS_ENV)
        env.update(env_extra or {})
        env.update({"STACK_BRIDGE": bridge, "STACK_VOLUME": volume, "STACK_CONFIG": config, "STACK_TOKEN": token})
        with open(os.path.join(m, ".env"), "w") as fh:
            fh.write("# per-stack-env\n" + "".join(f"{k}={v}\n" for k, v in env.items()))
        if over.get("schrijf_token", True) and os.path.dirname(token) == os.path.join(m, "credentials"):
            with open(token, "w") as fh:
                fh.write(over.get("token_inhoud", f"geheim-{sid}"))
        open(os.path.join(m, "runner-config.yml"), "w").close()
        project = over.get("project", self.project(sid))
        toml = VALID_TOML.decode()
        toml = toml.replace('compose_file = "/opt/forgejo-runner/compose.yaml"',
                            f'compose_file = "{over.get("compose_file", os.path.join(self.bundle, "compose.yaml"))}"')
        toml = toml.replace('project = "forgejo-runner"', f'project = "{project}"')
        toml = toml.replace('marker_path = "/tmp/ctl/cycle-op.marker"',
                            f'marker_path = "{over.get("marker", os.path.join(m, "state", "cycle-op.marker"))}"')
        env_file = over.get("env_file", "" if sid == "02" else os.path.join(m, ".env"))
        if env_file:
            toml = toml.replace(f'project = "{project}"', f'project = "{project}"\nenv_file = "{env_file}"')
        with open(os.path.join(m, "controller.toml"), "w") as fh:
            fh.write(toml)
        self.compose[project] = {
            "name": project,
            "networks": {"runner-control": {"name": f"{project}_runner-control", "driver": "bridge",
                                            "driver_opts": {si.BRIDGE_OPT: bridge}}},
            "volumes": {"dind-data": {"name": volume}},
            "services": {"runner": {"volumes": [
                {"type": "bind", "source": config, "target": si.CONFIG_TARGET, "read_only": True},
                {"type": "bind", "source": token, "target": si.TOKEN_TARGET, "read_only": True}]}},
        }

    def run(self, argv, **kw):
        self.aanroepen.append((argv, kw))
        project = argv[argv.index("-p") + 1]
        if project not in self.compose:
            return subprocess.CompletedProcess(argv, 1, "", "no such service\nregel twee")
        return subprocess.CompletedProcess(argv, 0, json.dumps(self.compose[project]), "")

    aanroepen = None

    def check(self, ids=None):
        self.aanroepen = []
        return si.check_stacks(self.bundle, self.stacks_dir, ids or self.ids, run=self.run)


class TestStackInvarianten(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.o = Opstelling(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertViolation(self, deel, v=None):
        v = self.o.check() if v is None else v
        self.assertTrue(any(deel in m for m in v), f"{deel!r} niet in {v}")
        return v

    def test_twee_consistente_stacks_zijn_groen(self):
        self.assertEqual(self.o.check(), [])

    def test_alleen_stack_02_is_groen(self):
        self.assertEqual(self.o.check(["02"]), [])

    def test_dubbele_bridge(self):
        self.o.maak("03", bridge="fr-dind0")
        self.assertViolation("bridge is niet uniek")

    def test_dubbel_volume(self):
        self.o.maak("03", volume="forgejo-runner-dind-data")
        self.assertViolation("volume is niet uniek")

    def test_dubbel_tokenpad(self):
        self.o.maak("03", token=os.path.join(self.o.map("02"), "credentials", "forgejo-token"))
        self.assertViolation("tokenpad is niet uniek")

    def test_zelfde_tokeninhoud_onder_ander_pad(self):
        self.o.maak("03", token_inhoud="geheim-02")
        v = self.assertViolation("tokeninhoud")
        self.assertFalse(any("geheim-02" in m or hashlib.sha256(b"geheim-02").hexdigest() in m for m in v))

    def test_onleesbaar_tokenbestand_is_een_overtreding(self):
        os.remove(os.path.join(self.o.map("03"), "credentials", "forgejo-token"))
        self.assertViolation("token")

    def test_afwijkende_pin_tussen_per_stack_envs(self):
        self.o.maak("03", env_extra={"DIND_IMAGE": "docker.io/library/docker@sha256:" + "c" * 64})
        v = self.assertViolation("DIND_IMAGE")
        self.assertFalse(any("c" * 64 in m for m in v))      # sleutelnamen, geen waarden

    def test_ontbrekende_sleutel_in_een_per_stack_env(self):
        p = os.path.join(self.o.map("03"), ".env")
        with open(p) as fh:
            regels = [r for r in fh.read().splitlines() if not r.startswith("RUNNER_PIDS=")]
        with open(p, "w") as fh:
            fh.write("\n".join(regels) + "\n")
        self.assertViolation("RUNNER_PIDS")

    def test_afwijkende_caps_zijn_ook_een_overtreding(self):
        self.o.maak("03", env_extra={"DIND_MEM": "1"})
        self.assertViolation("DIND_MEM")

    def test_stack_sleutels_mogen_verschillen(self):
        self.assertEqual(self.o.check(), [])        # STACK_* verschilt al in de basisopstelling

    def test_gedeeld_marker_path(self):
        self.o.maak("03", marker=os.path.join(self.o.map("02"), "state", "cycle-op.marker"))
        self.assertViolation("marker_path is niet uniek")

    def test_marker_buiten_de_eigen_state_map(self):
        self.o.maak("03", marker=os.path.join(self.o.tmp, "elders", "cycle-op.marker"))
        self.assertViolation("marker_path")

    def test_projectnaam_wijkt_af_van_de_conventie(self):
        self.o.maak("03", project="forgejo-runner-04")
        self.assertViolation("projectnaam forgejo-runner-04 wijkt af")

    def test_controller_wijst_naar_een_ander_env_bestand(self):
        self.o.maak("03", env_file=os.path.join(self.o.map("02"), ".env"))
        self.assertViolation("env_file")

    def test_stack_03_zonder_env_file_in_de_controller(self):
        # Zonder --env-file valt compose terug op de .env van de projectmap: die van stack 02.
        self.o.maak("03", env_file="")
        self.assertViolation("env_file")

    def test_stack_02_mag_zonder_of_met_zijn_eigen_env_file(self):
        self.o.maak("02", env_file=os.path.join(self.o.map("02"), ".env"))
        self.assertEqual(self.o.check(), [])

    def test_gekopieerd_compose_bestand(self):
        kopie = os.path.join(self.o.tmp, "compose-kopie.yaml")
        shutil.copy(os.path.join(self.o.bundle, "compose.yaml"), kopie)
        self.o.maak("03", compose_file=kopie)
        self.assertViolation("compose_file")

    def test_bridge_buiten_het_guardpatroon(self):
        for naam in ("br-dind1", "fr-dind", "fr-dind1x", "fr-dind1234567890"):
            with self.subTest(naam=naam):
                self.o.maak("03", bridge=naam)
                self.assertViolation("bridge")

    def test_token_buiten_de_eigen_map(self):
        elders = os.path.join(self.o.tmp, "elders")
        os.makedirs(elders)
        with open(os.path.join(elders, "t"), "w") as fh:
            fh.write("x")
        self.o.maak("03", token=os.path.join(elders, "t"))
        self.assertViolation("token")

    def test_config_buiten_de_eigen_map(self):
        self.o.maak("03", config=os.path.join(self.o.map("02"), "runner-config.yml"))
        self.assertViolation("config")

    def test_ontbrekende_controller_toml(self):
        os.remove(os.path.join(self.o.map("03"), "controller.toml"))
        self.assertViolation("controller.toml")

    def test_compose_config_faalt(self):
        del self.o.compose["forgejo-runner-03"]
        v = self.assertViolation("docker compose config")
        self.assertFalse(any("regel twee" in m for m in v))   # alleen de eerste stderr-regel

    def test_ontbrekend_veld_in_de_effectieve_configuratie(self):
        del self.o.compose["forgejo-runner-03"]["volumes"]["dind-data"]["name"]
        self.assertViolation("effectieve")

    def test_compose_krijgt_een_schone_omgeving_en_het_profiel_cycle(self):
        os.environ["STACK_BRIDGE"] = "fr-dind9"
        try:
            self.o.check()
        finally:
            del os.environ["STACK_BRIDGE"]
        for argv, kw in self.o.aanroepen:
            self.assertNotIn("STACK_BRIDGE", kw["env"])
            self.assertIn("--profile", argv)
            self.assertEqual(argv[argv.index("--profile") + 1], "cycle")
            self.assertEqual(argv[-3:], ["config", "--format", "json"])
        drie = [a for a, _ in self.o.aanroepen if a[a.index("-p") + 1] == "forgejo-runner-03"][0]
        self.assertEqual(drie[drie.index("--env-file") + 1], os.path.join(self.o.map("03"), ".env"))
        twee = [a for a, _ in self.o.aanroepen if a[a.index("-p") + 1] == "forgejo-runner"][0]
        self.assertNotIn("--env-file", twee)


class TestEffectieveWaarden(unittest.TestCase):
    def test_pakt_waarden_op_sleutel_niet_op_positie(self):
        doc = {"name": "p", "networks": {"runner-control": {"driver_opts": {si.BRIDGE_OPT: "fr-dind1"}}},
               "volumes": {"dind-data": {"name": "v"}},
               "services": {"runner": {"volumes": [
                   {"type": "bind", "source": "/t", "target": si.TOKEN_TARGET},
                   {"type": "volume", "source": "x", "target": "/x"},
                   {"type": "bind", "source": "/c", "target": si.CONFIG_TARGET}]}}}
        self.assertEqual(si.effective_values(doc),
                         {"project": "p", "bridge": "fr-dind1", "volume": "v", "token": "/t", "config": "/c"})

    @unittest.skipUnless(shutil.which("docker") and subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0,
                         "docker compose ontbreekt")
    def test_echte_compose_uitvoer_heeft_de_verwachte_vorm(self):
        compose = os.path.join(os.path.dirname(os.path.abspath(si.__file__)), "..", "compose.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, ".env")
            with open(env, "w") as fh:
                fh.write("".join(f"{k}={v}\n" for k, v in BASIS_ENV.items()))
                fh.write(f"STACK_BRIDGE=fr-dind1\nSTACK_VOLUME=forgejo-runner-03-dind-data\n"
                         f"STACK_CONFIG={tmp}/runner-config.yml\nSTACK_TOKEN={tmp}/credentials/forgejo-token\n")
            cfg = type("C", (), {"compose_file": os.path.abspath(compose), "project": "forgejo-runner-03", "env_file": env})()
            waarden = si.effective_values(si.compose_config(cfg))
        self.assertEqual(waarden["bridge"], "fr-dind1")
        self.assertEqual(waarden["volume"], "forgejo-runner-03-dind-data")
        self.assertEqual(waarden["token"], f"{tmp}/credentials/forgejo-token")
        self.assertEqual(waarden["config"], f"{tmp}/runner-config.yml")


class TestCli(unittest.TestCase):
    def test_gebruiksfouten_geven_exit_2(self):
        for argv in ([], ["--bundle", "/x"], ["--bundle", "/x", "--stacks-dir", "/y", "--stacks", "03"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                old = sys.stderr
                sys.stderr = err
                try:
                    with self.assertRaises(SystemExit) as ctx:
                        si.main(argv)
                finally:
                    sys.stderr = old
                self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
