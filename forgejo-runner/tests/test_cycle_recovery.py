# forgejo-runner/tests/test_cycle_recovery.py
"""Delta R15 (PBI-34/35): runnerfout-backoff, pre-pull-retry, operatiedeadlines en
herstel na een onzeker operatie-einde. Tijden zijn fake-klokseconden."""
import dataclasses, signal, tempfile, unittest
from _harness import (build_runtime, run_for, FakeClock, State, RC, EventLoop,
                      Controller, cr)


def starts(rec, kind): return rec.starts.count(kind)
def events(obj, kind): return [e for e in getattr(obj, "loop", obj).events if e.kind == kind]


class Backoff(unittest.TestCase):
    """Hart: QUARANTINED heropent pas na min(2**(n-1), 30) minuten."""
    def setUp(self):
        self.clock = FakeClock(); self.loop = EventLoop(self.clock)
        self.ctl = Controller(self.loop); self.ctl.gates_groen = True

    def _cyclus(self, code, scrub_ok=True):
        self.ctl.on_event(self.loop.submit("child_exit", {"code": code}))
        self.ctl.on_event(self.loop.submit("scrub_done", {"ok": scrub_ok}))

    def _wacht(self):
        return self.ctl.quarantaine_tot - self.clock()[0]

    def test_wachttijden_1_2_4_tot_30_minuten_cap(self):
        verwacht = [1, 2, 4, 8, 16, 30, 30]
        for n, minuten in enumerate(verwacht, 1):
            self._cyclus(1)
            self.assertEqual(self.ctl.state, State.QUARANTINED)
            self.assertEqual(self._wacht(), minuten * 60)
            self.assertEqual(self.ctl.opeenvolgende_fouten, n)
            self.clock.advance(minuten * 60)
        self.assertEqual(len(events(self, "alarm")), len(verwacht))

    def test_scrubfout_na_runnercyclus_telt_ook(self):
        self._cyclus(0, scrub_ok=False)
        self.assertEqual(self.ctl.opeenvolgende_fouten, 1)
        self.assertEqual(self._wacht(), 60)

    def test_schone_cyclus_reset_teller(self):
        self._cyclus(1); self.clock.advance(60)
        self._cyclus(1); self.clock.advance(120)
        self.assertEqual(self.ctl.opeenvolgende_fouten, 2)
        self._cyclus(0)
        self.assertEqual(self.ctl.opeenvolgende_fouten, 0)
        self.assertEqual(self.ctl.state, State.WAITING)
        self._cyclus(1)
        self.assertEqual(self._wacht(), 60)

    def test_koude_start_heropent_pas_na_de_wachttijd(self):
        self._cyclus(1)
        def ready(t):
            self.clock.t = t
            self.ctl.on_event(self.loop.submit("readiness", {"klasse": RC.READY}))
        ready(10); ready(20)                       # bevestigd, maar wachttijd (60 s) loopt
        self.assertEqual(self.ctl.state, State.QUARANTINED)
        ready(70); ready(80)
        self.assertEqual(self.ctl.state, State.WAITING)

    def test_losse_scrub_omzeilt_de_backoff_niet(self):
        self._cyclus(1)
        self.ctl.on_event(self.loop.submit("scrub_done", {"ok": True}))  # herstelscrub
        self.assertEqual(self.ctl.state, State.QUARANTINED)
        self.assertEqual(self.ctl.opeenvolgende_fouten, 1)


class RuntimeBackoff(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); self.tmp = td.name

    def test_runtime_start_niet_voor_de_wachttijd(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["runner"] = 1
        t_start = []
        def on_tick(t):
            if starts(rec, "runner") > len(t_start): t_start.append(t)
        run_for(rt, clock, 1000, on_tick=on_tick)
        self.assertGreaterEqual(t_start[1] - t_start[0], 60)
        self.assertGreaterEqual(t_start[2] - t_start[1], 120)


class PullRetry(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); self.tmp = td.name

    def test_pullretry_30s_verdubbelt_max_15min_zonder_blokkade(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["pull"] = 1
        t_pull = []
        def on_tick(t):
            self.assertFalse(rt._blocked)
            if starts(rec, "pull") > len(t_pull): t_pull.append(t)
        run_for(rt, clock, 4500, on_tick=on_tick)
        gaps = [b - a for a, b in zip(t_pull, t_pull[1:])]
        self.assertGreaterEqual(len(gaps), 7)
        for gap, want in zip(gaps, [30, 60, 120, 240, 480, 900, 900]):
            self.assertGreaterEqual(gap, want); self.assertLessEqual(gap, want + 2)
        self.assertEqual(starts(rec, "runner"), 0)

    def test_pullteller_reset_na_succes(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["pull"] = 1
        run_for(rt, clock, 10)
        self.assertEqual(rt._pull_fails, 1)
        rec.auto["pull"] = 0
        run_for(rt, clock, 60)
        self.assertEqual(rt._pull_fails, 0)


class Deadlines(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); self.tmp = td.name
        self.calls = []

    def _rt(self, **kw):
        rt, ctl, rec, clock = build_runtime(self.tmp, **kw)
        rt.a.reconcile.restart_dind = lambda: self.calls.append("restart")
        return rt, ctl, rec, clock

    def test_config_defaults_en_validatie(self):
        rt, *_ = self._rt()
        self.assertEqual((rt.cfg.scrub_deadline, rt.cfg.pull_deadline), (300.0, 900.0))
        bad = dataclasses.replace(rt.cfg, scrub_deadline=0, pull_deadline=-1)
        problems = cr.validate_config(bad)
        self.assertTrue(any("scrub_deadline" in p for p in problems))
        self.assertTrue(any("pull_deadline" in p for p in problems))

    def test_sigterm_na_deadline_sigkill_na_10s(self):
        rt, ctl, rec, clock = self._rt()
        rec.auto["scrub"] = None
        run_for(rt, clock, 305)
        self.assertEqual(rec.pops["scrub"].signals, [signal.SIGTERM])
        self.assertEqual(len(events(rt, "alarm")), 1)
        run_for(rt, clock, 10)
        self.assertEqual(rec.pops["scrub"].signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(rt.a.reconcile.marker_present())   # marker bewaard
        self.assertEqual(ctl.state, State.QUARANTINED)

    def test_herstel_vooraf_aan_volgende_operatie_marker_pas_na_groene_scrub(self):
        rt, ctl, rec, clock = self._rt()
        rec.auto["scrub"] = None
        run_for(rt, clock, 330)                      # scrub gekilld; lokale client weg
        self.assertEqual(self.calls, [])             # pacing: nog geen herstel
        self.assertTrue(rt._needs_recovery)
        rec.auto["scrub"] = 1                        # herstelscrub faalt
        run_for(rt, clock, 40)
        self.assertEqual(self.calls, ["restart"])
        self.assertTrue(rt.a.reconcile.marker_present())
        self.assertEqual(starts(rec, "runner"), 0)
        rec.auto["scrub"] = 0                        # volgende herstelpoging slaagt
        run_for(rt, clock, 120)
        self.assertEqual(self.calls, ["restart", "restart"])
        self.assertFalse(rt.a.reconcile.marker_present())
        self.assertFalse(rt._needs_recovery)
        self.assertGreaterEqual(starts(rec, "runner"), 1)

    def test_pulldeadline_telt_als_pullfout_en_herstel_gaat_voor_retry(self):
        rt, ctl, rec, clock = self._rt()
        rec.auto["pull"] = None
        run_for(rt, clock, 915)
        self.assertEqual(rec.pops["pull"].signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(rt._pull_fails, 1)
        self.assertFalse(rt._blocked)
        self.assertEqual(len(events(rt, "alarm")), 1)
        rec.auto["pull"] = 0
        run_for(rt, clock, 200)
        self.assertEqual(self.calls, ["restart"])   # eerst herstel, dan pas de retry
        self.assertFalse(rt.a.reconcile.marker_present())
        self.assertGreaterEqual(starts(rec, "runner"), 1)

    def test_geen_herstel_tijdens_stop(self):
        rt, ctl, rec, clock = self._rt()
        rec.auto["scrub"] = None
        run_for(rt, clock, 315)
        self.assertTrue(rt._needs_recovery)
        rt.request_stop()
        rec.auto["scrub"] = 0
        run_for(rt, clock, 120)
        self.assertEqual(self.calls, [])
        self.assertEqual(starts(rec, "scrub"), 1)
        self.assertEqual(rt._stop_result(False), 1)  # marker bewaard → non-zero

    def test_startup_marker_blijft_na_mislukte_scrub(self):
        rt, ctl, rec, clock = self._rt(marker=True)
        rec.auto["scrub"] = 1
        run_for(rt, clock, 5)
        self.assertEqual(self.calls, ["restart"])
        self.assertTrue(rt.a.reconcile.marker_present())

    def test_faalt_herstel_dind_herstart_dan_blokkade(self):
        rt, ctl, rec, clock = self._rt(marker=True)
        def boom(): raise RuntimeError("kill faalde")
        rt.a.reconcile.restart_dind = boom
        run_for(rt, clock, 3)
        self.assertTrue(rt._blocked)


if __name__ == "__main__":
    unittest.main()
