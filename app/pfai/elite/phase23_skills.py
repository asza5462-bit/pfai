"""PHASE 23 skills — web research / MCP / source verification; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.mcp_registry import MCPServerRegistry
from pfai.elite.prompt_injection_guard import sanitize_external_content, scan_untrusted_text
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.elite.web_fabric import web_config_report
from pfai.elite.web_research_pipeline import WebResearchPipeline
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_web_provider_status(**args: Any) -> dict[str, Any]:
    return {**web_config_report(), "phase": 23, "PHASE_24_ALLOWED": False}


def skill_web_research(**args: Any) -> dict[str, Any]:
    return WebResearchPipeline().run(
        _text(args, "query", "question", "message"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        limit=int(args.get("limit") or 5),
        fetch_top=int(args.get("fetch_top") or 1),
    )


def skill_source_verify(**args: Any) -> dict[str, Any]:
    content = _text(args, "content", "text", "snippet")
    url = _text(args, "url")
    scan = scan_untrusted_text(content)
    sanitized = sanitize_external_content(content)
    return {
        "ok": True,
        "url": url,
        "trusted": False,
        "injection_scan": scan,
        "sanitized": sanitized,
        "claim_kind": "SOURCE-DERIVED CLAIM",
        "instruction_authority": "SYSTEM_OWNER_ONLY",
        "PHASE_24_ALLOWED": False,
    }


def skill_technical_research(**args: Any) -> dict[str, Any]:
    q = _text(args, "query", "topic", "message")
    out = WebResearchPipeline().run(
        f"technical research: {q}",
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
    )
    out["skill"] = "research.technical"
    return out


def skill_coding_research(**args: Any) -> dict[str, Any]:
    q = _text(args, "query", "topic", "message")
    out = WebResearchPipeline().run(
        f"coding research: {q}",
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
    )
    out["skill"] = "research.coding"
    return out


def skill_mcp_status(**args: Any) -> dict[str, Any]:
    orch = args.get("_orchestrator")
    if orch is not None and getattr(orch, "mcp_registry", None):
        return orch.mcp_registry.health()
    return MCPServerRegistry().health()


PHASE23_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE23_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="web_research",
                capabilities=capabilities or [skill_id, "phase23"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase23", skill_id],
                provenance={"phase": 23, "origin": "pfai_web_fabric", "cannot_self_elevate": True},
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
    if PHASE23_SKILLS:
        return
    specs = [
        ("research.web_status", "Web provider configuration status", skill_web_provider_status, ["web", "research"], ToolPermission.READ.value, "low"),
        ("research.web", "Web research pipeline with provenance", skill_web_research, ["research", "web"], ToolPermission.READ.value, "medium"),
        ("research.source_verify", "Source verification + injection scan", skill_source_verify, ["research", "security"], ToolPermission.READ.value, "low"),
        ("research.technical", "Technical research orchestration", skill_technical_research, ["research", "technical"], ToolPermission.READ.value, "medium"),
        ("research.coding", "Coding research orchestration", skill_coding_research, ["research", "coding"], ToolPermission.READ.value, "medium"),
        ("research.mcp_status", "MCP registry health (untrusted default)", skill_mcp_status, ["mcp"], ToolPermission.READ.value, "low"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase23_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE23_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase23_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
