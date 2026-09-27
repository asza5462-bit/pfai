import tempfile, unittest
from pfai.security_sentinel import SecuritySentinel, SentinelEvent

class TestSecuritySentinel(unittest.TestCase):
    def test_permission_and_tool_drift_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            s=SecuritySentinel(d+"/s.jsonl", tool_threshold=2)
            e=lambda tool: SentinelEvent("t","c",tool,"code")
            self.assertTrue(s.inspect(e("code"),allowed_tools={"code"})[0])
            self.assertFalse(s.inspect(e("shell"),allowed_tools={"code"})[0])
            self.assertTrue(s.is_isolated("t","c")); self.assertTrue(s.verify_ledger())

    def test_repeated_failures(self):
        with tempfile.TemporaryDirectory() as d:
            s=SecuritySentinel(d+"/s.jsonl",failure_threshold=2)
            e=SentinelEvent("t","c","code","code",success=False)
            self.assertTrue(s.inspect(e)[0])
            self.assertFalse(s.inspect(e)[0])
            self.assertTrue(s.is_isolated("t","c"))

    def test_release_requires_external_approval(self):
        with tempfile.TemporaryDirectory() as d:
            s=SecuritySentinel(d+"/s.jsonl")
            s.isolate("t","c","manual")
            with self.assertRaises(PermissionError): s.release("t","c","model")
            self.assertTrue(s.release("t","c","external-reviewer"))
            self.assertFalse(s.is_isolated("t","c")); self.assertTrue(s.verify_ledger())

if __name__ == '__main__': unittest.main()
