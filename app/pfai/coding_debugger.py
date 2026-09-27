"""Debugging trainer — progressive diagnosis before giving the fix."""
from __future__ import annotations

from .coding_skill_profile import SkillProfileStore
from .code_execution_evaluator import SandboxedCodeEvaluator


class DebuggingTrainer:
    def __init__(self, profiles: SkillProfileStore | None = None, sandbox: SandboxedCodeEvaluator | None = None):
        self.profiles = profiles or SkillProfileStore()
        self.sandbox = sandbox or SandboxedCodeEvaluator()
        self._sessions: dict[str, dict] = {}

    def start(self, owner: str, code: str, test_code: str = "", buggy_description: str = "") -> dict:
        result = None
        if test_code.strip():
            result = self.sandbox.evaluate(code or "", test_code)
        sid = f"{owner}:{len(self._sessions)+1}"
        self._sessions[sid] = {
            "owner": owner,
            "code": code,
            "tests": test_code,
            "description": buggy_description,
            "step": 0,
            "result": result,
        }
        return {
            "ok": True,
            "session_id": sid,
            "question": "What do you think is causing the problem?",
            "observed": {
                "passed": None if result is None else result.passed,
                "stderr": None if result is None else result.stderr,
                "reason": None if result is None else result.reason,
            },
            "mode": "debugging",
        }

    def respond(self, session_id: str, learner_hypothesis: str = "") -> dict:
        sess = self._sessions.get(session_id)
        if not sess:
            return {"ok": False, "error": "unknown debug session"}
        step = int(sess.get("step", 0))
        sess["step"] = step + 1
        result = sess.get("result")
        hints = [
            "Reproduce the failure and read the exact assertion/error message.",
            "Check inputs at the failing line: types, empty values, off-by-one.",
            "Compare expected vs actual; isolate the smallest failing example.",
        ]
        if step < len(hints):
            return {
                "ok": True,
                "session_id": session_id,
                "status": "hint",
                "hint_level": step + 1,
                "hint": hints[step],
                "ack_hypothesis": (learner_hypothesis or "")[:300],
                "solution_ready": False,
            }
        # Final explanation
        explanation = "Walk the failing path line-by-line, fix the root cause, then re-run tests."
        if result is not None and not result.passed:
            explanation = f"Failure signal: {result.reason}. stderr: {result.stderr[:300]}"
            self.profiles.record_error(sess["owner"], f"debug:{result.reason[:60]}")
        return {
            "ok": True,
            "session_id": session_id,
            "status": "explain",
            "explanation": explanation,
            "solution_ready": True,
            "note": "Request an explicit fix only if you want Engineering Mode help.",
        }
