import os, tempfile, unittest
from pfai.training import ModelLifecycle
from pfai.model_registry import ModelRegistry

class V09Tests(unittest.TestCase):
    def test_training_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            life=ModelLifecycle(os.path.join(d,'runs.json'),os.path.join(d,'artifacts'))
            r=life.train_candidate('r1','base','cand-1',[{'x':1}],lambda artifact,data: 0.8)
            self.assertEqual(r['status'],'evaluated'); self.assertTrue(os.path.exists(r['artifact']))
    def test_registry_promote_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            reg=ModelRegistry(os.path.join(d,'models.json'))
            reg.register('v1','a1',.8); reg.register('v2','a2',.9)
            self.assertTrue(reg.promote('v1')); self.assertEqual(reg.active()['version'],'v1')
            self.assertTrue(reg.promote('v2')); self.assertEqual(reg.active()['version'],'v2')
            self.assertTrue(reg.rollback('v1')); self.assertEqual(reg.active()['version'],'v1')

if __name__=='__main__': unittest.main()
