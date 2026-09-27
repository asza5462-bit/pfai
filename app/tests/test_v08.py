import os, tempfile, unittest
from pfai.learning_loop import LearningLoop
from pfai.learning_data import sanitize_dataset
class TestV08(unittest.TestCase):
    def test_reject_regression(self):
        with tempfile.TemporaryDirectory() as d:
            l=LearningLoop(os.path.join(d,'r.json'),min_improvement=.1)
            ds=[{'prompt':'a','answer':'b'}]
            self.assertEqual(l.propose('v1',ds,lambda x:.8)['status'],'accepted')
            l.promote('v1')
            self.assertEqual(l.propose('v2',ds,lambda x:.81)['status'],'rejected')
    def test_approval_gate(self):
        with tempfile.TemporaryDirectory() as d:
            l=LearningLoop(os.path.join(d,'r.json'),require_human_approval=True)
            r=l.propose('v1',[{'prompt':'a','answer':'b'}],lambda x:1)
            self.assertEqual(r['status'],'pending_approval'); self.assertTrue(l.approve('v1')); self.assertTrue(l.promote('v1'))
    def test_sanitize(self):
        self.assertEqual(len(sanitize_dataset([{'prompt':' q ','answer':' a '},{'prompt':'','answer':'x'},'bad'])),1)
if __name__=='__main__': unittest.main()
