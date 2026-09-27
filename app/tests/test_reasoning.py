import unittest
from pfai.reasoning import ReasoningEngine
class TestReasoning(unittest.TestCase):
 def test_limit(self): self.assertEqual(len(ReasoningEngine(2).make_plan('x',['a','b','c']).steps),2)
 def test_retry(self):
  n=[0]
  def h(s):
   n[0]+=1
   if n[0]==1: raise RuntimeError('temporary')
   return 'ok'
  p=ReasoningEngine(max_attempts=2).execute(ReasoningEngine(2,2).make_plan('x',['go']),{'go':h})
  self.assertEqual(p.steps[0].status,'success'); self.assertEqual(p.steps[0].attempts,2)
 def test_block(self):
  p=ReasoningEngine().execute(ReasoningEngine().make_plan('x',['missing']),{})
  self.assertEqual(p.steps[0].status,'blocked')
if __name__=='__main__': unittest.main()
