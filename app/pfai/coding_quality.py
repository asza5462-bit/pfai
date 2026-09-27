"""Quality gate for coding answers — never claim untested code works."""
from __future__ import annotations

from .code_evaluation import PythonCodeEvaluator
from .code_execution_evaluator import SandboxedCodeEvaluator


class CodingQualityGate:
    def __init__(self):
        self.static = PythonCodeEvaluator()
        self.sandbox = SandboxedCodeEvaluator()

    def evaluate_answer(self, code: str, test_code: str = "", language: str = "python") -> dict:
        language = (language or "python").lower()
        if language not in {"python", "py"}:
            return {
                "ok": True,
                "language": language,
                "syntax_ok": None,
                "executed": False,
                "passed": None,
                "claim": "not_executed",
                "message": "Non-Python answer was not executed; do not claim it runs.",
            }
        static = self.static.evaluate(code or "")
        if not static.syntax_ok:
            return {
                "ok": False,
                "language": language,
                "syntax_ok": False,
                "executed": False,
                "passed": False,
                "claim": "invalid",
                "message": f"Syntax invalid: {static.details.get('error')}",
            }
        if not (test_code or "").strip():
            return {
                "ok": True,
                "language": language,
                "syntax_ok": True,
                "executed": False,
                "passed": None,
                "claim": "untested",
                "message": "Syntax OK but not executed — do not claim runtime correctness.",
            }
        result = self.sandbox.evaluate(code or "", test_code)
        return {
            "ok": result.passed,
            "language": language,
            "syntax_ok": True,
            "executed": result.executed,
            "passed": result.passed,
            "claim": "verified" if result.passed else "failed_tests",
            "message": result.reason,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
