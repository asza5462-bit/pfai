from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional
import json, time, uuid

@dataclass
class ReasoningStep:
    id: str
    action: str
    status: str = 'pending'
    result: Any = None
    attempts: int = 0
    error: Optional[str] = None

@dataclass
class ReasoningTask:
    task_id: str
    goal: str
    steps: List[ReasoningStep] = field(default_factory=list)
    working_memory: List[str] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    status: str = 'pending'
    repair_rounds: int = 0
    created_at: float = field(default_factory=time.time)

class ReasoningCore:
    """Bounded plan/execute/verify/repair loop.

    It stores concise state/results, not hidden chain-of-thought. Verification and
    tool execution are injected by the caller, so this layer cannot grant itself
    permissions or bypass the tool policy.
    """
    def __init__(self, max_steps=8, max_attempts=2, max_repairs=2):
        self.max_steps = max(1, int(max_steps))
        self.max_attempts = max(1, int(max_attempts))
        self.max_repairs = max(0, int(max_repairs))

    def plan(self, goal: str, actions: List[str], task_id: Optional[str] = None) -> ReasoningTask:
        actions = [str(a) for a in actions if str(a).strip()][:self.max_steps]
        return ReasoningTask(task_id or uuid.uuid4().hex, goal, [ReasoningStep(str(i+1), a) for i,a in enumerate(actions)])

    def add_context(self, task: ReasoningTask, items: List[str], max_items: int = 20) -> None:
        for item in items:
            s = str(item).strip()
            if s and s not in task.working_memory:
                task.working_memory.append(s)
        del task.working_memory[:-max_items]

    def run(self, task: ReasoningTask, handlers: Dict[str, Callable[[ReasoningStep, ReasoningTask], Any]],
            verifier: Optional[Callable[[ReasoningTask], Dict[str, Any]]] = None,
            critic: Optional[Callable[[ReasoningTask], Dict[str, Any]]] = None) -> ReasoningTask:
        task.status = 'running'
        for step in task.steps:
            handler = handlers.get(step.action)
            if not handler:
                step.status, step.error = 'blocked', 'no handler'
                task.status = 'blocked'
                return task
            while step.attempts < self.max_attempts and step.status != 'success':
                step.attempts += 1
                try:
                    step.result = handler(step, task)
                    step.status = 'success'
                    self.add_context(task, [f"step:{step.id} success"])
                except Exception as exc:
                    step.error = str(exc)
                    step.status = 'retrying' if step.attempts < self.max_attempts else 'failed'
            if step.status == 'failed':
                task.status = 'failed'
                return task

        for _ in range(self.max_repairs + 1):
            task.verification = verifier(task) if verifier else {'passed': True, 'reason': 'no verifier'}
            if task.verification.get('passed'):
                task.status = 'verified'
                return task
            if task.repair_rounds >= self.max_repairs:
                task.status = 'unverified'
                return task
            task.repair_rounds += 1
            critique = critic(task) if critic else {'repair': True}
            self.add_context(task, [json.dumps(critique, sort_keys=True)])
            repaired = False
            repair_actions = set(critique.get('actions', [])) if isinstance(critique, dict) else set()
            for step in task.steps:
                if step.action in repair_actions or (not repair_actions and step.status in ('failed','unverified')):
                    try:
                        step.result = handlers[step.action](step, task)
                        step.status = 'success'; repaired = True
                    except Exception as exc:
                        step.error = str(exc)
            if not repaired and task.repair_rounds >= self.max_repairs:
                task.status = 'unverified'
                return task
        task.status = 'unverified'
        return task

    @staticmethod
    def summary(task: ReasoningTask) -> Dict[str, Any]:
        return {
            'task_id': task.task_id, 'goal': task.goal, 'status': task.status,
            'repair_rounds': task.repair_rounds,
            'steps': [asdict(s) for s in task.steps],
            'working_memory_items': len(task.working_memory),
            'verification': task.verification,
        }
