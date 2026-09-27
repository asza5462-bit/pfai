"""Goals system contracts — scaffold only until PHASE 9."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Goal:
    goal_id: str
    title: str
    status: str = "open"  # open | active | blocked | done | cancelled
    priority: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GoalSystemProtocol(Protocol):
    def create(self, title: str, *, priority: int = 0, meta: dict[str, Any] | None = None) -> Goal:
        ...

    def list_goals(self, *, status: str | None = None) -> list[Goal]:
        ...

    def update(self, goal_id: str, **fields: Any) -> Goal | None:
        ...
