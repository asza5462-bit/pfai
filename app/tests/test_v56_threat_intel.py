import tempfile, unittest
from pathlib import Path
from pfai.threat_intelligence import ThreatIntelligenceEngine
class TestV56(unittest.TestCase):
    def test_unverified_is_not_decision_input(self):
        with tempfile.TemporaryDirectory() as d:
            e=ThreatIntelligenceEngine(str(Path(d)/'ti.jsonl'))
            e.ingest('1.2.3.4','ip','feed-a',.8)
            self.assertFalse(e.decision_input('1.2.3.4')['usable'])
    def test_verified_and_confidence(self):
        with tempfile.TemporaryDirectory() as d:
            e=ThreatIntelligenceEngine(str(Path(d)/'ti.jsonl'))
            e.ingest('CVE-X','cve','vendor',.9,verified=True)
            x=e.decision_input('CVE-X')
            self.assertTrue(x['usable']); self.assertEqual(x['confidence'],.9)
    def test_validation_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            e=ThreatIntelligenceEngine(str(Path(d)/'ti.jsonl'))
            with self.assertRaises(ValueError): e.ingest('x','bad','src')
            e.ingest('evil.example','domain','feed-a',.7,verified=True)
            e.ingest('evil.example','domain','feed-b',.2,verified=False)
            self.assertTrue(e.conflicts('evil.example'))
if __name__=='__main__': unittest.main()
