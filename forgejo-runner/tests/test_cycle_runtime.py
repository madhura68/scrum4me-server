# forgejo-runner/tests/test_cycle_runtime.py
import contextlib, hashlib, http.client, io, os, subprocess, tempfile, unittest, urllib.error
from _harness import cr, write_toml, VALID_TOML, RC, classify_probe, FakePopen, build_runtime, State
import cycle_adapters as ca

class TestConfig(unittest.TestCase):
    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cr.load_config(write_toml(tmp))
        self.assertEqual(cfg.forgejo_base_url, "https://git.jp-visser.nl")
        self.assertEqual(cfg.child_stop_grace, 200.0)
        self.assertEqual(cfg.marker_path, "/tmp/ctl/cycle-op.marker")
    def test_missing_key_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = VALID_TOML.replace(b'project = "forgejo-runner"', b"")
            with self.assertRaises(ValueError) as ctx:
                cr.load_config(write_toml(tmp, bad))
        self.assertIn("dind.project", str(ctx.exception))

class TestImages(unittest.TestCase):
    REAL = ("# commentaar\ncatthehacker/ubuntu@sha256:" + "c"*64 + "\t1729048576\n")
    def test_digest_tab_bytes(self):
        self.assertEqual(cr.parse_allowed_images(self.REAL), ["catthehacker/ubuntu@sha256:" + "c"*64])
    def test_blank_comment_ignored(self):
        self.assertEqual(cr.parse_allowed_images("\n#x\n  \n"), [])
    def test_invalid_raises(self):
        with self.assertRaises(ValueError): cr.parse_allowed_images("ubuntu:latest\t10\n")

class TestVerdict(unittest.TestCase):
    def _cfg(self):
        with tempfile.TemporaryDirectory() as tmp: return cr.load_config(write_toml(tmp))
    def _v(self, **o):
        b = {"ok": True, "measured_at": 1000.0, "forgejo_target": "https://git.jp-visser.nl",
             "labels_sha256": "LS", "allowlist_sha256": "AS"}; b.update(o); return b
    def test_green(self): self.assertTrue(cr.verdict_green(self._v(), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_not_ok(self): self.assertFalse(cr.verdict_green(self._v(ok=False), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_future(self): self.assertFalse(cr.verdict_green(self._v(measured_at=2000.0), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_too_old(self): self.assertFalse(cr.verdict_green(self._v(), 1000.0+86401, self._cfg(), "LS", "AS")[0])
    def test_nan(self): self.assertFalse(cr.verdict_green(self._v(measured_at=float("nan")), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_inf(self): self.assertFalse(cr.verdict_green(self._v(measured_at=float("inf")), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_bool_ts(self): self.assertFalse(cr.verdict_green(self._v(measured_at=True), 1500.0, self._cfg(), "LS", "AS")[0])
    def test_binding(self): self.assertFalse(cr.verdict_green(self._v(), 1500.0, self._cfg(), "OTHER", "AS")[0])
    def test_non_dict(self): self.assertFalse(cr.verdict_green(None, 1500.0, self._cfg(), "LS", "AS")[0])

class TestReadinessConfirmed(unittest.TestCase):
    def test_trace(self):
        r = cr.ReadinessConfirmed()
        r.observe(RC.READY, 0.0);  self.assertFalse(r.confirmed)
        r.observe(RC.READY, 30.0); self.assertTrue(r.confirmed)
        r.observe(RC.SOURCE_WAIT, 60.0); self.assertFalse(r.confirmed)
        r.observe(RC.READY, 120.0); self.assertFalse(r.confirmed)
        r.observe(RC.READY, 150.0); self.assertTrue(r.confirmed)
    def test_too_close(self):
        r = cr.ReadinessConfirmed(); r.observe(RC.READY, 0.0); r.observe(RC.READY, 1.0)
        self.assertFalse(r.confirmed)

class TestProbe(unittest.TestCase):
    def _p(self, opener): return ca.TransportProbe("https://x", 5.0, opener=opener).probe()
    def test_ready(self):
        self.assertEqual(classify_probe(self._p(lambda r, timeout: io.BytesIO(b'{"version":"1"}'))), RC.READY)
    def test_wrong_schema_not_ready(self):
        p = self._p(lambda r, timeout: io.BytesIO(b'{"note":"no version here"}'))
        self.assertEqual(classify_probe(p), RC.PROTOCOL)     # geen version-veld
    def test_5xx(self):
        def o(r, timeout): raise urllib.error.HTTPError("u", 503, "x", {}, None)
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)
    def test_401_protocol(self):
        def o(r, timeout): raise urllib.error.HTTPError("u", 401, "x", {}, None)
        self.assertEqual(classify_probe(self._p(o)), RC.PROTOCOL)
    def test_urlerror(self):
        def o(r, timeout): raise urllib.error.URLError("refused")
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)
    def test_readtimeout(self):
        def o(r, timeout): raise TimeoutError("read timed out")
        self.assertEqual(classify_probe(self._p(o)), RC.SOURCE_WAIT)

class TestDockerAdapters(unittest.TestCase):
    def setUp(self):
        self.spawned = []; self.popen = lambda argv, **kw: self.spawned.append((argv, kw)) or FakePopen(argv)
    def test_runner_argv(self):
        ca.RunnerLifecycle("/c", "p", popen=self.popen).start()
        self.assertEqual(self.spawned[-1][0],
            ["docker","compose","-f","/c","-p","p","--profile","cycle","run","--rm","runner"])
    def test_pull_argv_has_endpoint(self):
        ca.PullOp("/c","p", popen=self.popen).start("img@sha256:"+"a"*64)
        argv = self.spawned[-1][0]
        self.assertEqual(argv[:8], ["docker","compose","-f","/c","-p","p","exec","-T"])
        self.assertIn("-H", argv); self.assertIn("tcp://127.0.0.1:2375", argv)
        self.assertIn("pull", argv); self.assertIn("img@sha256:"+"a"*64, argv)
    def test_scrub_argv_and_opens_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            sc = os.path.join(tmp, "scrub.sh")
            with open(sc, "wb") as f: f.write(b"#!/bin/sh\n")
            ca.ScrubOp("/c","p", sc, "/etc/forgejo-runner/allowed-job-images.txt", popen=self.popen).start()
        argv, kw = self.spawned[-1]
        self.assertIn("--endpoint", argv); self.assertIn("tcp://127.0.0.1:2375", argv)
        self.assertIn("--allow", argv); self.assertIn("/etc/forgejo-runner/allowed-job-images.txt", argv)
        self.assertIn("stdin", kw)          # script via stdin

def _cp(out="", rc=0, err=""):
    class C: pass
    c = C(); c.returncode = rc; c.stdout = out; c.stderr = err; return c

class TestReconcileAdapter(unittest.TestCase):
    def test_leftover_ok(self):
        rec = ca.Reconcile("/c","p","/m", run=lambda a,t: _cp("abc\n"))
        self.assertEqual(rec.leftover_runners(), ["abc"])
    def test_leftover_rc_error_raises(self):
        rec = ca.Reconcile("/c","p","/m", run=lambda a,t: _cp("", rc=1, err="boom"))
        with self.assertRaises(ca.ReconcileError): rec.leftover_runners()
    def test_leftover_uses_raw_label_filtered_docker_ps(self):
        # C1: een one-off runner (compose --profile cycle run --rm) draagt
        # com.docker.compose.oneoff=True en is onzichtbaar voor `compose ps`;
        # leftover-detectie MOET dus de raw, label-filterde `docker ps -a` zijn.
        seen = []
        rec = ca.Reconcile("/c","p","/m", run=lambda a,t: seen.append(a) or _cp("abc\n"))
        self.assertEqual(rec.leftover_runners(), ["abc"])
        argv = seen[-1]
        self.assertEqual(argv[:3], ["docker", "ps", "-a"])          # NIET "docker compose ps"
        self.assertIn("label=com.docker.compose.service=runner", argv)
        self.assertIn("label=com.docker.compose.project=p", argv)   # self._project uit __init__
    def test_restart_kill_fail_raises(self):
        calls = {"n": 0}
        def run(a, t):
            calls["n"] += 1; return _cp(rc=0) if "up" in a else _cp(rc=1)   # kill faalt
        rec = ca.Reconcile("/c","p","/m", run=run)
        with self.assertRaises(ca.ReconcileError): rec.restart_dind()
    def test_marker_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mk = os.path.join(tmp, "c", "m"); rec = ca.Reconcile("/c","p",mk, run=lambda a,t:_cp())
            self.assertFalse(rec.marker_present()); rec.write_marker("scrub")
            self.assertTrue(rec.marker_present()); rec.clear_marker(); self.assertFalse(rec.marker_present())
    def test_verdict_reader_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp=os.path.join(tmp,"l");
            with open(lp,"wb") as f: f.write(b"x")
            ap=os.path.join(tmp,"a")
            with open(ap,"wb") as f: f.write(b"y")
            vp=os.path.join(tmp,"v")
            with open(vp,"w") as f: f.write('{"ok":true}')
            v, ls, as_ = ca.TrustVerdictReader(vp, lp, ap).read()
            self.assertEqual(v, {"ok": True}); self.assertEqual(ls, hashlib.sha256(b"x").hexdigest())

class TestStartCondition(unittest.TestCase):
    def test_no_start_before_confirmed_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.tick()                                   # één probe → onbevestigd
            self.assertNotIn("runner", rec.starts)
    def test_start_after_confirmed_clean_pulled(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            for _ in range(8):
                clock.advance(30.0); rt.tick()          # scrub/pull voltooien vanzelf (auto rc0)
            self.assertIn("scrub", rec.starts); self.assertIn("pull", rec.starts); self.assertIn("runner", rec.starts)
            self.assertTrue(rec.starts.index("runner") > rec.starts.index("pull") > rec.starts.index("scrub"))

class TestCycle(unittest.TestCase):
    def _ready(self, rt, rec, clock, n=8):
        for _ in range(n): clock.advance(30.0); rt.tick()   # scrub/pull auto rc0
    def test_exit0_scrub_ok_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp); self._ready(rt, rec, clock)
            self.assertIn("runner", rec.starts)
            rec.pops["runner"].rc = 0                            # runner exit 0
            clock.advance(30.0); rt.tick()                       # child_exit → scrub gestart
            clock.advance(30.0); rt.tick()                       # scrub (auto rc0) verwerkt
            self.assertTrue(rt.clean_proven)                     # schoonbewijs vóór de volgende launch
    def test_scrub_fail_blocks_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp); self._ready(rt, rec, clock)
            rec.pops["runner"].rc = 0; rec.auto["scrub"] = 50   # post-exit scrub faalt
            for _ in range(3): clock.advance(30.0); rt.tick()
            self.assertFalse(rt.clean_proven); self.assertFalse(rt._may_start())   # geen start op vuile DinD (B2)
            self.assertFalse(rt.controller.mag_child_starten)   # hart quarantineert op scrub_done(ok=False): de echte B2-blokkade

class TestStartupReconcile(unittest.TestCase):
    def test_leftover_blocks_all_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp, leftover=["live"])
            for _ in range(6): clock.advance(30.0); rt.tick()
            self.assertTrue(rt._blocked); self.assertEqual(rec.starts, [])   # géén scrub/pull/runner (B1)
    def test_marker_triggers_restart_and_scrub(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = {"restart": 0}
            rt, ctrl, rec, clock = build_runtime(tmp, marker=True)
            rec.auto["scrub"] = None                              # herstelscrub loopt nog
            rt.a.reconcile.restart_dind = lambda: calls.__setitem__("restart", 1)
            rt.tick()
            self.assertEqual(calls["restart"], 1); self.assertIn("scrub", rec.starts)
            self.assertFalse(rt.clean_proven)                     # scrub nog niet bewezen
            rec.pops["scrub"].rc = 0; rt.tick()                   # scrub af → schoon
            self.assertTrue(rt.clean_proven)

class TestDindHealthResilience(unittest.TestCase):
    """I1: een gewedgede binnen-DinD mag de daemon niet crash-loopen (§7.4)."""
    def test_healthy_subprocess_error_degrades_gates_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            def boom(): raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
            rt.a.dind.healthy = boom
            rt.tick()                                        # mag niet crashen
            self.assertFalse(rt.controller.gates_groen)       # fail-closed: ongezond
    def test_ensure_up_subprocess_error_does_not_crash_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            def boom(): raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
            rt.a.dind.ensure_up = boom
            rt.tick()                                         # mag niet crashen
            self.assertTrue(rt.controller.gates_groen)         # health-check zelf draait alsnog

class TestStop(unittest.TestCase):
    def test_stop_with_child_no_new_scrub_exit_after_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.child = rec._mk("runner"); rt.request_stop()
            self.assertIn(15, rt.child.signals)              # SIGTERM naar child
            rt.child.rc = None; self.assertFalse(rt._stop_complete())
            rt.child.rc = 0; rt._advance_child()
            self.assertIsNone(rt.op)                          # géén nieuwe scrub tijdens stop (M4)
            self.assertTrue(rt._stop_complete())
    def test_stop_during_scrub_signals_and_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            sp = rec._mk("scrub"); sp.rc = None; rt.op = ("scrub", sp)
            rt.request_stop()
            self.assertIn(15, sp.signals)                    # scrub gesignaleerd (M4/§9)
            self.assertFalse(rt._stop_complete())
            sp.rc = 0; rt._advance_op(); self.assertTrue(rt._stop_complete())
    def test_stop_before_first_tick_no_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp, marker=True)
            calls = {"r": 0}; rt.a.reconcile.restart_dind = lambda: calls.__setitem__("r", 1)
            rt.request_stop(); rt.tick()
            self.assertEqual(calls["r"], 0); self.assertEqual(rec.starts, [])   # geen reconcile/scrub bij stop (M4)
    def test_stop_killed_op_is_unclean(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            sp = rec._mk("scrub"); rt.op = ("scrub", sp)
            rt.a.reconcile.write_marker("scrub")                   # operatie in-flight
            rt.request_stop(); sp.rc = -15                         # client door signaal gedood
            rt._advance_op()
            self.assertTrue(rt.a.reconcile.marker_present())       # marker bewaard (onzeker einde)
            self.assertEqual(rt._stop_result(overshoot=False), 1)  # géén exit 0 (M1)
    def test_deadline_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.child = rec._mk("runner"); rt.child.rc = None
            self.assertEqual(rt._stop_result(overshoot=True), 1)   # geen succes bij deadline

def _check_toml(tmp, **wijzig):
    """VALID_TOML met padverwijzingen naar echte tempbestanden; wijzig = {oud: nieuw}."""
    for n in ("compose.yaml", "images.txt", "labels.txt", "allow.yml"):
        open(os.path.join(tmp, n), "w").close()
    t = VALID_TOML.decode()
    for oud, nieuw in (
        ("/opt/forgejo-runner/compose.yaml", f"{tmp}/compose.yaml"),
        ("/opt/forgejo-runner/allowed-job-images.txt", f"{tmp}/images.txt"),
        ("/opt/forgejo-runner/labels.txt", f"{tmp}/labels.txt"),
        ("/opt/forgejo-runner/trusted-actions-scope.yml", f"{tmp}/allow.yml"),
        ("/opt/forgejo-runner/trust-verdict.json", f"{tmp}/verdict.json"),
        ("/tmp/ctl/cycle-op.marker", f"{tmp}/marker"),
    ):
        t = t.replace(oud, nieuw)
    for oud, nieuw in wijzig.items():
        assert oud in t, oud
        t = t.replace(oud, nieuw)
    return write_toml(tmp, t.encode())

class TestMain(unittest.TestCase):
    def _check(self, **wijzig):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _check_toml(tmp, **wijzig)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = cr.main(["--config", cfg_path, "--check"])
            return rc, err.getvalue()
    def test_check_mode(self):
        self.assertEqual(self._check(), (0, ""))
    def test_missing_config(self):
        self.assertNotEqual(cr.main(["--config", "/nope.toml"]), 0)
    def test_check_missing_file(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cr.main(["--config", "/nope.toml", "--check"])
        self.assertEqual(rc, 2)
        self.assertIn("config-fout:", err.getvalue())
    def test_check_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _check_toml(tmp)
            with open(p) as fh:
                t = fh.read().replace('project = "forgejo-runner"', "")
            with open(p, "w") as fh:
                fh.write(t)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cr.main(["--config", p, "--check"]), 2)
        self.assertIn("dind.project", err.getvalue())
    def test_check_nonexistent_paths_all_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Paden onder een niet-bestaande map in tmp: de /opt-paden uit VALID_TOML
            # bestaan wél op een uitgerolde host (max2), dan faalt deze test daar.
            weg = os.path.join(tmp, "bestaat-niet")
            data = VALID_TOML.replace(b"/opt/forgejo-runner", weg.encode()).replace(b"/tmp/ctl", (weg + "/ctl").encode())
            p = write_toml(tmp, data)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cr.main(["--config", p, "--check"]), 2)
        for naam in ("compose_file", "allowed_images_file", "labels_file",
                     "allowlist_file", "marker_path", "trust_verdict_path"):
            self.assertIn(naam, err.getvalue())
    def test_check_poll_zero(self):
        rc, err = self._check(**{"poll_interval_seconds = 1": "poll_interval_seconds = 0"})
        self.assertEqual(rc, 2)
        self.assertIn("poll_interval", err)
    def test_check_bad_level(self):
        rc, err = self._check(**{'level = "INFO"': 'level = "LUID"'})
        self.assertEqual(rc, 2)
        self.assertIn("log.level", err)
    def test_check_grace_at_unit_timeout(self):
        rc, err = self._check(**{"child_stop_grace_seconds = 200": "child_stop_grace_seconds = 300"})
        self.assertEqual(rc, 2)
        self.assertIn("TimeoutStopSec", err)
    def test_check_reports_multiple_problems(self):
        rc, err = self._check(**{"poll_interval_seconds = 1": "poll_interval_seconds = -1",
                                 'level = "INFO"': 'level = "X"'})
        self.assertEqual(rc, 2)
        self.assertIn("poll_interval", err)
        self.assertIn("log.level", err)
    def test_documented_command_via_subprocess(self):
        scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
        with tempfile.TemporaryDirectory() as tmp:
            cp = subprocess.run(
                ["python3", "-B", "scripts/cycle_runtime.py", "--config",
                 os.path.join(tmp, "missing.toml"), "--check"],
                cwd=scripts, capture_output=True, text=True, timeout=30)
            self.assertEqual(cp.returncode, 2)
            self.assertIn("config-fout:", cp.stderr)
            ok = subprocess.run(
                ["python3", "-B", "scripts/cycle_runtime.py", "--config",
                 _check_toml(tmp), "--check"],
                cwd=scripts, capture_output=True, text=True, timeout=30)
            self.assertEqual(ok.returncode, 0, ok.stderr)

class TestLogging(unittest.TestCase):
    def test_alarm_events_are_logged(self):
        import logging
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.loop.submit("alarm", {"klasse": "X", "reden": "test"})
                rt._drain_events()
            self.assertTrue(any("alarm" in m for m in cm.output))

class TestTrustgateLogging(unittest.TestCase):
    """Een rode trustgate moet zijn reden loggen, één keer per wissel (max2 ISS-8)."""
    def test_red_gate_logs_reason_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt._trust_green = lambda: (False, "verdict is te oud")
            with self.assertLogs(rt.log, level="INFO") as cm:
                for _ in range(3):
                    rt._readiness_and_gates(clock()[1])
            rood = [m for m in cm.output if "trustgate ROOD" in m]
            self.assertEqual(len(rood), 1)
            self.assertIn("WARNING", rood[0])
            self.assertIn("verdict is te oud", rood[0])
            self.assertFalse(ctrl.gates_groen)
    def test_recovery_and_new_reason_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            staat = {"v": (False, "ok is niet true")}
            rt._trust_green = lambda: staat["v"]
            with self.assertLogs(rt.log, level="INFO") as cm:
                rt._readiness_and_gates(clock()[1])
                staat["v"] = (False, "allowlist-binding mismatch")
                rt._readiness_and_gates(clock()[1])
                staat["v"] = (True, "groen")
                rt._readiness_and_gates(clock()[1])
                rt._readiness_and_gates(clock()[1])
            berichten = [m.split(":", 2)[2] for m in cm.output]
            self.assertEqual(berichten, [
                "trustgate ROOD: ok is niet true → geen nieuwe runners",
                "trustgate ROOD: allowlist-binding mismatch → geen nieuwe runners",
                "trustgate groen",
            ])
            self.assertTrue(ctrl.gates_groen)

class TestAdapterHardening(unittest.TestCase):
    def test_probe_incompleteread_is_transport_failure(self):
        class R:
            status = 200
            def read(self): raise http.client.IncompleteRead(b"{")
        p = ca.TransportProbe("https://x", 5.0, opener=lambda r, timeout: R()).probe()
        self.assertIn("IncompleteRead", p["error"])
        self.assertNotEqual(classify_probe(p), RC.READY)
    def test_probe_oserror_during_read_is_transport_failure(self):
        class R:
            status = 200
            def read(self): raise ConnectionResetError("reset")
        p = ca.TransportProbe("https://x", 5.0, opener=lambda r, timeout: R()).probe()
        self.assertIn("ConnectionResetError", p["error"])
        self.assertNotEqual(classify_probe(p), RC.READY)
    def test_verdict_reader_permissionerror_fail_closed(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            lp = os.path.join(tmp, "l"); ap = os.path.join(tmp, "a"); vp = os.path.join(tmp, "v")
            for q in (lp, ap, vp):
                with open(q, "w") as f: f.write("{}")
            real = open
            def deny(path, *a, **k):
                if path == vp: raise PermissionError(13, "denied")
                return real(path, *a, **k)
            r = ca.TrustVerdictReader(vp, lp, ap)
            with mock.patch("builtins.open", deny):
                v, ls, as_ = r.read()
            self.assertIsNone(v); self.assertIn("PermissionError", r.last_error)
            self.assertFalse(cr.verdict_green(v, 1.0, cr.load_config(write_toml(tmp)), ls, as_)[0])
    def test_dind_ensure_up_returns_rc_and_healthy_records_rc(self):
        d = ca.DindHealth("/c", "p", run=lambda a, t: _cp(rc=3))
        self.assertEqual(d.ensure_up(), 3)
        self.assertFalse(d.healthy()); self.assertEqual(d.last_rc, 3)

class TestRuntimeGuards(unittest.TestCase):
    def _rt(self, tmp, **kw):
        rt, ctrl, rec, clock = build_runtime(tmp, **kw)
        rt._trust_green = type(rt)._trust_green.__get__(rt)   # echte guard i.p.v. harness-stub
        return rt, ctrl, rec, clock
    def test_probe_exception_logged_and_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            def boom(): raise RuntimeError("kapot")
            rt, ctrl, rec, clock = self._rt(tmp, probe_seq=boom)
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.tick()
            self.assertTrue(any("RuntimeError: kapot" in m for m in cm.output))
            self.assertFalse(rt.readiness.confirmed)
    def test_trust_read_exception_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = self._rt(tmp)
            def boom(): raise PermissionError("nee")
            rt.a.trust.read = boom
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.tick()
            self.assertFalse(ctrl.gates_groen)
            self.assertTrue(any("trustgate ROOD: trust-read faalde: PermissionError" in m for m in cm.output))
    def test_trust_reader_detail_in_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = self._rt(tmp)
            rt.a.trust.read = lambda: (None, "", "")
            rt.a.trust.last_error = "verdict onleesbaar: PermissionError"
            green, reden = rt._trust_green()
            self.assertFalse(green); self.assertIn("PermissionError", reden)
    def test_runner_start_exception_keeps_child_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            def boom(): raise OSError("docker weg")
            rt.a.runner.start = boom
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt._start_runner()
            self.assertIsNone(rt.child)
            self.assertTrue(any("runner-start faalde: OSError: docker weg" in m for m in cm.output))
    def test_baseexception_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            def stop(): raise KeyboardInterrupt()
            rt.a.probe.probe = stop
            with self.assertRaises(KeyboardInterrupt): rt.tick()

class TestGateTransitionLogging(unittest.TestCase):
    def test_dind_transitions_once_with_rc_and_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            st = {"h": False}; rt.a.dind.last_rc = 1; rt.a.dind.healthy = lambda: st["h"]
            with self.assertLogs(rt.log, level="INFO") as cm:
                rt._readiness_and_gates(0); rt._readiness_and_gates(1)
                st["h"] = True; rt._readiness_and_gates(2); rt._readiness_and_gates(3)
                def boom(): raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
                rt.a.dind.healthy = boom; rt._readiness_and_gates(4)
            msgs = [m.split(":", 2)[2] for m in cm.output if "dind" in m]
            self.assertEqual(len(msgs), 3)
            self.assertIn("ROOD: rc=1", msgs[0]); self.assertEqual(msgs[1], "dind gezond")
            self.assertIn("TimeoutExpired", msgs[2])
    def test_blocked_logged_with_reason_and_reminder_per_retry_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp, leftover=["abc"])
            with self.assertLogs(rt.log, level="WARNING") as cm:
                for _ in range(65):
                    rt.tick(); clock.advance(1.0)
            geb = [m for m in cm.output if "GEBLOKKEERD" in m]
            rem = [m for m in cm.output if "nog steeds geblokkeerd" in m]
            self.assertEqual(len(geb), 1); self.assertIn("achtergebleven runner", geb[0])
            self.assertEqual(len(rem), 2)   # t=30 en t=60 bij retry_interval 30
            self.assertIn("achtergebleven runner", rem[0])
    def test_ensure_up_nonzero_rc_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            rt.a.dind.ensure_up = lambda: 17
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.tick()
            self.assertTrue(any("rc=17" in m for m in cm.output))

if __name__ == "__main__":
    unittest.main()
