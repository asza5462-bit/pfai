import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pfai.forensic_recovery import ForensicRecoveryCenter, RecoveryState

class TestForensicRecovery(unittest.TestCase):
    def test_lifecycle_and_external_approval(self):
        with tempfile.TemporaryDirectory() as d:
            c=ForensicRecoveryCenter(str(Path(d)/"ledger.jsonl"))
            c.open_incident("i1","task-1","anomaly")
            e=c.collect("i1","runtime","tool-x",{"action":"denied"})
            self.assertEqual(len(e.data_hash),64)
            c.contain("i1","suspicious behavior")
            p=c.plan_recovery("i1",["rotate capability","restart sandbox"])
            with self.assertRaises(PermissionError): c.approve_recovery("i1","model",p.plan_hash)
            c.approve_recovery("i1","external-reviewer",p.plan_hash)
            c.recover("i1",p.plan_hash); c.close("i1")
            self.assertEqual(c.state["i1"]["state"],RecoveryState.CLOSED.value)
            self.assertTrue(c.verify_chain())

    def test_tamper_and_plan_binding(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"ledger.jsonl"; c=ForensicRecoveryCenter(str(path))
            c.open_incident("i2","task-2","test"); c.contain("i2","x")
            p=c.plan_recovery("i2",["safe restart"])
            with self.assertRaises(PermissionError): c.approve_recovery("i2","reviewer","bad")
            text=path.read_text(); path.write_text(text.replace("INCIDENT_OPENED","TAMPERED",1))
            self.assertFalse(c.verify_chain())
            with self.assertRaises(RuntimeError): c.collect("i2","x","y",{})

if __name__ == "__main__": unittest.main()
