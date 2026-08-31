# forgejo-runner/tests/test_compute_caps.py
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import compute_caps

GIB = 1024 ** 3
MIB = 1024 ** 2


def sample(rc, rm, rp, dc, dm, dp, memav):
    return {"runner_cpu_pct": rc, "runner_mem_bytes": rm, "runner_pids": rp,
            "dind_cpu_pct": dc, "dind_mem_bytes": dm, "dind_pids": dp,
            "mem_available_bytes": memav}


class TestOndergrens(unittest.TestCase):
    def test_lichte_belasting_valt_terug_op_de_ondergrens(self):
        caps = compute_caps.compute([sample(5, 100 * MIB, 10, 10, 200 * MIB, 20, 8 * GIB)])
        self.assertEqual(caps.runner_cpu, 1.0)
        self.assertEqual(caps.runner_mem_bytes, 1 * GIB)
        self.assertEqual(caps.runner_pids, 256)
        self.assertEqual(caps.dind_cpu, 2.0)
        self.assertEqual(caps.dind_mem_bytes, 4 * GIB)
        self.assertEqual(caps.dind_pids, 2048)


class TestPiek(unittest.TestCase):
    def test_gebruikt_150_procent_van_de_piek_en_rondt_af(self):
        # DinD-piek: 300% CPU = 3 vCPU -> 4,5 vCPU; 6 GiB -> 9 GiB -> afronden op 256 MiB
        caps = compute_caps.compute([
            sample(10, 100 * MIB, 10, 100, 2 * GIB, 100, 8 * GIB),
            sample(20, 200 * MIB, 20, 300, 6 * GIB, 3000, 8 * GIB),
        ])
        self.assertEqual(caps.dind_cpu, 4.5)
        self.assertEqual(caps.dind_mem_bytes, 9 * GIB)
        self.assertEqual(caps.dind_pids, 4608)

    def test_rondt_cpu_naar_boven_af_op_een_half(self):
        caps = compute_caps.compute([sample(140, 100 * MIB, 10, 10, 200 * MIB, 20, 8 * GIB)])
        # 1,4 vCPU * 1,5 = 2,1 -> 2,5
        self.assertEqual(caps.runner_cpu, 2.5)


class TestHeadroom(unittest.TestCase):
    def _caps(self):
        return compute_caps.Caps(runner_cpu=1.0, runner_mem_bytes=1 * GIB, runner_pids=256,
                                 dind_cpu=2.0, dind_mem_bytes=4 * GIB, dind_pids=2048)

    def test_ruime_host_is_groen(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=28, lowest_mem_available=20 * GIB)
        self.assertTrue(ok)
        self.assertEqual(redenen, [])

    def test_te_weinig_geheugen_is_rood(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=28, lowest_mem_available=6 * GIB)
        self.assertFalse(ok)
        self.assertTrue(any("geheugen" in r for r in redenen))

    def test_te_weinig_vcpu_is_rood(self):
        ok, redenen = compute_caps.headroom_ok(self._caps(), vcpu=4, lowest_mem_available=20 * GIB)
        self.assertFalse(ok)
        self.assertTrue(any("vCPU" in r for r in redenen))

    def test_precies_op_de_helft_is_nog_groen(self):
        caps = compute_caps.Caps(runner_cpu=1.0, runner_mem_bytes=1 * GIB, runner_pids=256,
                                 dind_cpu=3.0, dind_mem_bytes=4 * GIB, dind_pids=2048)
        ok, _ = compute_caps.headroom_ok(caps, vcpu=8, lowest_mem_available=10 * GIB)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
