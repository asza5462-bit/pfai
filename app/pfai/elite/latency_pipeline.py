"""PHASE 21 latency pipeline — real instrumentation only; never fabricate timings."""
from __future__ import annotations

import time
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.types import new_id


PIPELINE_EVENTS = (
    "request_received",
    "routing_started",
    "routing_completed",
    "planning_started",
    "planning_completed",
    "tool_started",
    "tool_completed",
    "model_started",
    "model_completed",
    "execution_started",
    "execution_completed",
    "response_started",
    "response_completed",
)


class LatencyPipeline:
    """Record actual event timestamps for a single request/task."""

    VERSION = "21.0.0"

    def __init__(self, *, request_id: str = "") -> None:
        self.request_id = request_id or new_id("lat")
        self.started_at = time.time()
        self.events: list[dict[str, Any]] = []
        self.mark("request_received")

    def mark(self, event: str, **detail: Any) -> dict[str, Any]:
        row = {
            "event": event,
            "ts": time.time(),
            "elapsed": time.time() - self.started_at,
            **sanitize_args(detail),
        }
        self.events.append(row)
        return row

    def span(self, start_event: str, end_event: str) -> float | None:
        starts = [e["ts"] for e in self.events if e["event"] == start_event]
        ends = [e["ts"] for e in self.events if e["event"] == end_event]
        if not starts or not ends:
            return None
        return max(0.0, ends[-1] - starts[0])

    def summary(self) -> dict[str, Any]:
        total = time.time() - self.started_at
        measured = {
            "total_latency": total,
            "routing_latency": self.span("routing_started", "routing_completed"),
            "planning_latency": self.span("planning_started", "planning_completed"),
            "tool_latency": self.span("tool_started", "tool_completed"),
            "model_latency": self.span("model_started", "model_completed"),
            "execution_latency": self.span("execution_started", "execution_completed"),
            "response_latency": self.span("response_started", "response_completed"),
        }
        # Derive queue latency if present
        queue = self.span("request_received", "execution_started")
        measured["queue_latency"] = queue
        return {
            "request_id": self.request_id,
            "version": self.VERSION,
            "fabricated": False,
            "measured": {k: v for k, v in measured.items() if v is not None},
            "not_available": [k for k, v in measured.items() if v is None],
            "events": list(self.events),
            "source": "measured",
        }
