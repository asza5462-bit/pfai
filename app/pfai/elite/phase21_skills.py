"""PHASE 21 skills — performance/reliability; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.elite.adaptive_budgets import AdaptiveBudgetSelector
from pfai.elite.task_decomposer import TaskDecomposer
from pfai.elite.latency_pipeline import LatencyPipeline
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_adaptive_budget(**args: Any) -> dict[str, Any]:
    return AdaptiveBudgetSelector().select(
        _text(args, "message", "task"),
        capabilities=list(args.get("capabilities") or []),
        context=dict(args.get("context") or {}),
        forced_tier=args.get("tier"),
    )


def skill_smart_decompose(**args: Any) -> dict[str, Any]:
    return TaskDecomposer().decompose(_text(args, "message", "task"), context=dict(args.get("context") or {}))


def skill_latency_pipeline(**args: Any) -> dict[str, Any]:
    lat = LatencyPipeline()
    lat.mark("routing_started")
    lat.mark("routing_completed")
    lat.mark("response_started")
    lat.mark("response_completed")
    return lat.summary()


def skill_perf_submit(**args: Any) -> dict[str, Any]:
    orch = args.get("_orchestrator")
    if orch is None or not hasattr(orch, "performance"):
        return {"ok": False, "error": "performance_engine_required"}
    return orch.performance.submit_task(
        _text(args, "message", "task"),
        priority=str(args.get("priority") or "USER_INTERACTIVE"),
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
        context=dict(args.get("context") or {}),
    )


PHASE21_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE21_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="performance",
                capabilities=capabilities or [skill_id, "phase21"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase21", skill_id],
                provenance={"phase": 21, "origin": "pfai_performance", "cannot_self_elevate": True},
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
    if PHASE21_SKILLS:
        return
    specs = [
        ("perf.budget", "Adaptive execution budget selection", skill_adaptive_budget, ["planning"], ToolPermission.READ.value, "low"),
        ("perf.decompose", "Smart task decomposition", skill_smart_decompose, ["planning"], ToolPermission.READ.value, "low"),
        ("perf.latency", "Latency pipeline smoke", skill_latency_pipeline, ["evaluation"], ToolPermission.READ.value, "low"),
        ("perf.submit", "Submit task to performance scheduler", skill_perf_submit, ["execution"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase21_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE21_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase21_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
