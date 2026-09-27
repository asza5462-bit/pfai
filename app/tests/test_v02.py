import tempfile, unittest
from pathlib import Path
from pfai.audit import AuditLog
from pfai.memory import MemoryStore
from pfai.model import EchoProvider
from pfai.policy import Policy
from pfai.web import WebTool
from pfai.tools import ToolGateway
from pfai.agent import Agent
class T(unittest.TestCase):
    def test_network_default_deny(self):
        with tempfile.TemporaryDirectory() as d:
            a=AuditLog(str(Path(d)/'audit.jsonl')); w=WebTool(Policy({'allow_network':False}),a)
            with self.assertRaises(PermissionError): w.fetch('https://example.com')
    def test_network_enabled_with_empty_allowlist_stays_denied(self):
        self.assertFalse(Policy({"allow_network":True,"allowed_domains":[]}).allow_url("https://example.com"))

    def test_domain_allowlist(self):
        p=Policy({'allow_network':True,'allowed_domains':['example.com']})
        self.assertTrue(p.allow_url('https://example.com/a'))
        self.assertFalse(p.allow_url('https://evil.example/a'))
    def test_agent_memory(self):
        with tempfile.TemporaryDirectory() as d:
            m=MemoryStore(str(Path(d)/'m.sqlite3')); m.add('fact','PFAI test memory','test',1.0)
            a=AuditLog(str(Path(d)/'audit.jsonl')); agent=Agent(EchoProvider(),m,ToolGateway(audit=a),a)
            out=agent.answer('PFAI test memory'); self.assertIn('PFAI test memory',out)
    def test_unknown_tool_denied(self):
        with self.assertRaises(PermissionError): ToolGateway().call('system.shell',cmd='whoami')
if __name__=='__main__': unittest.main()
