# forgejo-runner/tests/test_cycle_runtime.py
import hashlib, io, os, tempfile, unittest, urllib.error
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

class TestMain(unittest.TestCase):
    def test_check_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            # vervang de padverwijzingen door bestaande dummies zodat --check niet op IO struikelt
            cfg_path = write_toml(tmp)
            self.assertEqual(cr.main(["--config", cfg_path, "--check"]), 0)
    def test_missing_config(self):
        self.assertNotEqual(cr.main(["--config", "/nope.toml"]), 0)

class TestLogging(unittest.TestCase):
    def test_alarm_events_are_logged(self):
        import logging
        with tempfile.TemporaryDirectory() as tmp:
            rt, ctrl, rec, clock = build_runtime(tmp)
            with self.assertLogs(rt.log, level="WARNING") as cm:
                rt.loop.submit("alarm", {"klasse": "X", "reden": "test"})
                rt._drain_events()
            self.assertTrue(any("alarm" in m for m in cm.output))

if __name__ == "__main__":
    unittest.main()
