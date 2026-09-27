import tempfile, unittest
from pfai.active_defense import ActiveDefenseController

class TestActiveDefense(unittest.TestCase):
    def test_authorized_simulation(self):
        with tempfile.TemporaryDirectory() as d:
            c=ActiveDefenseController(d+"/a.jsonl")
            op=c.request(task_id="t",action="exploit_simulation",target="lab-web",scope="lab-web",approver="reviewer")
            r=c.execute_simulation(op["operation_id"],simulated_result="blocked")
            self.assertTrue(r["executed"]); self.assertFalse(r["real_intrusion"]); self.assertTrue(c.verify_ledger())
    def test_external_approval_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            c=ActiveDefenseController(d+"/a.jsonl")
            with self.assertRaises(PermissionError): c.request(task_id="t",action="port_check",target="lab",scope="lab",approver="model")
            with self.assertRaises(PermissionError): c.request(task_id="t",action="port_check",target="prod",scope="lab",approver="reviewer")
    def test_destructive_actions_denied(self):
        with tempfile.TemporaryDirectory() as d:
            c=ActiveDefenseController(d+"/a.jsonl")
            with self.assertRaises(PermissionError): c.request(task_id="t",action="ransomware",target="lab",scope="lab",approver="reviewer")

if __name__=='__main__': unittest.main()
