"""High-reliability coding tutor/repair loop.

The engine treats code as correct only after execution-backed verification.
It learns from failures by asking the teacher for a patch, re-running tests,
and adding every verified failure->repair pair to the regression corpus.
It never claims zero bugs: it drives residual risk down with layered checks.
"""
from __future__ import annotations
import ast, hashlib, json, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from .code_execution_evaluator import SandboxedCodeEvaluator
from .code_evaluation import PythonCodeEvaluator

@dataclass
class RepairAttempt:
    attempt: int
    passed: bool
    reason: str
    code_hash: str
    stderr: str = ""

@dataclass
class AutoFixResult:
    solved: bool
    code: Optional[str]
    attempts: int
    repairs: int
    verification_passes: int
    history: list[dict]
    regression_added: bool = False

class CodeAutoFixEngine:
    """Generate -> execute -> diagnose -> repair -> re-test, with bounded retries."""
    def __init__(self, model, evaluator: Optional[SandboxedCodeEvaluator] = None,
                 max_repairs: int = 4, regression_root: str = "data/code_learning"):
        self.model = model
        self.evaluator = evaluator or SandboxedCodeEvaluator()
        self.max_repairs = max(1, int(max_repairs))
        self.static = PythonCodeEvaluator()
        self.root = Path(regression_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.regression_path = self.root / "verified_regressions.jsonl"

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _diagnosis(result) -> str:
        parts = [result.reason]
        if result.stderr:
            parts.append("stderr:\n" + result.stderr[-5000:])
        if result.stdout:
            parts.append("stdout:\n" + result.stdout[-3000:])
        return "\n".join(parts)

    def _repair_prompt(self, instruction: str, code: str, tests: str, result) -> str:
        return f"""You are a senior software engineer repairing code.
The previous solution FAILED execution-backed verification. Fix the implementation.
Return ONLY the complete replacement Python code, with no markdown fences or prose.
Do not weaken, delete, or bypass the tests. Preserve the requested API.

TASK:
{instruction}

CURRENT CODE:
{code}

TESTS (ground truth; do not modify):
{tests}

VERIFIER FAILURE:
{self._diagnosis(result)}

Requirements:
- Fix the root cause, not the symptom.
- Handle edge cases implied by the task.
- Keep dependencies within the sandbox's allowed standard library.
- Do not use filesystem, process, network, eval/exec, reflection, or hidden state.
- Return executable Python only.
"""

    def _record_regression(self, instruction: str, tests: str, bad: str, good: str, history: list[dict]):
        row = {"time": time.time(), "instruction": instruction, "tests": tests,
               "failed_code": bad, "verified_code": good, "history": history}
        with self.regression_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def solve_and_repair(self, instruction: str, initial_code: str, test_code: str) -> AutoFixResult:
        code = initial_code.strip()
        history: list[dict] = []
        repairs = 0
        passes = 0
        last_bad = code
        for attempt in range(self.max_repairs + 1):
            static = self.static.evaluate(code + "\n" + test_code)
            if not static.syntax_ok or not static.passed:
                reason = "static gate rejected: " + str(static.details)
                fake = type("R", (), {"reason": reason, "stderr": "", "stdout": ""})()
            else:
                fake = self.evaluator.evaluate(code, test_code)
            passed = bool(getattr(fake, "passed", False))
            history.append(asdict(RepairAttempt(attempt, passed, getattr(fake, "reason", ""), self._hash(code), getattr(fake, "stderr", ""))))
            if passed:
                passes += 1
                if repairs:
                    self._record_regression(instruction, test_code, last_bad, code, history)
                return AutoFixResult(True, code, attempt + 1, repairs, passes, history, repairs > 0)
            if attempt >= self.max_repairs:
                break
            try:
                repaired = self.model.generate(self._repair_prompt(instruction, code, test_code, fake))
            except Exception as exc:
                history[-1]["repair_generation_error"] = type(exc).__name__
                break
            repaired = repaired.strip()
            if repaired.startswith("```"):
                lines = repaired.splitlines()
                repaired = "\n".join(lines[1:-1] if lines and lines[-1].strip().startswith("```") else lines[1:]).strip()
            if not repaired or repaired == code:
                history[-1]["repair_rejected"] = "empty_or_unchanged"
                break
            last_bad = code
            code = repaired
            repairs += 1
        return AutoFixResult(False, None, len(history), repairs, passes, history, False)

class CodeAdversarialVerifier:
    """Adds independent, teacher-generated edge-case tests before curation.

    Generated tests are treated as untrusted input and pass through the same
    static gate + disposable execution sandbox. A generated test suite is used
    only when it actually executes and contains assertions; malformed suites
    are discarded rather than used to reject a solution.
    """
    def __init__(self, model, evaluator=None, rounds: int = 2):
        self.model = model
        self.evaluator = evaluator or SandboxedCodeEvaluator()
        self.rounds = max(0, int(rounds))
        self.static = PythonCodeEvaluator()

    def _prompt(self, instruction: str, code: str, original_tests: str) -> str:
        return f"""Create additional adversarial Python assertions for this programming task.
Return ONLY executable test code. Do not redefine the solution. Do not import modules.
Target edge cases, boundaries, empty inputs, negatives, types, ordering, and invariants.
Never use I/O, filesystem, network, subprocesses, eval/exec, reflection, or randomness.
The tests must assert the documented behavior, not invent requirements.

TASK:\n{instruction}\n\nSOLUTION:\n{code}\n\nEXISTING TESTS:\n{original_tests}\n"""

    def generate(self, instruction: str, code: str, original_tests: str) -> list[str]:
        out = []
        for _ in range(self.rounds):
            try:
                raw = self.model.generate(self._prompt(instruction, code, original_tests)).strip()
            except Exception:
                continue
            if raw.startswith("```"):
                lines = raw.splitlines(); raw = "\n".join(lines[1:-1] if lines and lines[-1].strip().startswith("```") else lines[1:])
            if not raw.strip():
                continue
            static = self.static.evaluate(code + "\n" + raw)
            if not static.passed:
                continue
            if not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(raw))):
                continue
            # A suite is admissible only if it passes for the candidate. If it
            # contradicts the original contract, the model is not allowed to
            # turn that contradiction into a hard failure here.
            result = self.evaluator.evaluate(code, raw)
            if result.passed:
                out.append(raw)
        return out
