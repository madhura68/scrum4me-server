# forgejo-runner/tests/test_cycle_maintenance.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import forgejo_runner_cycle as c  # noqa: E402

S, R = c.State, c.ReadinessClass


class NepKlok:
    def __init__(self):
        self.mono, self.wall = 0.0, 1_000_000.0

    def __call__(self):
        return (self.mono, self.wall)

    def tik(self, seconden):
        self.mono += seconden
        self.wall += seconden


def record(start=1_000_000.0, duur=1800.0):
    return c.MaintenanceRecord(maintenance_id="mnt-1", start_utc=start, eind_utc=start + duur)


class TestRecordvalidatie(unittest.TestCase):
    def test_duur_boven_dertig_minuten_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"maintenance_id": "x", "start_utc": 0, "eind_utc": 1801})

    def test_precies_dertig_minuten_mag(self):
        rec = c.MaintenanceRecord.parse({"maintenance_id": "x", "start_utc": 0, "eind_utc": 1800})
        self.assertEqual(rec.maintenance_id, "x")

    def test_ontbrekend_veld_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"start_utc": 0, "eind_utc": 60})

    def test_lege_id_wordt_geweigerd(self):
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"maintenance_id": "", "start_utc": 0, "eind_utc": 60})

    def test_id_van_alleen_witruimte_wordt_geweigerd(self):
        # Anders is "   " een geldig record en verwijst de monitoring van §10
        # naar een maintenance_id dat niemand kan terugvinden.
        with self.assertRaises(ValueError):
            c.MaintenanceRecord.parse({"maintenance_id": "   ", "start_utc": 0, "eind_utc": 60})

    def test_niet_positieve_duur_wordt_geweigerd(self):
        for eind in (0, -1):
            with self.assertRaises(ValueError):
                c.MaintenanceRecord.parse(
                    {"maintenance_id": "x", "start_utc": 0, "eind_utc": eind})

    def test_geldigheid_is_een_wandklokinterval(self):
        rec = record(start=100.0, duur=60.0)
        self.assertFalse(rec.geldig_op(99.0))
        self.assertTrue(rec.geldig_op(100.0))
        self.assertTrue(rec.geldig_op(159.0))
        self.assertFalse(rec.geldig_op(160.0))


class TestVensterGedrag(unittest.TestCase):
    def setUp(self):
        self.klok = NepKlok()
        self.loop = c.EventLoop(self.klok)
        self.ctrl = c.Controller(self.loop)
        self.ctrl.maintenance = record()

    def wijk_af(self, klasse):
        self.ctrl.on_event(self.loop.submit("readiness", {"klasse": klasse}))

    def test_gemengde_startupklassen_committen_alleen_source_wait(self):
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)

    def test_deadline_binnen_het_venster_alarmeert_niet_als_security(self):
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        alarmen = [e for e in self.loop.events if e.kind == "alarm"]
        self.assertTrue(all(e.payload.get("verwacht") for e in alarmen))

    def test_het_alarm_draagt_het_maintenance_id(self):
        # §10 monitort de actieve maintenance_id; zonder dit veld is een
        # verwacht alarm niet te koppelen aan het venster dat het verklaart.
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        alarm = [e for e in self.loop.events if e.kind == "alarm"][-1]
        self.assertEqual(alarm.payload.get("maintenance_id"), "mnt-1")

    def test_na_tweemaal_geldige_algemene_readiness_vervalt_de_uitzondering(self):
        self.ctrl.algemene_readiness_bevestigd = True
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(1.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_na_de_harde_eindtijd_geldt_de_normale_regel(self):
        self.ctrl.maintenance = record(start=1_000_000.0, duur=60.0)
        self.klok.tik(120.0)          # buiten het venster
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_zonder_record_geldt_de_normale_regel(self):
        self.ctrl.maintenance = None
        self.wijk_af(R.PROTOCOL)
        self.klok.tik(61.0)
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.QUARANTINED)

    def test_het_venster_verlengt_zichzelf_niet(self):
        rec = record(start=1_000_000.0, duur=60.0)
        self.ctrl.maintenance = rec
        self.klok.tik(30.0)
        self.wijk_af(R.SOURCE_WAIT)
        self.assertEqual(rec.eind_utc, 1_000_060.0)

    def test_de_uitzondering_geldt_alleen_voor_de_watchdog_niet_voor_bevestiging(self):
        # §7.7: de startupuitzondering verzacht uitsluitend de deadlinecommit.
        # Een BEVESTIGDE 401/403 binnen het venster wordt gewoon als
        # CREDENTIAL_ERROR gemeld; zou de uitzondering ook hier gelden, dan
        # verdween een echte credentialfout in het onderhoudsvenster.
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.klok.tik(5.0)
        self.wijk_af(R.CREDENTIAL_ERROR)
        self.assertEqual(self.ctrl.state, S.CREDENTIAL_ERROR)

    def test_de_fencedeadline_blijft_monotoon_terwijl_het_venster_wandklok_is(self):
        # De twee klokken mogen niet door elkaar lopen. Hier staat de wandklok
        # stil binnen het venster terwijl de monotone tijd doorloopt: de
        # deadline moet toch worden bereikt.
        self.wijk_af(R.PROTOCOL)
        self.klok.mono += 61.0        # alleen monotoon; wandklok blijft staan
        self.ctrl.tick(self.klok.mono)
        self.assertEqual(self.ctrl.state, S.SOURCE_WAIT)
        self.assertIsNone(self.ctrl.fence)


if __name__ == "__main__":
    unittest.main()
