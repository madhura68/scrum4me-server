# forgejo-runner/tests/test_cycle_fence.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c  # noqa: E402

S, R = c.State, c.ReadinessClass


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


class FenceBasis(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.gates_groen = True
        self.ctrl.state = S.WAITING

    def wijk_af(self, klasse=R.SOURCE_WAIT):
        return self.ctrl.on_event(self.loop.submit("readiness", {"klasse": klasse}))


class TestFenceZetten(FenceBasis):
    def test_eerste_afwijking_zet_een_fence(self):
        self.assertIsNone(self.ctrl.fence)
        self.wijk_af()
        self.assertIsNotNone(self.ctrl.fence)

    def test_eerste_afwijking_haalt_waiting_direct_uit_de_lucht(self):
        self.wijk_af()
        self.assertEqual(self.ctrl.state, S.DRAINING)

    def test_eerste_afwijking_blokkeert_een_nieuwe_child(self):
        self.wijk_af()
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_eerste_afwijking_logt_fence_set_en_alarmeert_niet(self):
        self.wijk_af()
        soorten = [e.kind for e in self.loop.events]
        self.assertIn("fence_set", soorten)
        self.assertNotIn("alarm", soorten)

    def test_fence_seq_is_het_event_seq_van_de_afwijking(self):
        ev = self.loop.submit("readiness", {"klasse": R.SOURCE_WAIT})
        self.ctrl.on_event(ev)
        self.assertEqual(self.ctrl.fence.fence_seq, ev.event_seq)


class TestLatchclassificatie(FenceBasis):
    def test_job_voor_de_fence_is_voor_latch(self):
        job = self.loop.submit("job_accepted", {})
        self.wijk_af()
        self.assertEqual(self.ctrl.latch_verdict(job), "voor")

    def test_job_na_de_fence_is_op_of_na_latch(self):
        self.wijk_af()
        job = self.loop.submit("job_accepted", {})
        self.assertEqual(self.ctrl.latch_verdict(job), "op-of-na")

    def test_gelijk_seq_telt_als_op_of_na(self):
        self.wijk_af()
        nep = c.Event(kind="job_accepted", payload={},
                      event_seq=self.ctrl.fence.fence_seq, mono=0.0, wall=0.0)
        self.assertEqual(self.ctrl.latch_verdict(nep), "op-of-na")

    def test_late_wandklok_verandert_het_oordeel_niet(self):
        # Een event met een oudere wandklok maar hoger event_seq blijft op/na-latch.
        self.wijk_af()
        laat = c.Event(kind="job_accepted", payload={},
                       event_seq=self.ctrl.fence.fence_seq + 5, mono=0.0, wall=-9999.0)
        self.assertEqual(self.ctrl.latch_verdict(laat), "op-of-na")

    def test_onbekend_event_zonder_fence_is_fail_closed(self):
        nep = c.Event(kind="job_accepted", payload={}, event_seq=1, mono=0.0, wall=0.0)
        self.assertEqual(self.ctrl.latch_verdict(nep), "op-of-na")


class TestDeadlinewatchdog(FenceBasis):
    def test_fence_verloopt_na_zestig_seconden(self):
        self.wijk_af()
        self.klok.tik(59.0)
        self.assertFalse(self.ctrl.fence.verlopen(self.klok.mono))
        self.klok.tik(2.0)
        self.assertTrue(self.ctrl.fence.verlopen(self.klok.mono))

    def test_zwaarste_klasse_wint_bij_een_blijvende_klassesprong(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(1.0)
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.assertEqual(self.ctrl.fence.zwaarste_klasse, R.PROTOCOL)

    def test_deadline_commit_gaat_naar_de_zwaarste_klasse(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.CREDENTIAL_ERROR)

    def test_deadline_commit_alarmeert(self):
        self.wijk_af(R.SOURCE_WAIT)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertIn("alarm", [e.kind for e in self.loop.events])

    def test_valid_error_flap_bereikt_alsnog_de_deadline(self):
        self.wijk_af(R.SOURCE_WAIT)
        for _ in range(6):
            self.klok.tik(5.0)
            self.wijk_af(R.READY)
            self.klok.tik(5.0)
            self.wijk_af(R.SOURCE_WAIT)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)
        self.assertIsNone(self.ctrl.fence)


class TestFenceWissen(FenceBasis):
    def test_een_geldige_probe_wist_de_fence_niet(self):
        self.wijk_af()
        self.klok.tik(5.0)
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNotNone(self.ctrl.fence)

    def test_twee_geldige_probes_zonder_nulbewijs_wissen_de_fence_niet(self):
        self.wijk_af()
        self.ctrl.nulbewijs_ok = False
        for _ in range(2):
            self.klok.tik(5.0)
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNotNone(self.ctrl.fence)

    def test_twee_geldige_probes_met_nulbewijs_en_groene_gates_wissen_de_fence(self):
        self.wijk_af()
        self.ctrl.nulbewijs_ok = True
        self.ctrl.gates_groen = True
        for _ in range(2):
            self.klok.tik(5.0)
            self.ctrl.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertIsNone(self.ctrl.fence)
        self.assertTrue(self.ctrl.mag_child_starten)

    def test_koude_start_zonder_fence_vraagt_geen_nulbewijs(self):
        # Het nulbewijs weerlegt dat er nog een job aan een GESTOPTE runner is
        # toegewezen. Bij een koude start is er niets te weerleggen; §7.7
        # spreekt daarom van het "eventueel uitgestelde" nulbewijs. Zou het hier
        # ook vereist zijn, dan kwam een verse host nooit uit SOURCE_WAIT.
        koud = c.Controller(self.loop)
        koud.gates_groen = True
        self.assertFalse(koud.nulbewijs_ok)
        koud.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.klok.tik(5.0)
        koud.on_event(self.loop.submit("readiness", {"klasse": R.READY}))
        self.assertEqual(koud.state, S.WAITING)


class TestJobInUitvoering(FenceBasis):
    """§7.9: bij een al vóór de latch RUNNING job legt de controller de
    geselecteerde volgende toestand vast maar breekt hij die job niet af."""

    def _bevestig_fout_tijdens_running(self, klasse=R.SOURCE_WAIT):
        self.ctrl.state = S.RUNNING
        self.wijk_af(klasse)
        self.klok.tik(5.0)
        self.wijk_af(klasse)

    def test_fence_zetten_breekt_een_lopende_job_niet_af(self):
        self.ctrl.state = S.RUNNING
        self.wijk_af()
        self.assertEqual(self.ctrl.state, S.RUNNING)
        self.assertIsNotNone(self.ctrl.fence)

    def test_bevestigde_foutklasse_laat_de_lopende_job_staan(self):
        self._bevestig_fout_tijdens_running()
        self.assertEqual(self.ctrl.state, S.RUNNING)
        self.assertEqual(self.ctrl.volgende_state, S.SOURCE_WAIT)

    def test_na_de_job_landt_de_controller_in_de_vastgelegde_toestand(self):
        self._bevestig_fout_tijdens_running(R.CREDENTIAL_ERROR)
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.assertEqual(self.ctrl.state, S.SCRUBBING)
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertEqual(self.ctrl.state, S.CREDENTIAL_ERROR)
        self.assertIsNone(self.ctrl.volgende_state)

    def test_scrub_heropent_niet_terwijl_een_onopgeloste_fence_staat(self):
        # Anders omzeilt de scrubroute de fence: de bron wijkt nog af en er
        # staat toch weer een runner klaar om een job aan te nemen.
        self.ctrl.state = S.RUNNING
        self.wijk_af()
        self.ctrl.on_event(self.loop.submit("child_exit", {"code": 0}))
        self.ctrl.on_event(self.loop.submit("scrub_done", {"ok": True}))
        self.assertNotEqual(self.ctrl.state, S.WAITING)
        self.assertFalse(self.ctrl.mag_child_starten)

    def test_deadline_tijdens_een_lopende_job_breekt_hem_ook_niet_af(self):
        self.ctrl.state = S.RUNNING
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.RUNNING)
        self.assertEqual(self.ctrl.volgende_state, S.QUARANTINED)
        self.assertIn("alarm", [e.kind for e in self.loop.events])


if __name__ == "__main__":
    unittest.main()
