"""PHASE 20 execution budgets — hard stops; no infinite agent loops."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ExecutionBudgets:
    max_task_steps: int = 24
    max_retries: int = 2
    max_tool_calls: int = 40
    max_model_calls: int = 20
    max_execution_time_seconds: float = 120.0
    max_nested_task_depth: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BudgetTracker:
    def __init__(self, budgets: ExecutionBudgets | None = None) -> None:
        self.budgets = budgets or ExecutionBudgets()
        self.started_at = time.time()
        self.steps = 0
        self.retries = 0
        self.tool_calls = 0
        self.model_calls = 0
        self.nested_depth = 0

    def check(self) -> dict[str, Any]:
        elapsed = time.time() - self.started_at
        b = self.budgets
        if self.steps > b.max_task_steps:
            return {"ok": False, "exceeded": "max_task_steps", "value": self.steps, "limit": b.max_task_steps}
        if self.retries > b.max_retries:
            return {"ok": False, "exceeded": "max_retries", "value": self.retries, "limit": b.max_retries}
        if self.tool_calls > b.max_tool_calls:
            return {"ok": False, "exceeded": "max_tool_calls", "value": self.tool_calls, "limit": b.max_tool_calls}
        if self.model_calls > b.max_model_calls:
            return {"ok": False, "exceeded": "max_model_calls", "value": self.model_calls, "limit": b.max_model_calls}
        if elapsed > b.max_execution_time_seconds:
            return {
                "ok": False,
                "exceeded": "max_execution_time_seconds",
                "value": elapsed,
                "limit": b.max_execution_time_seconds,
            }
        if self.nested_depth > b.max_nested_task_depth:
            return {
                "ok": False,
                "exceeded": "max_nested_task_depth",
                "value": self.nested_depth,
                "limit": b.max_nested_task_depth,
            }
        return {"ok": True, "elapsed": elapsed}

    def snapshot(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "retries": self.retries,
            "tool_calls": self.tool_calls,
            "model_calls": self.model_calls,
            "nested_depth": self.nested_depth,
            "elapsed": time.time() - self.started_at,
            "budgets": self.budgets.to_dict(),
            "check": self.check(),
        }
