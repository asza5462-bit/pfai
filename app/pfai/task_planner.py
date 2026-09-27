"""Task Planner scaffold (PHASE 1). Implementation in PHASE 4.

Wraps/extends ReasoningCore; does not grant permissions or bypass ToolRouter.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.planner import PlanStep, TaskPlan, TaskPlannerProtocol

__all__ = ["PlanStep", "TaskPlan", "TaskPlannerProtocol", "TaskPlanner"]

PHASE = 4


class TaskPlanner:
    """Placeholder — ReasoningCore adapter lands in PHASE 4."""

    def plan(self, goal: str, actions: list[str] | None = None) -> TaskPlan:
        raise NotImplementedError("TaskPlanner adapter lands in PHASE 4")

    def run(self, plan: TaskPlan, *, handlers: dict[str, Any] | None = None) -> TaskPlan:
        raise NotImplementedError("TaskPlanner adapter lands in PHASE 4")
