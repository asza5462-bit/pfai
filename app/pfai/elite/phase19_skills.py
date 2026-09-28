"""PHASE 19 skills — Unified AI Core; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.elite.capability_router import CapabilityRouter
from pfai.elite.algorithm_intelligence import AlgorithmIntelligence
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_capability_route(**args: Any) -> dict[str, Any]:
    return CapabilityRouter().route(_text(args, "message", "task", "prompt"), context=dict(args.get("context") or {}))


def skill_algorithm_analyze(**args: Any) -> dict[str, Any]:
    return AlgorithmIntelligence().full_pipeline(
        _text(args, "message", "task", "prompt"),
        code=str(args.get("code") or ""),
        implement=bool(args.get("implement", True)),
    )


def skill_unified_ai_core(**args: Any) -> dict[str, Any]:
    orch = args.get("_orchestrator")
    if orch is None:
        return {"ok": False, "error": "orchestrator_required_for_skill_invocation"}
    from pfai.elite.unified_ai_core import UnifiedAICore

    return UnifiedAICore(orch).handle(
        _text(args, "message", "task", "prompt"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        context=dict(args.get("context") or {}),
        allow_training_ops=bool(args.get("allow_training_ops")),
    )


PHASE19_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE19_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="unified_ai",
                capabilities=capabilities or [skill_id, "phase19"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase19", skill_id],
                provenance={"phase": 19, "origin": "pfai_unified_ai_core", "cannot_self_elevate": True},
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
    if PHASE19_SKILLS:
        return
    specs = [
        ("core.capability_route", "Multi-label capability routing", skill_capability_route, ["routing", "planning"], ToolPermission.READ.value, "low"),
        ("core.algorithm_intelligence", "Algorithm analysis + verified optimized templates", skill_algorithm_analyze, ["algorithms", "coding"], ToolPermission.READ.value, "low"),
        ("core.unified_ai", "Unified AI Core entry (requires orchestrator injection)", skill_unified_ai_core, ["unified", "orchestration"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase19_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE19_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase19_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
