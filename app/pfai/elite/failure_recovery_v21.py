"""PHASE 21 failure classification + bounded recovery upgrades."""
from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pfai.elite.self_check_engine import FailureRecovery


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    DEPENDENCY = "dependency_failure"
    TOOL = "tool_failure"
    MODEL = "model_failure"
    INVALID_OUTPUT = "invalid_output"
    VALIDATION = "validation_failure"
    AUTHORIZATION = "authorization_failure"
    RESOURCE = "resource_exhaustion"
    PROGRAMMING = "programming_error"
    UNRECOVERABLE = "unrecoverable_failure"


class FailureClassifier:
    VERSION = "21.0.0"

    def classify(self, error: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        e = (error or "").lower()
        ctx = dict(context or {})
        if any(w in e for w in ("unauthorized", "forbidden", "owner_approval", "denied", "authorization")):
            cls = FailureClass.AUTHORIZATION
            recoverable = False
            action = "safe_stop"
        elif any(w in e for w in ("timeout", "timed out", "deadline")):
            cls = FailureClass.TIMEOUT
            recoverable = True
            action = "retry"
        elif any(w in e for w in ("budget", "exhausted", "queue_full", "resource")):
            cls = FailureClass.RESOURCE
            recoverable = False
            action = "safe_stop"
        elif any(w in e for w in ("model", "provider_unavailable", "forced_model")):
            cls = FailureClass.MODEL
            recoverable = True
            action = "model_escalation"
        elif any(w in e for w in ("tool", "forced_tool", "mcp")):
            cls = FailureClass.TOOL
            recoverable = True
            action = "tool_fallback"
        elif any(w in e for w in ("dependency", "deadlock")):
            cls = FailureClass.DEPENDENCY
            recoverable = True
            action = "replan"
        elif any(w in e for w in ("validation", "schema", "invalid output", "invalid_output")):
            cls = FailureClass.VALIDATION
            recoverable = True
            action = "retry"
        elif any(w in e for w in ("typeerror", "attributeerror", "programming", "traceback")):
            cls = FailureClass.PROGRAMMING
            recoverable = False
            action = "safe_stop"
        elif any(w in e for w in ("transient", "temporarily", "connection reset")):
            cls = FailureClass.TRANSIENT
            recoverable = True
            action = "retry"
        else:
            cls = FailureClass.UNRECOVERABLE if ctx.get("fatal") else FailureClass.TRANSIENT
            recoverable = cls == FailureClass.TRANSIENT
            action = "retry" if recoverable else "safe_stop"
        return {
            "ok": True,
            "class": cls.value,
            "recoverable": recoverable,
            "recommended_action": action,
            "version": self.VERSION,
        }


class BoundedRecoveryPolicy(FailureRecovery):
    """Retry with exponential backoff; never endless; auth failures never retry."""

    VERSION = "21.0.0"

    def __init__(self, max_retries: int = 2, *, base_backoff_seconds: float = 0.05) -> None:
        super().__init__(max_retries=max_retries)
        self.base_backoff = float(base_backoff_seconds)
        self.classifier = FailureClassifier()

    def decide(
        self,
        *,
        error: str,
        attempt: int,
        alternatives: list[str] | None = None,
        allow_model_escalation: bool = True,
    ) -> dict[str, Any]:
        classified = self.classifier.classify(error)
        if classified["class"] == FailureClass.AUTHORIZATION.value:
            return {
                "ok": False,
                "action": "safe_stop",
                "reason": "authorization_failure_not_retried",
                "classification": classified,
                "attempt": attempt,
            }
        if attempt > self.max_retries:
            return {
                "ok": False,
                "action": "stop",
                "reason": "retry_budget_exhausted",
                "classification": classified,
                "attempt": attempt,
                "max_retries": self.max_retries,
            }
        backoff = self.base_backoff * (2 ** max(0, attempt - 1))
        action = classified.get("recommended_action") or "retry"
        if action == "model_escalation" and not allow_model_escalation:
            action = "alternative" if alternatives else "retry"
        if action in ("tool_fallback", "alternative") and alternatives:
            return {
                "ok": True,
                "action": "alternative",
                "alternative": alternatives[0],
                "backoff_seconds": backoff,
                "classification": classified,
                "attempt": attempt,
            }
        if action == "model_escalation":
            return {
                "ok": True,
                "action": "model_escalation",
                "backoff_seconds": backoff,
                "classification": classified,
                "attempt": attempt,
            }
        if action == "replan":
            return {
                "ok": True,
                "action": "replan",
                "backoff_seconds": backoff,
                "classification": classified,
                "attempt": attempt,
            }
        if action == "safe_stop":
            return {
                "ok": False,
                "action": "safe_stop",
                "classification": classified,
                "attempt": attempt,
            }
        # Default retry with backoff (caller sleeps)
        return {
            "ok": True,
            "action": "retry",
            "backoff_seconds": backoff,
            "classification": classified,
            "attempt": attempt,
            "max_retries": self.max_retries,
        }

    def sleep_backoff(self, decision: dict[str, Any]) -> float:
        delay = float(decision.get("backoff_seconds") or 0.0)
        if delay > 0:
            time.sleep(min(delay, 2.0))
        return delay
