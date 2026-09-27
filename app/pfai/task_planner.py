"""Task Planner — ReasoningCore adapter (PHASE 4).

Every executable step passes through AuthorizedExecutor.
Bounded max steps / tool calls; forbids planner self-modification and unsafe actions.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable

from pfai.interfaces.planner import PlanStep, TaskPlan, TaskPlannerProtocol
from pfai.interfaces.tools import ToolPermission
from pfai.authorized_execution import AuthorizedExecutor, PermissionGate
from pfai.reasoning_core import ReasoningCore

__all__ = ["PlanStep", "TaskPlan", "TaskPlannerProtocol", "TaskPlanner"]

PHASE = 4

# Hard-forbidden action prefixes/names — never planned or executed.
FORBIDDEN_ACTIONS = {
    "modify_security",
    "mutate_weights",
    "fine_tune",
    "train_weights",
    "rewrite_architecture",
    "read_secrets",
    "self_modify_planner",
    "arbitrary_code",
    "write_code_file",
    "exec_shell",
    "bypass_auth",
}

DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_TOOL_CALLS = 8


class TaskPlanner:
    """Bounded plan → authorize → execute → verify over ReasoningCore."""

    def __init__(
        self,
        *,
        executor: AuthorizedExecutor | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
        tool_runner: Callable[..., dict[str, Any]] | None = None,
        skill_runner: Callable[..., dict[str, Any]] | None = None,
        memory_query: Callable[..., Any] | None = None,
        knowledge_query: Callable[..., Any] | None = None,
        eval_runner: Callable[..., Any] | None = None,
        learn_ingest: Callable[..., Any] | None = None,
    ) -> None:
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.max_steps = max(1, int(max_steps))
        self.max_tool_calls = max(1, int(max_tool_calls))
        self.core = ReasoningCore(max_steps=self.max_steps, max_attempts=2, max_repairs=1)
        self.tool_runner = tool_runner
        self.skill_runner = skill_runner
        self.memory_query = memory_query
        self.knowledge_query = knowledge_query
        self.eval_runner = eval_runner
        self.learn_ingest = learn_ingest
        self._plans: dict[str, TaskPlan] = {}
        self._tool_calls = 0

    def _is_forbidden(self, action: str) -> bool:
        a = (action or "").strip().lower()
        if a in FORBIDDEN_ACTIONS:
            return True
        return any(a.startswith(f"{x}:") or a.startswith(f"{x}_") for x in FORBIDDEN_ACTIONS)

    def _derive_actions(self, goal: str, actions: list[str] | None) -> list[str]:
        if actions:
            cleaned = []
            for a in actions:
                s = str(a).strip()
                if not s or self._is_forbidden(s):
                    continue
                cleaned.append(s)
            return cleaned[: self.max_steps]
        g = (goal or "").lower()
        derived: list[str] = []
        if any(k in g for k in ("memory", "تذكر", "ذاكرة")):
            derived.append("memory:query")
        if any(k in g for k in ("knowledge", "معرفة", "rag")):
            derived.append("knowledge:query")
        if any(k in g for k in ("eval", "evaluate", "تقييم", "regress")):
            derived.append("eval:run")
        if any(k in g for k in ("learn", "feedback", "تعلم", "correct")):
            derived.append("learn:ingest")
        if any(k in g for k in ("health", "status", "فحص")):
            derived.append("tool:health_check")
        if not derived:
            derived = ["memory:query", "knowledge:query", "eval:run"]
        return derived[: self.max_steps]

    def plan(self, goal: str, actions: list[str] | None = None) -> TaskPlan:
        acts = self._derive_actions(goal, actions)
        plan_id = uuid.uuid4().hex[:12]
        steps = [
            PlanStep(id=str(i + 1), action=a, status="pending")
            for i, a in enumerate(acts)
        ]
        plan = TaskPlan(plan_id=plan_id, goal=goal, steps=steps, status="pending")
        self._plans[plan_id] = plan
        return plan

    def get(self, plan_id: str) -> TaskPlan | None:
        return self._plans.get(plan_id)

    def run(
        self,
        plan: TaskPlan,
        *,
        handlers: dict[str, Any] | None = None,
        approved: bool = False,
        actor: str = "",
        verify: bool = True,
    ) -> TaskPlan:
        """Execute plan steps only through AuthorizedExecutor (never raw handlers)."""
        _ = handlers  # ignored — prevents bypass of authorization layer
        self._tool_calls = 0
        plan.status = "running"
        for step in plan.steps:
            if self._is_forbidden(step.action):
                step.status = "blocked"
                step.error = "forbidden action"
                plan.status = "blocked"
                self.executor.audit.record(
                    kind="planner",
                    name=step.action,
                    permission=ToolPermission.PRODUCTION,
                    allowed=False,
                    approved=approved,
                    actor=actor,
                    reason="forbidden planner action",
                )
                return plan
            if self._tool_calls >= self.max_tool_calls and step.action.startswith("tool:"):
                step.status = "blocked"
                step.error = "max tool calls exceeded"
                plan.status = "blocked"
                return plan

            result = self._run_step(step, plan, approved=approved, actor=actor)
            step.result = result
            if not result.get("ok"):
                step.status = "failed"
                step.error = result.get("error") or "step failed"
                if result.get("needs_approval"):
                    plan.status = "waiting_for_approval"
                    plan.verification = {"passed": False, "reason": "owner approval required"}
                    return plan
                plan.status = "failed"
                return plan
            step.status = "success"
            plan.working_memory.append(f"step:{step.id}:{step.action}=ok")

        if verify:
            plan.verification = self._verify(plan, approved=approved, actor=actor)
            plan.status = "verified" if plan.verification.get("passed") else "unverified"
        else:
            plan.status = "completed"
            plan.verification = {"passed": True, "reason": "verify_skipped"}
        self._plans[plan.plan_id] = plan
        return plan

    def _permission_for_action(self, action: str) -> ToolPermission:
        a = action.lower()
        if a.startswith("tool:"):
            # defer to tool router; treat as READ unless known sensitive names
            name = a.split(":", 1)[-1]
            if any(x in name for x in ("forget", "delete", "continuous_", "remember", "correct", "save_owner")):
                return ToolPermission.HIGH_RISK_WRITE
            return ToolPermission.READ
        if a.startswith("skill:"):
            return ToolPermission.READ  # skill registry enforces its own permission
        if a.startswith("learn:"):
            return ToolPermission.LOW_RISK_WRITE
        if a.startswith(("memory:", "knowledge:", "eval:")):
            return ToolPermission.READ
        return ToolPermission.READ

    def _run_step(
        self,
        step: PlanStep,
        plan: TaskPlan,
        *,
        approved: bool,
        actor: str,
    ) -> dict[str, Any]:
        action = step.action
        perm = self._permission_for_action(action)

        def handler(**_kwargs: Any) -> Any:
            return self._dispatch(action, plan, approved=approved, actor=actor)

        outer = self.executor.execute(
            kind="planner_step",
            name=action,
            permission=perm,
            handler=handler,
            args={"goal": plan.goal, "step_id": step.id},
            approved=bool(approved) if perm.requires_owner_gate() else True,
            actor=actor,
        )
        if not outer.get("ok"):
            return outer
        inner = outer.get("result")
        # Propagate nested tool/skill denial (authorization cannot be bypassed).
        if isinstance(inner, dict) and inner.get("ok") is False:
            return {
                "ok": False,
                "needs_approval": bool(inner.get("needs_approval")),
                "error": inner.get("error") or "nested step denied",
                "result": inner,
                "decision_id": outer.get("decision_id"),
            }
        if hasattr(inner, "ok") and getattr(inner, "ok") is False:
            meta = getattr(inner, "meta", None) or {}
            return {
                "ok": False,
                "needs_approval": bool(meta.get("needs_approval")),
                "error": getattr(inner, "error", None) or "nested step denied",
                "result": inner,
                "decision_id": outer.get("decision_id"),
            }
        return outer

    def _dispatch(self, action: str, plan: TaskPlan, *, approved: bool, actor: str) -> Any:
        if action.startswith("tool:"):
            self._tool_calls += 1
            name = action.split(":", 1)[1]
            if self.tool_runner is None:
                raise RuntimeError("tool_runner not configured")
            return self.tool_runner(name, {}, approved=approved, actor=actor)
        if action.startswith("skill:"):
            name = action.split(":", 1)[1]
            if self.skill_runner is None:
                raise RuntimeError("skill_runner not configured")
            return self.skill_runner(name, {}, approved=approved, actor=actor)
        if action.startswith("memory:"):
            if self.memory_query is None:
                return {"hits": []}
            return self.memory_query(plan.goal)
        if action.startswith("knowledge:"):
            if self.knowledge_query is None:
                return {"results": []}
            return self.knowledge_query(plan.goal)
        if action.startswith("eval:"):
            if self.eval_runner is None:
                return {"ok": True, "suite": "smoke"}
            return self.eval_runner("smoke")
        if action.startswith("learn:"):
            if self.learn_ingest is None:
                return {"ok": True, "note": "learn_ingest not configured"}
            return self.learn_ingest(plan.goal, approved=approved, actor=actor)
        raise RuntimeError(f"unsupported action: {action}")

    def _verify(self, plan: TaskPlan, *, approved: bool, actor: str) -> dict[str, Any]:
        if self.eval_runner is None:
            return {"passed": True, "reason": "no evaluator; steps succeeded"}
        try:
            report = self.eval_runner("smoke")
            ok = bool(report.get("ok", True)) if isinstance(report, dict) else bool(getattr(report, "ok", True))
            return {"passed": ok, "reason": "eval smoke", "report": report if isinstance(report, dict) else str(report)}
        except Exception as exc:
            return {"passed": False, "reason": str(exc)}
