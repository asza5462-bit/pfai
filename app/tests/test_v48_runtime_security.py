import tempfile, unittest
from pfai.runtime_security import RuntimeSecurity, RuntimeEvent

class TestRuntimeSecurity(unittest.TestCase):
    def test_budget_and_kill_switch(self):
        with tempfile.TemporaryDirectory() as d:
            s=RuntimeSecurity(d+"/runtime.jsonl")
            e=RuntimeEvent("t1","c1","code","run",cost=3)
            self.assertEqual(s.inspect(e,allowed_tools={"code"},max_cost=5,max_calls=2)[0],True)
            self.assertEqual(s.inspect(e,allowed_tools={"code"},max_cost=5,max_calls=2)[0],False)
            self.assertTrue(s.is_blocked("t1","c1"))
            self.assertFalse(s.inspect(e,allowed_tools={"code"})[0])
            self.assertTrue(s.verify_ledger())
    def test_scope_violation(self):
        with tempfile.TemporaryDirectory() as d:
            s=RuntimeSecurity(d+"/runtime.jsonl")
            e=RuntimeEvent("t2","c2","shell","run")
            self.assertEqual(s.inspect(e,allowed_tools={"code"})[1],"tool_out_of_scope")
            self.assertTrue(s.is_blocked("t2","c2"))
            self.assertTrue(s.verify_ledger())
    def test_call_limit(self):
        with tempfile.TemporaryDirectory() as d:
            s=RuntimeSecurity(d+"/runtime.jsonl")
            e=RuntimeEvent("t3","c3","code","run")
            self.assertTrue(s.inspect(e,max_calls=1)[0])
            self.assertFalse(s.inspect(e,max_calls=1)[0])

if __name__ == '__main__': unittest.main()
