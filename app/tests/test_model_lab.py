import unittest
from pfai.model_lab import ModelLab
class TestModelLab(unittest.TestCase):
    def test_environment(self):
        r=ModelLab().environment(); self.assertTrue(r.python)
    def test_backend(self):
        self.assertIn(ModelLab().backend(), ('transformers','external-openai-compatible'))
if __name__=='__main__': unittest.main()
