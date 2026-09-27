import unittest
from pfai.global_job_scheduler import GlobalJobScheduler, Job

class Fabric:
    def __init__(self):
        self.servers = {
            "gpu-a": {"authorized": True, "status": "HEALTHY", "load": .2,
                      "resources": {"cpu_free": 8, "ram_free_gb": 64, "gpu_free": 1, "vram_free_gb": 24}},
            "cpu-b": {"authorized": True, "status": "HEALTHY", "load": .1,
                      "resources": {"cpu_free": 16, "ram_free_gb": 32, "gpu_free": 0, "vram_free_gb": 0}},
            "bad": {"authorized": False, "status": "HEALTHY", "load": 0,
                    "resources": {"cpu_free": 99, "ram_free_gb": 99, "gpu_free": 9, "vram_free_gb": 99}},
        }

class TestV63(unittest.TestCase):
    def test_resource_aware_assignment(self):
        s=GlobalJobScheduler(Fabric())
        s.submit(Job("train", priority=100, required_gpu=1, required_vram_gb=16))
        self.assertEqual(s.schedule()[0].worker_id, "gpu-a")

    def test_dependencies(self):
        s=GlobalJobScheduler(Fabric())
        s.submit(Job("a")); s.submit(Job("b", dependencies=["a"]))
        self.assertEqual(s.schedule()[0].job_id, "a")
        self.assertFalse(s.ready("b"))
        s.complete("a")
        self.assertEqual(s.schedule("b")[0].job_id, "b")

    def test_cycle_rejected(self):
        s=GlobalJobScheduler(Fabric())
        s.submit(Job("a"))
        s.jobs["a"].dependencies=["b"]
        with self.assertRaises(ValueError): s.submit(Job("b", dependencies=["a"]))

    def test_failover(self):
        s=GlobalJobScheduler(Fabric())
        s.submit(Job("x", required_gpu=1, required_vram_gb=8))
        s.schedule("x")
        self.assertEqual(s.worker_failed("gpu-a"), [])
        self.assertEqual(s.jobs["x"].status, "PENDING")

    def test_unauthorized_worker_ignored(self):
        s=GlobalJobScheduler(Fabric())
        s.submit(Job("x", required_gpu=1, required_vram_gb=8))
        self.assertEqual(s.schedule()[0].worker_id, "gpu-a")

if __name__ == '__main__': unittest.main()
