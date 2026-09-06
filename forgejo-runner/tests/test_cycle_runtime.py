# forgejo-runner/tests/test_cycle_runtime.py
import os, tempfile, unittest
from _harness import cr, write_toml, VALID_TOML

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

if __name__ == "__main__":
    unittest.main()
