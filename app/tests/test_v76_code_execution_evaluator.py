import unittest
from pfai.code_execution_evaluator import SandboxedCodeEvaluator


class TestSandboxedCodeEvaluator(unittest.TestCase):
    def setUp(self):
        self.ev = SandboxedCodeEvaluator(timeout_seconds=3, cpu_seconds=3)

    def test_correct_solution_passes(self):
        r = self.ev.evaluate(
            "def add(a, b):\n    return a + b\n",
            "assert add(2, 3) == 5\nassert add(-1, 1) == 0\n",
        )
        self.assertTrue(r.passed)
        self.assertTrue(r.executed)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.score, 1.0)

    def test_incorrect_solution_fails_with_real_traceback(self):
        r = self.ev.evaluate(
            "def add(a, b):\n    return a - b\n",
            "assert add(2, 3) == 5\n",
        )
        self.assertFalse(r.passed)
        self.assertTrue(r.executed)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("AssertionError", r.stderr)

    def test_blocked_import_never_executes(self):
        r = self.ev.evaluate("import os\nos.system('echo hi')\n", "")
        self.assertFalse(r.passed)
        self.assertFalse(r.executed)  # never even reached the subprocess
        self.assertIn("blocked import", r.reason)

    def test_socket_use_never_executes(self):
        r = self.ev.evaluate("", "import socket\nsocket.socket()\n")
        self.assertFalse(r.executed)

    def test_infinite_loop_is_killed_by_timeout(self):
        ev = SandboxedCodeEvaluator(timeout_seconds=1, cpu_seconds=1)
        r = ev.evaluate("while True:\n    pass\n", "")
        self.assertFalse(r.passed)
        self.assertTrue(r.timed_out)

    def test_syntax_error_never_executes(self):
        r = self.ev.evaluate("def f(:\n", "")
        self.assertFalse(r.static_passed)
        self.assertFalse(r.executed)

    def test_never_raises_on_malformed_input(self):
        # Fails closed even on pathological input -- must never propagate an exception.
        try:
            r = self.ev.evaluate("\x00\x00garbage", "")
        except Exception as exc:  # pragma: no cover
            self.fail(f"evaluate() must fail closed, not raise: {exc}")
        self.assertFalse(r.passed)

    def test_dynamic_import_and_filesystem_escape_primitives_are_rejected(self):
        for code in ["__import__('os').system('echo bad')", "open('/etc/passwd').read()", "().__class__.__subclasses__()"]:
            r=self.ev.evaluate(code,'')
            self.assertFalse(r.static_passed)
            self.assertFalse(r.executed)

    def test_stdout_is_captured(self):
        r = self.ev.evaluate("print('hello from sandbox')\n", "")
        self.assertTrue(r.passed)
        self.assertIn("hello from sandbox", r.stdout)


if __name__ == '__main__':
    unittest.main()
