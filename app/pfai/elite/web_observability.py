"""PHASE 23 web/tool observability — counters without secrets."""
from __future__ import annotations

import threading
import time
from typing import Any

from pfai.authorized_execution import sanitize_args


class WebObservability:
    VERSION = "23.0.0"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: dict[str, int] = {
            "web_requests": 0,
            "web_success": 0,
            "web_failure": 0,
            "provider_timeouts": 0,
            "rate_limits": 0,
            "budget_exhaustion": 0,
            "injection_blocks": 0,
            "mcp_calls": 0,
            "mcp_failures": 0,
            "research_tasks": 0,
            "citation_validations": 0,
            "retries": 0,
        }
        self._latencies: list[float] = []

    def record(self, kind: str, *, ok: bool = True, latency: float = 0.0, **extra: Any) -> None:
        with self._lock:
            self._counters["web_requests"] = self._counters.get("web_requests", 0) + 1
            if kind == "research":
                self._counters["research_tasks"] += 1
            if kind == "mcp":
                self._counters["mcp_calls"] += 1
                if not ok:
                    self._counters["mcp_failures"] += 1
            if ok:
                self._counters["web_success"] += 1
            else:
                self._counters["web_failure"] += 1
            err = str(extra.get("error") or "")
            if "timeout" in err:
                self._counters["provider_timeouts"] += 1
            if "rate_limit" in err:
                self._counters["rate_limits"] += 1
            if "budget" in err:
                self._counters["budget_exhaustion"] += 1
            if int(extra.get("injection_blocks") or 0) > 0:
                self._counters["injection_blocks"] += int(extra.get("injection_blocks") or 0)
            if extra.get("retry"):
                self._counters["retries"] += 1
            if latency:
                self._latencies.append(float(latency))
                self._latencies = self._latencies[-200:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            mean = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.0
            return sanitize_args(
                {
                    "ok": True,
                    "version": self.VERSION,
                    "counters": dict(self._counters),
                    "mean_latency_seconds": mean,
                    "sample_count": len(self._latencies),
                    "ts": time.time(),
                    "secrets_recorded": False,
                }
            )


WEB_OBS = WebObservability()
