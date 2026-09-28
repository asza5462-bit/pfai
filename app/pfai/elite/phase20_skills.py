"""PHASE 20 skills — Agent Execution Engine; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.elite.task_decomposer import TaskDecomposer
from pfai.elite.task_state import TaskStateMachine, AgentTask, TaskState
from pfai.elite.research_workflow import ResearchWorkflow
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_agent_decompose(**args: Any) -> dict[str, Any]:
    return TaskDecomposer().decompose(_text(args, "message", "task", "prompt"), context=dict(args.get("context") or {}))


def skill_agent_state_machine(**args: Any) -> dict[str, Any]:
    sm = TaskStateMachine()
    task = AgentTask.create(_text(args, "objective") or "noop")
    nxt = str(args.get("transition_to") or TaskState.PLANNING.value)
    return {"task": task.to_dict(), "transition": sm.transition(task, nxt), "allowed_next": sm.allowed_next(task.state)}


def skill_research_workflow(**args: Any) -> dict[str, Any]:
    return ResearchWorkflow().run(_text(args, "question", "message", "task"))


def skill_agent_execute(**args: Any) -> dict[str, Any]:
    orch = args.get("_orchestrator")
    if orch is None:
        return {"ok": False, "error": "orchestrator_required"}
    from pfai.elite.agent_execution_engine import AgentExecutionEngine

    return AgentExecutionEngine(orch).run(
        _text(args, "message", "task", "prompt"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        context=dict(args.get("context") or {}),
        force_tool_failure=bool(args.get("force_tool_failure")),
        force_model_failure=bool(args.get("force_model_failure")),
    )


PHASE20_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE20_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="agent_execution",
                capabilities=capabilities or [skill_id, "phase20"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase20", skill_id],
                provenance={"phase": 20, "origin": "pfai_agent_execution", "cannot_self_elevate": True},
                quality_metrics={"smoke": "ok"},
                training_metadata={
                    "eligible": True,
                    "cannot_grant_privileges": True,
                    "cannot_modify_security_controls": True,
                    "cannot_modify_authorization_rules": True,
                },
            ),
            handler,
        )
    )


def _bootstrap() -> None:
    if PHASE20_SKILLS:
        return
    specs = [
        ("agent.decompose", "Task decomposition into executable steps", skill_agent_decompose, ["planning", "agent"], ToolPermission.READ.value, "low"),
        ("agent.state_machine", "Task state machine transition check", skill_agent_state_machine, ["agent"], ToolPermission.READ.value, "low"),
        ("agent.research", "Research workflow (honest web status)", skill_research_workflow, ["research", "web"], ToolPermission.READ.value, "low"),
        ("agent.execute", "Agent execution engine entry", skill_agent_execute, ["agent", "execution"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase20_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE20_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase20_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
