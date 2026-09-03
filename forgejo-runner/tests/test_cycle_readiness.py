# forgejo-runner/tests/test_cycle_readiness.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c  # noqa: E402

R = c.ReadinessClass


class TestVierwegclassificatie(unittest.TestCase):
    def test_transportfout_is_source_wait(self):
        for fout in ("timeout", "connection refused", "dns failure"):
            self.assertEqual(c.classify_probe({"kind": "general", "error": fout}), R.SOURCE_WAIT)

    def test_5xx_is_source_wait(self):
        for status in (500, 502, 503, 504):
            self.assertEqual(
                c.classify_probe({"kind": "general", "status": status, "schema_ok": False}),
                R.SOURCE_WAIT)

    def test_401_en_403_op_de_authprobe_is_credential_error(self):
        for status in (401, 403):
            self.assertEqual(
                c.classify_probe({"kind": "auth", "status": status, "schema_ok": False}),
                R.CREDENTIAL_ERROR)

    def test_401_op_de_algemene_probe_is_protocol(self):
        # De algemene probe hoort geen auth te vereisen; 401 daar is een protocolfout.
        self.assertEqual(
            c.classify_probe({"kind": "general", "status": 401, "schema_ok": False}),
            R.PROTOCOL)

    def test_overige_status_is_protocol(self):
        for status in (301, 404, 418):
            self.assertEqual(
                c.classify_probe({"kind": "auth", "status": status, "schema_ok": False}),
                R.PROTOCOL)

    def test_2xx_met_verkeerd_schema_is_protocol(self):
        self.assertEqual(
            c.classify_probe({"kind": "auth", "status": 200, "schema_ok": False}),
            R.PROTOCOL)

    def test_2xx_met_geldig_schema_is_ready(self):
        self.assertEqual(
            c.classify_probe({"kind": "auth", "status": 200, "schema_ok": True}),
            R.READY)

    def test_ontbrekende_status_is_protocol(self):
        # Fail-closed: een antwoord zonder status is niet interpreteerbaar en mag
        # nooit als READY of als louter availability-probleem worden gelezen.
        for probe in ({"kind": "auth"}, {"kind": "general", "schema_ok": True}):
            self.assertEqual(c.classify_probe(probe), R.PROTOCOL)

    def test_transportfout_wint_van_een_meegestuurde_status(self):
        # Een transportfout betekent dat er geen bruikbaar antwoord was; een
        # statusveld dat er toch bij staat mag de klasse niet verzwaren.
        self.assertEqual(
            c.classify_probe({"kind": "auth", "error": "timeout", "status": 401,
                              "schema_ok": False}),
            R.SOURCE_WAIT)

    def test_er_is_geen_default_gat(self):
        # Iedere combinatie valt in precies een van de vier klassen.
        for kind in ("general", "auth"):
            for status in (200, 201, 301, 400, 401, 403, 404, 418, 500, 503):
                for schema in (True, False):
                    uitkomst = c.classify_probe(
                        {"kind": kind, "status": status, "schema_ok": schema})
                    self.assertIn(uitkomst, (R.READY, R.SOURCE_WAIT, R.CREDENTIAL_ERROR, R.PROTOCOL))

    def test_er_is_ook_geen_gat_zonder_status_of_met_fout(self):
        for kind in ("general", "auth"):
            for probe in ({"kind": kind},
                          {"kind": kind, "error": "timeout"},
                          {"kind": kind, "schema_ok": True},
                          {"kind": kind, "status": None, "schema_ok": False}):
                uitkomst = c.classify_probe(probe)
                self.assertIn(uitkomst, (R.READY, R.SOURCE_WAIT, R.CREDENTIAL_ERROR, R.PROTOCOL))


class TestSeverity(unittest.TestCase):
    def test_protocol_is_zwaarder_dan_credential_dan_availability(self):
        self.assertGreater(c.SEVERITY[R.PROTOCOL], c.SEVERITY[R.CREDENTIAL_ERROR])
        self.assertGreater(c.SEVERITY[R.CREDENTIAL_ERROR], c.SEVERITY[R.SOURCE_WAIT])

    def test_severity_dekt_precies_de_drie_foutklassen(self):
        # De deadlinewatchdog van 7.7 kiest de zwaarste SINDS LATCH waargenomen
        # FOUTklasse. READY hoort daar niet bij; dat het ontbreekt is contract,
        # geen omissie.
        self.assertEqual(set(c.SEVERITY), {R.SOURCE_WAIT, R.CREDENTIAL_ERROR, R.PROTOCOL})
        self.assertNotIn(R.READY, c.SEVERITY)


class TestBevestiging(unittest.TestCase):
    def test_een_waarneming_bevestigt_niets(self):
        conf = c.Confirmation()
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=0.0))

    def test_twee_gelijke_waarnemingen_bevestigen(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertEqual(conf.observe(R.SOURCE_WAIT, now=5.0), R.SOURCE_WAIT)

    def test_te_snel_herhalen_bevestigt_nog_niet(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=1.0))

    def test_klassesprong_herstart_de_bevestiging(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertIsNone(conf.observe(R.CREDENTIAL_ERROR, now=5.0))
        self.assertEqual(conf.observe(R.CREDENTIAL_ERROR, now=10.0), R.CREDENTIAL_ERROR)

    def test_geldige_probe_bevestigt_ready_pas_bij_de_tweede(self):
        conf = c.Confirmation()
        self.assertIsNone(conf.observe(R.READY, now=0.0))
        self.assertEqual(conf.observe(R.READY, now=5.0), R.READY)

    def test_na_een_bevestiging_zijn_er_weer_twee_waarnemingen_nodig(self):
        # Anders zou elke volgende probe de toestand blijven herbevestigen en
        # verliest de drempel zijn betekenis.
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        self.assertEqual(conf.observe(R.SOURCE_WAIT, now=5.0), R.SOURCE_WAIT)
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=10.0))
        self.assertEqual(conf.observe(R.SOURCE_WAIT, now=15.0), R.SOURCE_WAIT)

    def test_reset_wist_de_lopende_bevestiging(self):
        conf = c.Confirmation()
        conf.observe(R.SOURCE_WAIT, now=0.0)
        conf.reset()
        self.assertIsNone(conf.observe(R.SOURCE_WAIT, now=5.0))


if __name__ == "__main__":
    unittest.main()
