import tempfile, unittest
from pfai.adaptive_defense import AdaptiveDefenseOrchestrator
class TestAdaptiveDefense(unittest.TestCase):
    def test_levels(self):
        with tempfile.TemporaryDirectory() as d:
            x=AdaptiveDefenseOrchestrator(d+"/a.jsonl")
            self.assertEqual(x.assess("a", anomaly_score=5)["level"],"observe")
            self.assertEqual(x.assess("b", anomaly_score=25)["level"],"harden")
            self.assertEqual(x.assess("c", anomaly_score=55)["level"],"simulate")
            self.assertEqual(x.assess("d", integrity_failure=True)["level"],"isolate")
            self.assertTrue(x.verify_ledger())
    def test_approval(self):
        with tempfile.TemporaryDirectory() as d:
            x=AdaptiveDefenseOrchestrator(d+"/a.jsonl"); dec=x.assess("c",anomaly_score=55)
            with self.assertRaises(PermissionError): x.approve_simulation(dec,"model")
            self.assertTrue(x.approve_simulation(dec,"reviewer")); self.assertTrue(x.verify_ledger())
if __name__=='__main__': unittest.main()
