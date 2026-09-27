"""PHASE 18 skills — Web & Application Engineering Fabric; no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.engineering.application_engineering import ApplicationEngineering
from pfai.engineering.authorized_web_ops import AuthorizedWebFabricOps
from pfai.engineering.coding_agent_bridge import CodingAgentBridge
from pfai.engineering.phase18_chat import Phase18ChatFabric
from pfai.engineering.phase18_security import Phase18SecurityAnalysis
from pfai.engineering.remediation_engine import RemediationEngine
from pfai.engineering.target_registry import TargetRegistry
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_appeng_build(**args: Any) -> dict[str, Any]:
    req = _text(args, "requirement", "task", "prompt")
    if not req:
        return {"ok": False, "error": "requirement_required"}
    return ApplicationEngineering(root=str(args.get("root") or "") or None).build(
        req,
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        run_tests=bool(args.get("run_tests", True)),
        security_review=bool(args.get("security_review", True)),
        apply_safe_fixes=bool(args.get("apply_safe_fixes")),
    )


def skill_appeng_adapters(**args: Any) -> dict[str, Any]:
    return {"ok": True, "adapters": ApplicationEngineering().supported_adapters()}


def skill_coding_inspect(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    return CodingAgentBridge().inspect_repository(
        path,
        target_id=str(args.get("target_id") or ""),
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
    )


def skill_coding_search(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    query = _text(args, "query", "q")
    if not path or not query:
        return {"ok": False, "error": "project_path_and_query_required"}
    return CodingAgentBridge().search_code(
        path,
        query,
        target_id=str(args.get("target_id") or ""),
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
    )


def skill_coding_modify(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    writers = dict(args.get("writers") or {})
    if not path or not writers:
        return {"ok": False, "error": "project_path_and_writers_required"}
    return CodingAgentBridge().apply_modification(
        path,
        writers=writers,
        reason=_text(args, "reason") or "authorized_modification",
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        target_id=str(args.get("target_id") or ""),
        run_tests=bool(args.get("run_tests", True)),
    )


def skill_security_phase18_analyze(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    url = _text(args, "url")
    return Phase18SecurityAnalysis().analyze(path, url=url, headers=dict(args.get("headers") or {}) or None)


def skill_remediation_engine(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    return RemediationEngine(
        allow_auto_safe_fixes=bool(args.get("allow_auto_safe_fixes")),
    ).run(
        path,
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        target_id=str(args.get("target_id") or ""),
        auto_apply=bool(args.get("auto_apply")),
        owner_approved_sensitive=bool(args.get("owner_approved_sensitive")),
    )


def skill_web_fabric_ops(**args: Any) -> dict[str, Any]:
    ops = AuthorizedWebFabricOps(
        registry=TargetRegistry(path=str(args.get("registry_path") or "data/longevity/engineering/target_registry.json"))
    )
    action = str(args.get("action") or "status")
    if action == "status":
        return ops.status()
    target_id = str(args.get("target_id") or "")
    url = _text(args, "url", "resource")
    if not target_id:
        return ops.reject_unregistered_url(url or "https://example.invalid")
    if action == "health":
        return ops.health_check(
            target_id=target_id,
            url=url,
            actor=str(args.get("actor") or ""),
            approved=bool(args.get("approved")),
        )
    if action == "crawl":
        return ops.controlled_crawl(
            target_id=target_id,
            start_url=url,
            actor=str(args.get("actor") or ""),
            approved=bool(args.get("approved")),
            max_pages=int(args.get("max_pages") or 5),
        )
    if action == "discover":
        return ops.discover_endpoints(
            target_id=target_id,
            base_url=url,
            actor=str(args.get("actor") or ""),
            approved=bool(args.get("approved")),
        )
    if action == "api_test":
        return ops.api_test(
            target_id=target_id,
            url=url,
            actor=str(args.get("actor") or ""),
            approved=bool(args.get("approved")),
            expect_status=args.get("expect_status"),
        )
    return ops.http_request(
        target_id=target_id,
        url=url,
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
        method=str(args.get("method") or "GET"),
    )


def skill_target_registry_v2(**args: Any) -> dict[str, Any]:
    reg = TargetRegistry(path=str(args.get("registry_path") or "data/longevity/engineering/target_registry.json"))
    action = str(args.get("action") or "register")
    if action == "resolve":
        return reg.resolve(target_id=str(args.get("target_id") or ""), name=_text(args, "name"))
    if action == "authorize":
        return reg.authorize(
            str(args.get("target_id") or ""),
            approval_reference=str(args.get("approval_reference") or ""),
            authorization_scope=str(args.get("authorization_scope") or args.get("scope") or ""),
            actor=str(args.get("actor") or ""),
            allowed_actions=list(args.get("allowed_actions") or []) or None,
        )
    if action == "revoke":
        return reg.revoke(str(args.get("target_id") or ""), actor=str(args.get("actor") or ""))
    if action == "list":
        return {"ok": True, "targets": reg.list_targets()}
    return reg.register(
        name=_text(args, "name") or "unnamed",
        target_type=str(args.get("target_type") or "local_project"),
        owner=str(args.get("owner") or args.get("actor") or ""),
        environment=str(args.get("environment") or "staging"),
        scope=str(args.get("scope") or args.get("authorization_scope") or ""),
        authorization_scope=str(args.get("authorization_scope") or args.get("scope") or ""),
        allowed_actions=list(args.get("allowed_actions") or []),
        allowed_domains=list(args.get("allowed_domains") or []),
        allowed_hosts=list(args.get("allowed_hosts") or []),
        allowed_ports=list(args.get("allowed_ports") or []),
        allowed_paths=list(args.get("allowed_paths") or ["/"]),
        testing_methods=list(args.get("testing_methods") or ["static_analysis", "passive_inspect"]),
        approval_reference=str(args.get("approval_reference") or ""),
        authorize_now=bool(args.get("authorize_now")),
        expiration=float(args.get("expiration") or 0),
        actor=str(args.get("actor") or ""),
        audit_metadata=dict(args.get("audit_metadata") or {}),
    )


def skill_phase18_chat(**args: Any) -> dict[str, Any]:
    return Phase18ChatFabric().handle(
        _text(args, "message", "task", "prompt"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        context=dict(args.get("context") or args),
    )


PHASE18_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE18_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="application_engineering",
                capabilities=capabilities or [skill_id, "phase18"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["phase18", skill_id],
                provenance={"phase": 18, "origin": "pfai_web_app_engineering", "cannot_self_elevate": True},
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
    if PHASE18_SKILLS:
        return
    specs = [
        ("appeng.build", "Application engineering build pipeline", skill_appeng_build, ["engineering", "build"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("appeng.adapters", "List implemented project adapters", skill_appeng_adapters, ["engineering", "adapters"], ToolPermission.READ.value, "low"),
        ("coding.inspect", "Repository inspection via coding agent", skill_coding_inspect, ["coding", "inspect"], ToolPermission.READ.value, "low"),
        ("coding.search", "Code search via coding agent", skill_coding_search, ["coding", "search"], ToolPermission.READ.value, "low"),
        ("coding.modify", "Authorized code modification with changeset", skill_coding_modify, ["coding", "modify"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("security.phase18_analyze", "Expanded defensive security analysis", skill_security_phase18_analyze, ["security", "analysis"], ToolPermission.READ.value, "low"),
        ("security.remediation_engine", "Phase 18 remediation engine pipeline", skill_remediation_engine, ["security", "remediation"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("web.fabric_ops", "Authorized WebFabric operations", skill_web_fabric_ops, ["web", "fabric"], ToolPermission.READ.value, "medium"),
        ("registry.target_v2", "Versioned target registry operations", skill_target_registry_v2, ["registry", "authorization"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("chat.phase18", "Phase 18 unified chat fabric", skill_phase18_chat, ["chat", "engineering", "security"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase18_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE18_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase18_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
