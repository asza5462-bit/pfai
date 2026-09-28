"""PHASE 20 Task State Machine — explicit validated transitions only."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from pfai.elite.types import new_id


class TaskState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    VALIDATING = "VALIDATING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


# Valid directed transitions
_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.PLANNING, TaskState.CANCELLED}),
    TaskState.PLANNING: frozenset({TaskState.READY, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.READY: frozenset({TaskState.RUNNING, TaskState.WAITING, TaskState.CANCELLED}),
    TaskState.RUNNING: frozenset(
        {
            TaskState.WAITING,
            TaskState.VALIDATING,
            TaskState.RECOVERING,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.COMPLETED,
        }
    ),
    TaskState.WAITING: frozenset({TaskState.READY, TaskState.RUNNING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.VALIDATING: frozenset(
        {TaskState.COMPLETED, TaskState.RECOVERING, TaskState.FAILED, TaskState.ROLLED_BACK}
    ),
    TaskState.RECOVERING: frozenset(
        {TaskState.READY, TaskState.RUNNING, TaskState.VALIDATING, TaskState.FAILED, TaskState.ROLLED_BACK}
    ),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset({TaskState.ROLLED_BACK}),
    TaskState.CANCELLED: frozenset(),
    TaskState.ROLLED_BACK: frozenset(),
}


TERMINAL_STATES = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.ROLLED_BACK}
)


def can_transition(current: TaskState | str, nxt: TaskState | str) -> bool:
    cur = TaskState(current)
    nxt_s = TaskState(nxt)
    return nxt_s in _TRANSITIONS.get(cur, frozenset())


@dataclass
class AgentTask:
    task_id: str
    objective: str
    state: str = TaskState.CREATED.value
    parent_task_id: str = ""
    plan: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    selected_capabilities: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    selected_model: dict[str, Any] = field(default_factory=dict)
    execution_results: list[dict[str, Any]] = field(default_factory=list)
    validation_results: dict[str, Any] = field(default_factory=dict)
    failure_information: dict[str, Any] = field(default_factory=dict)
    retry_recovery: list[dict[str, Any]] = field(default_factory=list)
    final_status: str = ""
    progress_percent: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(cls, objective: str, *, parent_task_id: str = "", meta: dict[str, Any] | None = None) -> "AgentTask":
        now = time.time()
        return cls(
            task_id=new_id("atask"),
            objective=(objective or "")[:4000],
            parent_task_id=parent_task_id,
            created_at=now,
            updated_at=now,
            meta=dict(meta or {}),
        )


class TaskStateMachine:
    """Enforces valid task state transitions; rejects forged/invalid transitions."""

    VERSION = "20.0.0"

    def transition(self, task: AgentTask, new_state: str | TaskState, *, reason: str = "") -> dict[str, Any]:
        try:
            nxt = TaskState(new_state)
        except ValueError:
            return {"ok": False, "error": "invalid_state", "attempted": str(new_state)}
        cur = TaskState(task.state)
        if not can_transition(cur, nxt):
            return {
                "ok": False,
                "error": "invalid_state_transition",
                "from": cur.value,
                "to": nxt.value,
                "reason": reason,
            }
        task.state = nxt.value
        task.updated_at = time.time()
        if nxt == TaskState.COMPLETED:
            task.final_status = "COMPLETED"
            task.progress_percent = 100
        elif nxt == TaskState.FAILED:
            task.final_status = "FAILED"
        elif nxt == TaskState.CANCELLED:
            task.final_status = "CANCELLED"
        elif nxt == TaskState.ROLLED_BACK:
            task.final_status = "ROLLED_BACK"
        return {"ok": True, "state": task.state, "reason": reason}

    def allowed_next(self, state: str | TaskState) -> list[str]:
        cur = TaskState(state)
        return sorted(s.value for s in _TRANSITIONS.get(cur, frozenset()))
