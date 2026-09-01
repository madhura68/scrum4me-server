# forgejo-runner/tests/test_cycle_eventloop.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c  # noqa: E402

S = c.State


class NepKlok:
    """Monotone tijd en wandklok apart, allebei handmatig bestuurd.

    De wandklok loopt bewust achteruit in een test, om te bewijzen dat de
    controller hem nooit voor een beslissing gebruikt.
    """

    def __init__(self):
        self.mono = 0.0
        self.wall = 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden, wall_delta=None):
        self.mono += seconden
        self.wall += seconden if wall_delta is None else wall_delta


class TestEventSeq(unittest.TestCase):
    def test_event_seq_loopt_strikt_op(self):
        loop = c.EventLoop(NepKlok())
        seqs = [loop.submit("probe", {}).event_seq for _ in range(5)]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 5)

    def test_event_seq_loopt_op_ook_als_de_wandklok_terugspringt(self):
        klok = NepKlok()
        loop = c.EventLoop(klok)
        eerste = loop.submit("probe", {})
        klok.tik(1.0, wall_delta=-500.0)
        tweede = loop.submit("probe", {})
        self.assertGreater(tweede.event_seq, eerste.event_seq)
        self.assertLess(tweede.wall, eerste.wall)
        self.assertGreater(tweede.mono, eerste.mono)

    def test_event_draagt_beide_tijden(self):
        loop = c.EventLoop(NepKlok())
        ev = loop.submit("probe", {"x": 1})
        self.assertIsNotNone(ev.mono)
        self.assertIsNotNone(ev.wall)
        self.assertEqual(ev.payload, {"x": 1})

    def test_de_loop_bewaart_ieder_event_in_volgorde_van_ontvangst(self):
        # Het auditspoor moet compleet zijn: de loop is de enige plek waar een
        # event ontstaat, dus wat hier niet in staat is nooit waargenomen.
        loop = c.EventLoop(NepKlok())
        for kind in ("probe", "job_accepted", "child_exit"):
            loop.submit(kind, {})
        self.assertEqual([e.kind for e in loop.events],
                         ["probe", "job_accepted", "child_exit"])
        self.assertEqual([e.event_seq for e in loop.events], [1, 2, 3])


class TestToestandsmachine(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)

    def test_begint_in_source_wait(self):
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)

    def test_waiting_pas_na_twee_ready_probes_en_groene_gates(self):
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)
        self.klok.tik(5.0)
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.assertEqual(self.ctrl.state, S.WAITING)

    def test_rode_gates_houden_de_controller_uit_waiting(self):
        self.ctrl.gates_groen = False
        for _ in range(2):
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
            self.klok.tik(5.0)
        self.assertNotEqual(self.ctrl.state, S.WAITING)

    def test_de_bevestiging_loopt_op_monotone_tijd_niet_op_de_wandklok(self):
        # De wandklok springt een half uur terug tussen de twee probes. Zou de
        # bevestiging daarop leunen, dan zou het venster negatief worden en
        # nooit sluiten.
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.klok.tik(5.0, wall_delta=-1800.0)
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": c.ReadinessClass.READY}))
        self.assertEqual(self.ctrl.state, S.WAITING)

    def test_een_bevestigde_foutklasse_haalt_de_controller_uit_waiting(self):
        # Fail-closed: zodra de bron aantoonbaar niet meer deugt mag er geen
        # runner blijven staan die nog een job kan aannemen.
        for klasse, verwacht in ((c.ReadinessClass.SOURCE_WAIT, S.SOURCE_WAIT),
                                 (c.ReadinessClass.CREDENTIAL_ERROR, S.CREDENTIAL_ERROR),
                                 (c.ReadinessClass.PROTOCOL, S.QUARANTINED)):
            klok = NepKlok()
            loop = c.EventLoop(klok)
            ctrl = c.Controller(loop, state=S.WAITING)
            ctrl.on_event(loop.submit("readiness", {"klasse": klasse}))
            klok.tik(5.0)
            ctrl.on_event(loop.submit("readiness", {"klasse": klasse}))
            self.assertEqual(ctrl.state, verwacht)

    def test_job_accepted_brengt_waiting_naar_running(self):
        self.ctrl.state = S.WAITING
        self.ctrl.on_event(self.loop.submit("job_accepted", {}))
        self.assertEqual(self.ctrl.state, S.RUNNING)

    def test_job_accepted_buiten_waiting_verandert_niets(self):
        # Een jobacceptatie zonder dat de controller een runner had staan is
        # geen geldige overgang; hem toch naar RUNNING brengen zou een job
        # legitimeren die niet uit deze cyclus komt.
        for begin in (S.SOURCE_WAIT, S.QUARANTINED, S.SCRUBBING):
            self.ctrl.state = begin
            self.ctrl.on_event(self.loop.submit("job_accepted", {}))
            self.assertEqual(self.ctrl.state, begin)

    def test_childexit_na_running_gaat_naar_scrubbing(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)

    def test_childexit_vanuit_waiting_scrubt_ook(self):
        # Een runnerproces dat sterft terwijl het nog wacht heeft de DinD al
        # aangeraakt; containment gaat voor, dus ook dan scrubben.
        self.ctrl.state = S.WAITING
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)

    def test_non_zero_childexit_quarantaint_na_scrub(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 1}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_groene_scrub_na_nette_exit_gaat_terug_naar_waiting(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.WAITING)

    def test_groene_scrub_met_rode_gates_gaat_niet_naar_waiting(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.gates_groen = False
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)

    def test_mislukte_scrub_quarantaint_altijd(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.gates_groen = True
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": False}))
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_onbekend_event_verandert_de_toestand_niet(self):
        self.ctrl.state = S.WAITING
        self.ctrl.on_event(self.loop.submit("iets_onbekends", {}))
        self.assertEqual(self.ctrl.state, S.WAITING)


if __name__ == "__main__":
    unittest.main()
