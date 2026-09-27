import tempfile, unittest
from pathlib import Path
from pfai.security_learning import SecurityLearningLoop

class TestSecurityLearning(unittest.TestCase):
    def test_quarantine_verify_admit(self):
        with tempfile.TemporaryDirectory() as d:
            l=SecurityLearningLoop(str(Path(d)/"ledger.jsonl"))
            x=l.quarantine("inc-1","behavior","safe observation","forensic:inc-1")
            self.assertEqual(x.status,"QUARANTINED")
            with self.assertRaises(PermissionError): l.verify(x.item_id,"model")
            l.verify(x.item_id,"reviewer")
            l.admit(x.item_id)
            self.assertEqual(l.state[x.item_id]["status"],"ADMITTED")
            self.assertTrue(l.verify_chain())

    def test_unsafe_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            l=SecurityLearningLoop(str(Path(d)/"ledger.jsonl"))
            with self.assertRaises(PermissionError): l.quarantine("i","credential","secret","src")

    def test_tamper_stops_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"ledger.jsonl"; l=SecurityLearningLoop(str(p))
            x=l.quarantine("i","observation","x","src")
            p.write_text(p.read_text().replace("LEARNING_QUARANTINED","TAMPERED"))
            self.assertFalse(l.verify_chain())
            with self.assertRaises(RuntimeError): l.verify(x.item_id,"reviewer")

if __name__ == "__main__": unittest.main()
