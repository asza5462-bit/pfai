"""Model-driven planning and critique for ReasoningCore's bounded plan/execute/verify
loop — this is what makes the "brain" of PFAI actually reason with real intelligence
instead of only running a plan the caller hand-wrote.

Every existing safety invariant of ReasoningCore is preserved, not loosened:
- `LLMPlanner` can only ever choose actions from the caller-supplied whitelist. It
  cannot invent a new action name, so it cannot grant itself a new tool or
  capability — the model proposes an *order*, never a *permission*.
- `LLMCritic` only returns a pass/fail verdict and which already-registered steps to
  retry; it never executes anything and cannot reference an action PFAI didn't
  already run.
- Any malformed, missing, or unparseable model output fails closed: the planner
  falls back to the caller's own action order, and the critic reports "not passed"
  rather than guessing that something succeeded.
"""
from __future__ import annotations
import json
from typing import Any, Dict, List


def _extract_json(text: str, opener: str, closer: str):
    start, end = text.find(opener), text.rfind(closer)
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


_PLAN_PROMPT = (
    "Choose which of these allowed actions to run, and in what order, to achieve the "
    "goal below. Return ONLY a JSON array of action names — no prose, no markdown "
    "fences — using only names from the allowed list, each at most once.\n"
    "Allowed actions: {actions}\n"
    "Goal: {goal}\n"
)

_CRITIQUE_PROMPT = (
    'Review this task result and decide whether the goal was actually achieved. '
    'Return ONLY JSON, no prose: {{"passed": true|false, "reason": "<=1 sentence", '
    '"actions": ["<step action names worth retrying>"]}}\n'
    "Goal: {goal}\n"
    "Step results: {steps}\n"
)


class LLMPlanner:
    """Proposes an execution order, constrained to a caller-supplied action whitelist."""

    def __init__(self, model):
        self.model = model

    def plan_actions(self, goal: str, allowed_actions: List[str]) -> List[str]:
        allowed = [str(a) for a in allowed_actions if str(a).strip()]
        if not allowed:
            return []
        try:
            raw = self.model.generate(_PLAN_PROMPT.format(actions=json.dumps(allowed), goal=goal))
            proposed = _extract_json(raw, "[", "]")
        except Exception:
            proposed = None
        if not isinstance(proposed, list):
            return allowed  # fail closed: keep the caller's own order
        chosen, seen = [], set()
        for a in proposed:
            a = str(a)
            if a in allowed and a not in seen:
                chosen.append(a)
                seen.add(a)
        return chosen or allowed


class LLMCritic:
    """Verifies a completed ReasoningTask; can only reference steps that already ran."""

    def __init__(self, model):
        self.model = model

    def critique(self, task) -> Dict[str, Any]:
        steps = [{"id": s.id, "action": s.action, "status": s.status, "error": s.error}
                  for s in task.steps]
        try:
            raw = self.model.generate(_CRITIQUE_PROMPT.format(goal=task.goal, steps=json.dumps(steps)))
            parsed = _extract_json(raw, "{", "}")
        except Exception:
            parsed = None
        if not isinstance(parsed, dict):
            return {"passed": False, "reason": "critique unavailable", "actions": []}
        known = {s["action"] for s in steps}
        actions = [a for a in parsed.get("actions", []) if a in known]
        return {"passed": bool(parsed.get("passed", False)),
                "reason": str(parsed.get("reason", "")),
                "actions": actions}


class IntelligentReasoner:
    """Wires ReasoningCore to LLMPlanner/LLMCritic without weakening any of its bounds:
    the model can only choose from — never expand — the caller-supplied whitelist."""

    def __init__(self, model, core=None):
        from .reasoning_core import ReasoningCore
        self.core = core or ReasoningCore()
        self.planner = LLMPlanner(model)
        self.critic = LLMCritic(model)

    def run(self, goal: str, allowed_actions: List[str], handlers: dict, verifier=None, task_id=None):
        actions = self.planner.plan_actions(goal, allowed_actions)
        task = self.core.plan(goal, actions, task_id=task_id)
        return self.core.run(task, handlers, verifier=verifier, critic=self.critic.critique)
