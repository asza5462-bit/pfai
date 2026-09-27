import os, tempfile, unittest
from pfai.model_registry import ModelRegistry
from pfai.deployment import DeploymentController
from pfai.checkpoints import CheckpointStore
from pfai.metrics import Metrics

class V10Tests(unittest.TestCase):
    def test_canary_promote_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            reg=ModelRegistry(os.path.join(d,'models.json')); reg.register('v1','a1',.8); reg.register('v2','a2',.9); reg.promote('v1')
            dep=DeploymentController(os.path.join(d,'dep.json'),reg); dep.canary('v2',.1); self.assertTrue(dep.promote('v2')); self.assertEqual(reg.active()['version'],'v2'); self.assertTrue(dep.rollback('v2'))
    def test_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,'artifact.bin'); 
            with open(p,'wb') as f: f.write(b'abc'); c=CheckpointStore(os.path.join(d,'cp')); m=c.save('v1',p); self.assertEqual(len(m['sha256']),64); self.assertTrue(os.path.exists(m['artifact']))
    def test_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            m=Metrics(os.path.join(d,'m.json')); m.inc('x'); m.observe('latency',4); s=m.snapshot(); self.assertEqual(s['counters']['x'],1); self.assertEqual(s['latency_ms']['latency'],[4.0])
if __name__=='__main__': unittest.main()
