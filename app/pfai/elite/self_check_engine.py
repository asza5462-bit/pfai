"""PHASE 12 SelfCheckEngine + bounded failure recovery."""
from __future__ import annotations

from typing import Any

from pfai.elite.types import ExecutionStatus


class SelfCheckEngine:
    def verify(
        self,
        *,
        result: Any = None,
        requirements: list[str] | None = None,
        schema_required_keys: list[str] | None = None,
        execution_ok: bool | None = None,
        contradictions: list[Any] | None = None,
        test_failed: int = 0,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        ok = True

        if execution_ok is False:
            checks.append({"name": "execution", "ok": False, "detail": "execution_failed"})
            ok = False
        else:
            checks.append({"name": "execution", "ok": True})

        if schema_required_keys:
            missing = []
            if not isinstance(result, dict):
                missing = list(schema_required_keys)
            else:
                missing = [k for k in schema_required_keys if k not in result]
            checks.append({"name": "schema", "ok": not missing, "missing": missing})
            ok = ok and not missing

        if requirements:
            text = str(result)
            missing_req = [r for r in requirements if str(r).lower() not in text.lower()]
            checks.append({"name": "requirements", "ok": not missing_req, "missing": missing_req})
            ok = ok and not missing_req

        if contradictions:
            checks.append({"name": "contradictions", "ok": False, "count": len(contradictions)})
            ok = False
        else:
            checks.append({"name": "contradictions", "ok": True})

        if test_failed:
            checks.append({"name": "tests", "ok": False, "failed": test_failed})
            ok = False
        else:
            checks.append({"name": "tests", "ok": True})

        if execution_ok is False:
            status = ExecutionStatus.FAILED.value
        elif execution_ok is None and result is None:
            status = ExecutionStatus.UNVERIFIED.value
        elif ok:
            status = ExecutionStatus.SUCCESS.value
        elif any(c.get("ok") for c in checks):
            status = ExecutionStatus.PARTIAL_SUCCESS.value
        else:
            status = ExecutionStatus.FAILED.value

        return {
            "ok": status in (ExecutionStatus.SUCCESS.value, ExecutionStatus.PARTIAL_SUCCESS.value),
            "status": status,
            "checks": checks,
        }


class FailureRecovery:
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = int(max_retries)

    def next_action(
        self,
        *,
        error: str,
        attempt: int,
        alternatives: list[str] | None = None,
    ) -> dict[str, Any]:
        attempt = int(attempt)
        if attempt > self.max_retries:
            return {
                "ok": False,
                "action": "stop",
                "reason": "retry_budget_exhausted",
                "attempt": attempt,
                "max_retries": self.max_retries,
                "error": error,
            }
        alts = list(alternatives or [])
        if alts:
            return {
                "ok": True,
                "action": "alternative",
                "alternative": alts[0],
                "attempt": attempt,
                "max_retries": self.max_retries,
            }
        return {
            "ok": True,
            "action": "retry",
            "attempt": attempt,
            "max_retries": self.max_retries,
            "error": error,
        }
