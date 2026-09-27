import tempfile, unittest
from pathlib import Path
from pfai.security_knowledge_graph import SecurityKnowledgeGraph
class TestV55(unittest.TestCase):
    def test_unverified_and_verified_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            g=SecurityKnowledgeGraph(str(Path(d)/'g.jsonl'))
            g.add('asset','srv1')
            g.add('incident','inc1',provenance='case-1',verified=True)
            g.link('inc1','affects','srv1',provenance='case-1',verified=True)
            self.assertEqual(len(g.query('inc1',verified_only=True)),2)
    def test_verified_requires_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            g=SecurityKnowledgeGraph(str(Path(d)/'g.jsonl'))
            with self.assertRaises(PermissionError): g.add('x','1',verified=True)
            with self.assertRaises(PermissionError): g.link('1','r','2',verified=True)
if __name__=='__main__': unittest.main()
