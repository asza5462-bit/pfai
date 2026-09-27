import json, tempfile, unittest
from pathlib import Path
from pfai.synthetic_lab import SyntheticDataLab, SyntheticTask

class TestSyntheticLab(unittest.TestCase):
    def setUp(self): self.lab=SyntheticDataLab(timeout_s=2)
    def test_fingerprint_stable(self): self.assertEqual(self.lab.fingerprint('x'), self.lab.fingerprint('x'))
    def test_syntax_valid(self): self.assertEqual(self.lab.syntax_check('x=1')[0], True)
    def test_syntax_invalid(self): self.assertFalse(self.lab.syntax_check('def x(:')[0])
    def test_verified_python(self):
        ok, _=self.lab.verify_python('def add(a,b):\n return a+b', 'assert add(2,3)==5')
        self.assertTrue(ok)
    def test_failed_test_rejected(self):
        ok, _=self.lab.verify_python('def add(a,b):\n return a-b', 'assert add(2,3)==5')
        self.assertFalse(ok)
    def test_evaluate_verified(self):
        t=SyntheticTask('add','implement add')
        c=self.lab.evaluate(t,'def add(a,b):\n return a+b')
        self.assertFalse(c.verified)
        c=self.lab.evaluate(t,'def add(a,b):\n return a+b',tests='assert add(1,2)==3')
        self.assertTrue(c.verified)
    def test_generate_filters_bad(self):
        tasks=[SyntheticTask('ok','x'),SyntheticTask('bad','x')]
        def gen(t): return 'def f():\n return 1' if t.task_id=='ok' else 'def f(:'
        got=self.lab.generate_and_verify(tasks,gen,{'ok':'assert f()==1','bad':''})
        self.assertEqual([x.task_id for x in got],['ok'])
    def test_deduplicates(self):
        tasks=[SyntheticTask('a','x'),SyntheticTask('b','x')]
        got=self.lab.generate_and_verify(tasks,lambda t:'def f():\n return 1',{'a':'assert f()==1','b':'assert f()==1'})
        self.assertEqual(len(got),2)  # task_id is part of fingerprint
    def test_export_only_verified(self):
        t=SyntheticTask('a','x'); c=self.lab.evaluate(t,'def f():\n return 1',tests='assert f()==1')
        with tempfile.TemporaryDirectory() as d:
            out=self.lab.export_training_jsonl([c],Path(d)/'data.jsonl')
            self.assertEqual(out['total'],1)
            self.assertTrue(json.loads(Path(d,'data.jsonl').read_text())['verified'])
    def test_limits(self):
        with self.assertRaises(ValueError): SyntheticDataLab(timeout_s=0)
    def test_candidate_metadata(self):
        t=SyntheticTask('a','x',track='ai_engineering',difficulty=4)
        c=self.lab.evaluate(t,'def f():\n return 1',tests='assert f()==1')
        self.assertEqual(c.metadata['difficulty'],4)

if __name__=='__main__': unittest.main()
