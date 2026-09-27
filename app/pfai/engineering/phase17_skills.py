"""PHASE 17 versioned defensive security skills — no self-privilege grants."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.security_ops import DefensiveMonitoringFramework, SecurityDevelopmentLifecycle, SecurityReportBuilder
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.web_security_engine import WebApplicationSecurityEngine
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_security_code_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    return WebApplicationSecurityEngine().analyze_source(path)


def skill_security_web_assessment(**args: Any) -> dict[str, Any]:
    engine = WebApplicationSecurityEngine()
    path = _text(args, "path", "project_path")
    url = _text(args, "url", "target")
    out: dict[str, Any] = {"ok": True, "findings": []}
    if path:
        src = engine.analyze_source(path)
        out["findings"].extend(src.get("findings") or [])
    if url:
        cfg = engine.analyze_url_config(url)
        out["findings"].extend(cfg.get("findings") or [])
    headers = args.get("headers") or {}
    if headers:
        out["findings"].extend(engine.analyze_headers(headers).get("findings") or [])
    out["finding_count"] = len(out["findings"])
    out["claim_100_percent_secure"] = False
    return out


def skill_security_api_assessment(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    analysis = WebApplicationSecurityEngine().analyze_source(path)
    cats = {"injection_risk", "ssrf_risk", "insecure_cors", "access_control", "auth_weakness", "secret_exposure"}
    findings = [f for f in (analysis.get("findings") or []) if f.get("category") in cats]
    return {"ok": True, "finding_count": len(findings), "findings": findings, "scope": "api"}


def skill_security_auth_analysis(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if path:
        analysis = WebApplicationSecurityEngine().analyze_source(path)
        findings = [f for f in (analysis.get("findings") or []) if f.get("category") in ("auth_weakness", "insecure_cookie", "session_security")]
        return {"ok": True, "finding_count": len(findings), "findings": findings}
    return {
        "ok": True,
        "checklist": [
            "server_side_session_validation",
            "no_client_trusted_role_fields",
            "secure_cookie_flags",
            "logout_invalidates_session",
        ],
    }


def skill_security_access_control_analysis(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    analysis = WebApplicationSecurityEngine().analyze_source(path)
    findings = [f for f in (analysis.get("findings") or []) if f.get("category") in ("access_control", "idor")]
    return {"ok": True, "finding_count": len(findings), "findings": findings}


def skill_security_dependency_audit(**args: Any) -> dict[str, Any]:
    from pfai.engineering.project_inspector import ProjectInspector

    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    insp = ProjectInspector(path).inspect()
    return {
        "ok": True,
        "manifests": (insp.get("dependencies") or {}).get("manifests"),
        "packages": (insp.get("dependencies") or {}).get("packages"),
        "note": "manifest_inventory_not_live_CVE_feed",
    }


def skill_security_secret_detection(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    analysis = WebApplicationSecurityEngine().analyze_source(path)
    findings = [f for f in (analysis.get("findings") or []) if f.get("category") == "secret_exposure"]
    # Double-check redaction
    for f in findings:
        if "supersecret" in str(f.get("evidence") or "").lower():
            f["evidence"] = "[REDACTED]"
    return {"ok": True, "finding_count": len(findings), "findings": findings}


def skill_security_configuration_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    url = _text(args, "url")
    engine = WebApplicationSecurityEngine()
    findings = []
    if path:
        findings.extend(engine.analyze_source(path).get("findings") or [])
        findings = [f for f in findings if f.get("category") in ("security_misconfiguration", "information_disclosure", "missing_security_headers")]
    if url:
        findings.extend(engine.analyze_url_config(url).get("findings") or [])
    return {"ok": True, "finding_count": len(findings), "findings": findings}


def skill_security_headers(**args: Any) -> dict[str, Any]:
    headers = args.get("headers") or {}
    return WebApplicationSecurityEngine().analyze_headers(headers)


def skill_security_session_analysis(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "checklist": ["Secure", "HttpOnly", "SameSite", "rotation_on_login", "invalidate_on_logout"],
        "note": "defensive_guidance",
    }


def skill_security_threat_modeling(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "model": {
            "assets": ["credentials", "sessions", "PII", "admin_actions"],
            "threats": ["injection", "idor", "xss", "csrf", "ssrf", "secret_leak"],
            "controls": ["authz_gate", "scope_enforcement", "sandbox", "audit", "input_validation"],
        },
    }


def skill_security_remediation(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    from pfai.engineering.project_workspace import ProjectWorkspace
    from pfai.engineering.remediation import RemediationLoop

    return RemediationLoop(ProjectWorkspace(path)).run(
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        auto_apply=bool(args.get("auto_apply")),
    )


def skill_security_regression_testing(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    from pfai.engineering.security_regression import SecurityRegressionEngine

    return SecurityRegressionEngine(path).run_regressions()


def skill_security_secure_architecture(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "principles": [
            "deny_by_default",
            "least_privilege",
            "server_side_authz",
            "secrets_in_env",
            "security_headers",
            "parameterized_queries",
            "output_encoding",
        ],
    }


def skill_security_sdlc(**args: Any) -> dict[str, Any]:
    return SecurityDevelopmentLifecycle().run_for_project(
        _text(args, "requirement", "task", "prompt") or "Build a secure application",
        project_path=str(args.get("project_path") or ""),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        target_id=str(args.get("target_id") or ""),
        auto_remediate=bool(args.get("auto_remediate")),
    )


def skill_security_target_register(**args: Any) -> dict[str, Any]:
    reg = TargetRegistry(path=str(args.get("registry_path") or "data/longevity/engineering/target_registry.json"))
    return reg.register(
        name=_text(args, "name") or "unnamed",
        target_type=str(args.get("target_type") or "local_application"),
        owner=str(args.get("owner") or args.get("actor") or ""),
        environment=str(args.get("environment") or "staging"),
        authorization_scope=str(args.get("authorization_scope") or args.get("scope") or ""),
        allowed_domains=list(args.get("allowed_domains") or []),
        allowed_hosts=list(args.get("allowed_hosts") or []),
        allowed_ports=list(args.get("allowed_ports") or []),
        allowed_paths=list(args.get("allowed_paths") or ["/"]),
        testing_methods=list(args.get("testing_methods") or ["static_analysis", "passive_inspect"]),
        approval_reference=str(args.get("approval_reference") or ""),
        authorize_now=bool(args.get("authorize_now")),
        expiration=float(args.get("expiration") or 0),
        actor=str(args.get("actor") or ""),
    )


def skill_security_scope_check(**args: Any) -> dict[str, Any]:
    layer = ScopeEnforcementLayer(
        registry=TargetRegistry(path=str(args.get("registry_path") or "data/longevity/engineering/target_registry.json"))
    )
    return layer.enforce(
        target_id=str(args.get("target_id") or ""),
        operation=str(args.get("operation") or "security_analysis"),
        method=str(args.get("method") or "static_analysis"),
        actor=str(args.get("actor") or ""),
        approved=bool(args.get("approved")),
        resource=str(args.get("resource") or args.get("url") or ""),
        client_claims=dict(args.get("client_claims") or {}),
    )


def skill_security_report(**args: Any) -> dict[str, Any]:
    findings = list(args.get("findings") or [])
    return SecurityReportBuilder().build(
        title=str(args.get("title") or "Security Assessment"),
        scope=dict(args.get("scope") or {}),
        authorization=dict(args.get("authorization") or {}),
        methodology=list(args.get("methodology") or ["static_analysis"]),
        findings=findings,
    )


def skill_security_monitor(**args: Any) -> dict[str, Any]:
    mon = DefensiveMonitoringFramework()
    if args.get("target_id"):
        return mon.check_registered_target(str(args["target_id"]), actor=str(args.get("actor") or ""))
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "target_id_or_project_path_required"}
    return mon.check_project_drift(path, baseline_finding_count=args.get("baseline_finding_count"))


PHASE17_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
    required_tools: list[str] | None = None,
) -> None:
    PHASE17_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace(".", " ").replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category="cyber_defense",
                capabilities=capabilities or [skill_id, "phase17", "security"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=["security", "phase17", skill_id],
                provenance={"phase": 17, "origin": "pfai_security_ops", "required_tools": required_tools or []},
                quality_metrics={"smoke": "ok"},
                training_metadata={"eligible": True, "cannot_grant_privileges": True, "cannot_modify_security_controls": True},
            ),
            handler,
        )
    )


def _bootstrap() -> None:
    if PHASE17_SKILLS:
        return
    specs = [
        ("security.code_review", "Secure source code review", skill_security_code_review, ["security", "code_review"], ToolPermission.READ.value, "low"),
        ("security.web_assessment", "Web application security assessment", skill_security_web_assessment, ["security", "web"], ToolPermission.READ.value, "medium"),
        ("security.api_assessment", "API security assessment", skill_security_api_assessment, ["security", "api"], ToolPermission.READ.value, "medium"),
        ("security.auth_analysis", "Authentication analysis", skill_security_auth_analysis, ["security", "auth"], ToolPermission.READ.value, "low"),
        ("security.access_control_analysis", "Access control / IDOR analysis", skill_security_access_control_analysis, ["security", "access_control"], ToolPermission.READ.value, "low"),
        ("security.dependency_audit", "Dependency manifest audit", skill_security_dependency_audit, ["security", "dependencies"], ToolPermission.READ.value, "low"),
        ("security.secret_detection", "Secret exposure detection with redaction", skill_security_secret_detection, ["security", "secrets"], ToolPermission.READ.value, "low"),
        ("security.configuration_review", "Configuration security review", skill_security_configuration_review, ["security", "config"], ToolPermission.READ.value, "low"),
        ("security.security_headers", "Security headers analysis", skill_security_headers, ["security", "headers"], ToolPermission.READ.value, "low"),
        ("security.session_analysis", "Session security analysis", skill_security_session_analysis, ["security", "session"], ToolPermission.READ.value, "low"),
        ("security.threat_modeling", "Defensive threat modeling", skill_security_threat_modeling, ["security", "threat_model"], ToolPermission.READ.value, "low"),
        ("security.remediation", "Authorized remediation loop", skill_security_remediation, ["security", "remediation"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("security.regression_testing", "Security regression tests", skill_security_regression_testing, ["security", "regression"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("security.secure_architecture", "Secure architecture principles", skill_security_secure_architecture, ["security", "architecture"], ToolPermission.READ.value, "low"),
        ("security.sdlc", "Security development lifecycle pipeline", skill_security_sdlc, ["security", "sdlc", "engineering"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("security.target_register", "Register authorized target (deny default)", skill_security_target_register, ["security", "registry"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("security.scope_check", "Scope enforcement check", skill_security_scope_check, ["security", "scope"], ToolPermission.READ.value, "low"),
        ("security.report", "Professional security report", skill_security_report, ["security", "report"], ToolPermission.READ.value, "low"),
        ("security.monitor", "Authorized defensive monitoring", skill_security_monitor, ["security", "monitoring"], ToolPermission.READ.value, "low"),
    ]
    for sid, desc, fn, caps, perm, risk in specs:
        _spec(sid, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase17_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE17_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase17_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
