"""Goal System scaffold (PHASE 1). Implementation in PHASE 9."""
from __future__ import annotations

from typing import Any

from pfai.interfaces.goals import Goal, GoalSystemProtocol

__all__ = ["Goal", "GoalSystemProtocol", "GoalSystem"]

PHASE = 9


class GoalSystem:
    """Placeholder — durable goals land in PHASE 9."""

    def create(self, title: str, *, priority: int = 0, meta: dict[str, Any] | None = None) -> Goal:
        raise NotImplementedError("GoalSystem implementation lands in PHASE 9")

    def list_goals(self, *, status: str | None = None) -> list[Goal]:
        raise NotImplementedError("GoalSystem implementation lands in PHASE 9")

    def update(self, goal_id: str, **fields: Any) -> Goal | None:
        raise NotImplementedError("GoalSystem implementation lands in PHASE 9")
