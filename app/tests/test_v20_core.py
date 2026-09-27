import tempfile, unittest
from pathlib import Path
from pfai.production_core import ProductionCore, ProductionConfig

class TestProductionCore(unittest.TestCase):
    def test_priority_and_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            c=ProductionCore(ProductionConfig(root=d, dry_run=True))
            c.orchestrator.register_resource('gpu0', total_gpus=1, memory_gb=24)
            c.submit_learning_job('general', priority=10, gpu_required=1, memory_gb=4)
            c.submit_learning_job('code_ai_training', gpu_required=1, memory_gb=4)
            started=c.tick()['started']
            self.assertEqual(len(started),1)
            self.assertEqual(started[0]['kind'],'code_ai_training')

    def test_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            c=ProductionCore(ProductionConfig(root=d))
            c.orchestrator.register_resource('gpu0',1,24)
            j=c.submit_learning_job(gpu_required=1)
            c.tick()
            self.assertEqual(c.recover(), [j['job_id']])
            self.assertEqual(c.orchestrator.jobs[j['job_id']].state,'queued')

    def test_persistent_state(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=ProductionConfig(root=d)
            c=ProductionCore(cfg); c.record_cycle({'accepted':True})
            c2=ProductionCore(cfg)
            self.assertEqual(c2.status()['state']['cycles'],1)
            self.assertTrue(c2.status()['state']['last_cycle']['accepted'])

if __name__=='__main__': unittest.main()
