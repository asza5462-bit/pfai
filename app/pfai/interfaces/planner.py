"""Task Planner contracts — wrap/extend ReasoningCore without replacing it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class PlanStep:
    id: str
    action: str
    status: str = "pending"
    result: Any = None
    error: str | None = None


@dataclass
class TaskPlan:
    plan_id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "pending"
    working_memory: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TaskPlannerProtocol(Protocol):
    """Bounded plan → execute → verify surface over ReasoningCore."""

    def plan(self, goal: str, actions: list[str] | None = None) -> TaskPlan:
        ...

    def run(self, plan: TaskPlan, *, handlers: dict[str, Any] | None = None) -> TaskPlan:
        ...
