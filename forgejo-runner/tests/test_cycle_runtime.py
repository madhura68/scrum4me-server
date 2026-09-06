# forgejo-runner/tests/test_cycle_runtime.py
import os, tempfile, unittest
from _harness import cr, write_toml, VALID_TOML, RC

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

if __name__ == "__main__":
    unittest.main()
