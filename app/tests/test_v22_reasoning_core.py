import unittest
from pfai.reasoning_core import ReasoningCore

class TestReasoningCore(unittest.TestCase):
    def test_plan_is_bounded(self):
        t=ReasoningCore(max_steps=2).plan('goal',['a','b','c'])
        self.assertEqual(len(t.steps),2)
    def test_verify(self):
        c=ReasoningCore()
        t=c.plan('goal',['work'])
        out=c.run(t, {'work': lambda s,t: 'ok'}, verifier=lambda t:{'passed':True})
        self.assertEqual(out.status,'verified')
    def test_repair(self):
        c=ReasoningCore(max_repairs=1)
        n={'v':0}
        def work(s,t):
            n['v']+=1
            return 'fixed' if n['v']>1 else 'first'
        def verify(t): return {'passed': n['v']>1}
        out=c.run(c.plan('goal',['work']), {'work':work}, verifier=verify, critic=lambda t:{'issue':'retry','actions':['work']})
        self.assertEqual(out.status,'verified'); self.assertEqual(out.repair_rounds,1)
    def test_missing_handler_blocked(self):
        out=ReasoningCore().run(ReasoningCore().plan('goal',['missing']), {})
        self.assertEqual(out.status,'blocked')
    def test_summary_has_no_hidden_trace(self):
        c=ReasoningCore(); t=c.run(c.plan('goal',['work']), {'work':lambda s,t:'ok'})
        s=c.summary(t)
        self.assertIn('working_memory_items',s)
        self.assertNotIn('chain_of_thought',s)

if __name__=='__main__': unittest.main()
