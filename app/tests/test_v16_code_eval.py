import unittest
from pfai.code_evaluation import PythonCodeEvaluator
class TestCodeEval(unittest.TestCase):
    def test_good_code(self):
        r=PythonCodeEvaluator().evaluate('''def add(a,b):\n    return a+b\n\nassert add(2,3)==5\n''')
        self.assertTrue(r.passed); self.assertTrue(r.syntax_ok); self.assertGreaterEqual(r.score,.65)
    def test_syntax_and_block(self):
        r=PythonCodeEvaluator().evaluate('import os\ndef x(:\n')
        self.assertFalse(r.syntax_ok)
        r=PythonCodeEvaluator().evaluate('import os\ndef x():\n    return 1\n')
        self.assertFalse(r.passed); self.assertIn('os',r.unsafe_imports)
if __name__=='__main__': unittest.main()
