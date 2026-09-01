# forgejo-runner/tests/test_cycle_lifecycle.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c  # noqa: E402

S = c.State


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


def snap(t, assigned=0, running=0):
    return {"mono": t, "assigned": assigned, "running": running}


class TestNulbewijs(unittest.TestCase):
    def test_twee_lege_snapshots_tien_seconden_uiteen_bewijzen_nul(self):
        self.assertTrue(c.assignment_nulbewijs([snap(0.0), snap(10.0)]))

    def test_te_kort_uiteen_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0), snap(5.0)]))

    def test_een_snapshot_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0)]))

    def test_een_toegewezen_job_breekt_het_bewijs(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0), snap(10.0, assigned=1)]))

    def test_een_lopende_job_breekt_het_bewijs(self):
        self.assertFalse(c.assignment_nulbewijs([snap(0.0, running=1), snap(10.0)]))

    def test_lege_lijst_bewijst_niets(self):
        self.assertFalse(c.assignment_nulbewijs([]))

    def test_het_bewijs_kijkt_naar_de_laatste_twee_opeenvolgende_snapshots(self):
        # §7.9 vraagt TWEE OPEENVOLGENDE schone snapshots, niet een schone
        # historie. Een eerdere bezette meting mag het bewijs dus niet blokkeren
        # zodra er daarna twee schone op rij staan.
        historie = [snap(0.0, assigned=1), snap(10.0, running=1),
                    snap(20.0), snap(30.0)]
        self.assertTrue(c.assignment_nulbewijs(historie))


class TestCyclusvolgorde(unittest.TestCase):
    def test_scrub_komt_voor_een_nieuwe_runnerstart(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("scrub"), stappen.index("start_runner_volgende_cyclus"))

    def test_bewijs_schoon_komt_voor_een_nieuwe_runnerstart(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("bewijs_schoon"),
                        stappen.index("start_runner_volgende_cyclus"))

    def test_trustgate_is_de_eerste_stap(self):
        self.assertEqual(c.Controller.cycle_stappen()[0], "trustgate")

    def test_bewijs_geen_runnerproces_komt_voor_de_scrub(self):
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("bewijs_geen_runnerproces"), stappen.index("scrub"))

    def test_de_imagecontrole_komt_voor_de_runnerstart(self):
        # §7.9 stap 2 vóór stap 3: pre-pull uitsluitend per digest gebeurt
        # voordat er een runner bestaat die een job kan aannemen.
        stappen = c.Controller.cycle_stappen()
        self.assertLess(stappen.index("controleer_toegestane_images"),
                        stappen.index("start_runner_one_job_wait"))

    def test_geen_stap_komt_twee_keer_voor(self):
        stappen = c.Controller.cycle_stappen()
        self.assertEqual(len(stappen), len(set(stappen)))


class TestDrain(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.gates_groen = True

    def test_drain_vanuit_waiting_gaat_naar_draining(self):
        self.ctrl.state = S.WAITING
        self.ctrl.drain(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.DRAINING)

    def test_drain_blokkeert_een_volgende_child(self):
        self.ctrl.state = S.WAITING
        self.ctrl.drain(self.klok.mono)
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_drain_tijdens_running_breekt_de_job_niet_af(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.drain(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.RUNNING)
        self.assertTrue(self.ctrl.drain_gevraagd)

    def test_na_drain_leidt_een_groene_scrub_niet_terug_naar_waiting(self):
        self.ctrl.state = S.RUNNING
        self.ctrl.drain(self.klok.mono)
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.DRAINING)

    def test_drain_vanuit_een_fouttoestand_heropent_niets(self):
        # Een drain is een geplande stop; hij mag een quarantaine nooit
        # opheffen, en de vraag blijft staan tot hij expliciet is ingetrokken.
        self.ctrl.state = S.QUARANTINED
        self.ctrl.drain(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)
        self.assertTrue(self.ctrl.drain_gevraagd)
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_een_drain_overleeft_bronherstel(self):
        # Vanuit SOURCE_WAIT verandert drain de toestand niet. Zou readiness
        # daarna gewoon naar WAITING mogen, dan was de geplande stop stilzwijgend
        # vergeten en stond er weer een runner klaar.
        self.ctrl.state = S.SOURCE_WAIT
        self.ctrl.drain(self.klok.mono)
        self.assertFalse(self.ctrl.mag_child_starten)
        for _ in range(2):
            self.ctrl.on_event(self.loop.submit(
                "readiness", {"klasse": c.ReadinessClass.READY}))
            self.klok.tik(5.0)
        self.assertNotEqual(self.ctrl.state, S.WAITING)


class TestOpNaLatchJob(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.gates_groen = True
        self.ctrl.state = S.WAITING

    def test_job_na_de_fence_leidt_tot_cancel_en_scrub(self):
        self.ctrl.on_event(self.loop.submit(
            "readiness", {"klasse": c.ReadinessClass.SOURCE_WAIT}))
        job = self.loop.submit("job_accepted", {})
        self.ctrl.on_event(job)
        self.assertEqual(self.ctrl.latch_verdict(job), "op-of-na")
        self.assertIn("cancel_en_redispatch", [e.kind for e in self.loop.events])

    def test_een_voor_latch_job_wordt_niet_gecanceld(self):
        # Het latchverdict bestaat juist om deze twee uit elkaar te houden:
        # een job die aantoonbaar vóór de fence werd geaccepteerd mag
        # gecontroleerd eindigen (§7.7). Zou hij ook worden gecanceld, dan
        # sneuvelt bij iedere bronhapering een legitiem draaiende job.
        job = self.loop.submit("job_accepted", {})
        self.ctrl.on_event(self.loop.submit(
            "readiness", {"klasse": c.ReadinessClass.SOURCE_WAIT}))
        self.assertEqual(self.ctrl.latch_verdict(job), "voor")
        self.ctrl.on_event(job)
        self.assertNotIn("cancel_en_redispatch", [e.kind for e in self.loop.events])


if __name__ == "__main__":
    unittest.main()
