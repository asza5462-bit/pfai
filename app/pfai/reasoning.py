from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

@dataclass
class Step:
    id: str
    action: str
    status: str = 'pending'
    result: Any = None
    attempts: int = 0
    error: str | None = None

@dataclass
class Plan:
    goal: str
    steps: List[Step] = field(default_factory=list)

class ReasoningEngine:
    def __init__(self, max_steps=8, max_attempts=2):
        self.max_steps = max_steps
        self.max_attempts = max_attempts
    def make_plan(self, goal: str, actions: List[str]) -> Plan:
        return Plan(goal, [Step(str(i+1), a) for i,a in enumerate(actions[:self.max_steps])])
    def execute(self, plan: Plan, handlers: Dict[str, Callable[[Step], Any]], verify=None) -> Plan:
        for step in plan.steps:
            handler = handlers.get(step.action)
            if not handler:
                step.status, step.error = 'blocked', 'no handler'
                continue
            while step.attempts < self.max_attempts and step.status != 'success':
                step.attempts += 1
                try:
                    step.result = handler(step); step.status = 'success'
                except Exception as exc:
                    step.error = str(exc)
                    step.status = 'retrying' if step.attempts < self.max_attempts else 'failed'
        if verify and not verify(plan):
            for step in plan.steps:
                if step.status == 'success': step.status = 'unverified'
        return plan
