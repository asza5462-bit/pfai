import tempfile, unittest
from pfai.sft import SFTLoRATrainer
class TestV13(unittest.TestCase):
 def test_preflight(self):
  r=SFTLoRATrainer(tempfile.mkdtemp()).preflight(); self.assertIn('ready',r)
 def test_manifest_checkpoint_resume(self):
  root=tempfile.mkdtemp(); t=SFTLoRATrainer(root); t.prepare_run('r1','m1',{'sha256':'x'}); out=t.train('r1',dry_run=True); self.assertTrue(t.resume_from('r1'))
if __name__=='__main__': unittest.main()
