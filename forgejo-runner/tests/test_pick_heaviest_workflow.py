# forgejo-runner/tests/test_pick_heaviest_workflow.py
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import pick_heaviest_workflow as p


class TestKiezen(unittest.TestCase):
    def test_kiest_de_langste_geslaagde_run(self):
        runs = {
            "janpeter/app": [
                {"id": 1, "workflow_id": "ci.yml", "status": "success", "duration": 120},
                {"id": 2, "workflow_id": "zwaar.yml", "status": "success", "duration": 900},
            ],
            "janpeter/ander": [
                {"id": 3, "workflow_id": "klein.yml", "status": "success", "duration": 30},
            ],
        }
        keuze = p.pick(runs)
        self.assertEqual(keuze["repo"], "janpeter/app")
        self.assertEqual(keuze["workflow_id"], "zwaar.yml")
        self.assertEqual(keuze["duration_seconds"], 900)

    def test_negeert_mislukte_en_lopende_runs(self):
        runs = {"janpeter/app": [
            {"id": 1, "workflow_id": "kapot.yml", "status": "failure", "duration": 9999},
            {"id": 2, "workflow_id": "loopt.yml", "status": "running", "duration": 8888},
            {"id": 3, "workflow_id": "goed.yml", "status": "success", "duration": 10},
        ]}
        self.assertEqual(p.pick(runs)["workflow_id"], "goed.yml")

    def test_zonder_geslaagde_runs_is_er_geen_keuze(self):
        self.assertIsNone(p.pick({"janpeter/app": [
            {"id": 1, "workflow_id": "x.yml", "status": "failure", "duration": 5}]}))

    def test_duration_als_dict_wordt_ondersteund(self):
        runs = {"janpeter/app": [
            {"id": 1, "workflow_id": "a.yml", "status": "success",
             "duration": {"seconds": 42}}]}
        self.assertEqual(p.pick(runs)["duration_seconds"], 42)


if __name__ == "__main__":
    unittest.main()
