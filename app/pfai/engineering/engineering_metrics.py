"""PHASE 18 engineering / security observability metrics — no secrets logged."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args


_SECRET_PAT = re.compile(
    r"(?i)(password|passcode|otp|api[_-]?key|token|secret|authorization|private[_-]?key|credential)\s*[:=]\s*\S+"
)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_PAT.sub(r"\1=[REDACTED]", value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if re.search(r"(?i)password|otp|secret|token|api[_-]?key|authorization|credential", str(k)):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class EngineeringMetrics:
    """Bounded metrics for Phase 18 fabric — deny secret leakage."""

    METRIC_KEYS = (
        "task_duration",
        "tool_latency",
        "model_latency",
        "test_duration",
        "security_analysis_duration",
        "remediation_success",
        "regression",
        "failed_authorization",
        "sandbox_failure",
        "tool_failure",
        "rollback",
    )

    def __init__(self, path: str = "data/longevity/engineering/phase18_metrics.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._counters: dict[str, float] = {k: 0.0 for k in self.METRIC_KEYS}

    def record(self, metric: str, value: float = 1.0, **fields: Any) -> dict[str, Any]:
        key = metric if metric in self.METRIC_KEYS else metric
        row = {
            "ts": time.time(),
            "metric": key,
            "value": float(value),
            **_redact(sanitize_args(fields)),
        }
        # Double-check no secret-like values
        blob = json.dumps(row)
        if re.search(r"(?i)(password|otp)\s*[:=]\s*[^\"\\s\\[]+", blob):
            row = _redact(row)
        with self._lock:
            if key in self._counters:
                if key.endswith("duration") or key.endswith("latency"):
                    self._counters[key] += float(value)
                else:
                    self._counters[key] += float(value)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "recorded": key}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "counters": dict(self._counters), "path": str(self.path)}

    def record_task(self, *, name: str, duration_seconds: float, success: bool, **extra: Any) -> None:
        self.record("task_duration", duration_seconds, name=name, success=success, **extra)

    def record_auth_failure(self, *, reason: str = "", actor: str = "") -> None:
        self.record("failed_authorization", 1.0, reason=reason, actor=actor)

    def record_rollback(self, *, reason: str = "") -> None:
        self.record("rollback", 1.0, reason=reason)
