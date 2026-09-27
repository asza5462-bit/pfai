import tempfile, unittest
from pathlib import Path
from pfai.deception import DeceptionEngine

class TestDeception(unittest.TestCase):
    def test_owned_scope_and_chain(self):
        with tempfile.TemporaryDirectory() as d:
            e=DeceptionEngine(Path(d)/"d.jsonl")
            e.create_honeypot("hp1","operator",["ssh","http"],"owned")
            e.record_interaction("hp1","sensor-1","203.0.113.9")
            self.assertTrue(e.verify_chain())
    def test_rejects_unauthorized_scope(self):
        with tempfile.TemporaryDirectory() as d:
            e=DeceptionEngine(Path(d)/"d.jsonl")
            with self.assertRaises(PermissionError): e.create_honeypot("hp","x",["http"],"internet")
    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"d.jsonl"; e=DeceptionEngine(p); e.create_honeypot("hp","x",["http"])
            p.write_text(p.read_text().replace('"scope": "lab"','"scope": "owned"'),encoding="utf-8")
            self.assertFalse(e.verify_chain())
if __name__ == '__main__': unittest.main()
