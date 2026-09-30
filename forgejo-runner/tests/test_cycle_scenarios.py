# forgejo-runner/tests/test_cycle_scenarios.py
"""Runtime-scenario's uit de audit van 2026-09-30 (T-161, PBI-33/ST-047).

Tijden zijn fake-klokseconden (stap 1 s, retry_interval 30, CONFIRM 30). C, D en E
waren @expectedFailure; delta R15 (PBI-34/35) implementeert ze, de decorators zijn vervallen."""
import signal, tempfile, unittest
from unittest import mock
from _harness import build_runtime, run_for, OK_PROBE, BAD_PROBE, State

def starts(rec, kind): return rec.starts.count(kind)
def events(rt, kind): return [e for e in rt.loop.events if e.kind == kind]

class Scenarios(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); self.tmp = td.name

    def _first_start(self, rt, rec, clock, limit):
        """Verstreken tijd tot de eerste runnerstart (None als die uitblijft)."""
        hit = []
        def on_tick(t):
            if starts(rec, "runner") and not hit: hit.append(t)
        run_for(rt, clock, limit, on_tick=on_tick)
        if starts(rec, "runner") and not hit: hit.append(limit)
        return hit[0] if hit else None

    # A — AUDIT-007: één mislukte probe (controle eerst, dan het bekende watchdoggedrag)
    def test_A_controle_alle_probes_ok_start_binnen_31s(self):
        rt, ctl, rec, clock = build_runtime(self.tmp, probe_seq=lambda: OK_PROBE)
        t = self._first_start(rt, rec, clock, 120)
        self.assertIsNotNone(t); self.assertLessEqual(t, 31)

    # AUDIT-007 is in delta R15 UITGESTELD (review ronde 1): zonder assignment-nulbewijs
    # wist de fence alleen via de 60 s-watchdog. Dit legt het bekende gedrag vast: één
    # alarm en een start rond t=120 i.p.v. t=30. Wordt aangescherpt zodra het nulbewijs bestaat.
    def test_A_eenmalige_probefout_watchdog_alarm_en_start_rond_120s(self):
        seq = iter([BAD_PROBE])
        rt, ctl, rec, clock = build_runtime(self.tmp, probe_seq=lambda: next(seq, OK_PROBE))
        t = self._first_start(rt, rec, clock, 180)
        self.assertEqual(len(events(rt, "alarm")), 1)
        self.assertIsNotNone(t); self.assertLessEqual(t, 125)

    # B — AUDIT-003, door de eigenaar ACCEPTED op 2026-09-30: een rode trustgate stopt
    # geen al lopende (wachtende) runner; hij mag nog één job oppakken. Dit is bewust
    # geaccepteerd risico (het ene-job-venster), geen defect: dit legt het gedrag vast.
    def test_B_trust_rood_laat_lopende_runner_staan_geaccepteerd_risico(self):
        red = {"v": False}
        rt, ctl, rec, clock = build_runtime(
            self.tmp, trust_fn=lambda: ((not red["v"]), "test"))
        run_for(rt, clock, 60)
        self.assertEqual(starts(rec, "runner"), 1); self.assertIsNotNone(rt.child)
        red["v"] = True
        run_for(rt, clock, 600)
        self.assertFalse(ctl.gates_groen)
        self.assertIsNotNone(rt.child)                       # child draait nog
        self.assertEqual(rec.pops["runner"].signals, [])     # en kreeg geen signaal
        self.assertEqual(ctl.state, State.WAITING)
        self.assertEqual(starts(rec, "runner"), 1)

    # C — AUDIT-006; gedrag volgens delta R15
    def test_C_runner_faalt_steeds_backoff_en_alarm_per_falen(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["runner"] = 1                               # runner sterft direct, rc=1
        run_for(rt, clock, 300)
        n = starts(rec, "runner")
        self.assertLessEqual(n, 3)                           # backoff 1,2,4… minuten
        self.assertGreaterEqual(len(events(rt, "alarm")), n) # een alarm per falen

    # D — AUDIT-005; gedrag volgens delta R15
    def test_D_pull_faalt_eenmaal_backoff_retry_en_runner_start(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["pull"] = 1
        def on_tick(t):
            if starts(rec, "pull"): rec.auto["pull"] = 0     # alleen de eerste pull faalt
            self.assertFalse(rt._blocked, f"geblokkeerd op t={t}")
        run_for(rt, clock, 3600, on_tick=on_tick)
        self.assertGreaterEqual(starts(rec, "runner"), 1)

    # E — AUDIT-004; gedrag volgens delta R15
    def test_E_scrub_blijft_hangen_wordt_beeindigd_alarm_en_quarantaine(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        rec.auto["scrub"] = None                             # poll levert nooit een rc
        run_for(rt, clock, 330)
        self.assertTrue(rec.pops["scrub"].signals, "scrub is nooit gesignaleerd")
        self.assertTrue(events(rt, "alarm"))
        self.assertEqual(starts(rec, "runner"), 0)
        self.assertEqual(ctl.state, State.QUARANTINED)

    # F — Runtime.run(): SIGTERM → schone stop, exitcode 0
    def test_F_run_sigterm_schone_stop_geeft_0(self):
        rt, ctl, rec, clock = build_runtime(self.tmp)
        for s in (signal.SIGTERM, signal.SIGINT):            # run() installeert handlers
            self.addCleanup(signal.signal, s, signal.getsignal(s))
        n = {"sleeps": 0}
        def fake_sleep(dt):                                  # klok vooruit i.p.v. echt slapen
            n["sleeps"] += 1; clock.advance(dt)
            self.assertLess(n["sleeps"], 50, "run() keerde niet terug")
            if n["sleeps"] == 3: signal.raise_signal(signal.SIGTERM)
        with mock.patch("time.sleep", fake_sleep):
            rc = rt.run()
        self.assertEqual(rc, 0)
        self.assertIsNone(rt.child); self.assertIsNone(rt.op)
        self.assertEqual(starts(rec, "runner"), 0)

if __name__ == "__main__":
    unittest.main()
