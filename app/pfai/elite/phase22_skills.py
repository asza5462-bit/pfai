"""PHASE 22 skills — production runtime / web policy; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.elite.web_fabric import WebPolicyGate, WebResearchSession, web_config_report
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_web_status(**args: Any) -> dict[str, Any]:
    return web_config_report()


def skill_web_policy(**args: Any) -> dict[str, Any]:
    gate = WebPolicyGate(
        allowed_domains=list(args.get("allowed_domains") or []),
        denied_domains=list(args.get("denied_domains") or []),
    )
    url = _text(args, "url")
    return gate.authorize_url(url, approved=bool(args.get("approved")), actor=str(args.get("actor") or ""))


def skill_web_research_session(**args: Any) -> dict[str, Any]:
    session = WebResearchSession()
    return session.research(
        _text(args, "query", "question", "message"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
    )


def skill_production_runtime(**args: Any) -> dict[str, Any]:
    orch = args.get("_orchestrator")
    if orch is None or not hasattr(orch, "production"):
        return {"ok": False, "error": "production_runtime_required"}
    return orch.production.handle(
        _text(args, "message", "task"),
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
        context=dict(args.get("context") or {}),
        authenticated=True,
    )


PHASE22_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE22_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="production_integration",
                capabilities=capabilities or [skill_id, "phase22"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase22", skill_id],
                provenance={"phase": 22, "origin": "pfai_production", "cannot_self_elevate": True},
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
    if PHASE22_SKILLS:
        return
    specs = [
        ("prod.web_status", "Honest web fabric configuration status", skill_web_status, ["web", "research"], ToolPermission.READ.value, "low"),
        ("prod.web_policy", "Web URL policy / SSRF gate", skill_web_policy, ["web", "security"], ToolPermission.READ.value, "low"),
        ("prod.web_research", "Research session (honest NOT_CONFIGURED)", skill_web_research_session, ["research", "web"], ToolPermission.READ.value, "low"),
        ("prod.runtime", "Production runtime entry", skill_production_runtime, ["execution", "agent"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase22_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE22_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase22_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
