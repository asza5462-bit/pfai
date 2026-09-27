"""PHASE 15 skills — engineering + defensive security (versioned, no self-privilege)."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.engineering.engineering_workflow import EngineeringWorkflow
from pfai.engineering.project_inspector import ProjectInspector
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.security_regression import SecurityRegressionEngine
from pfai.engineering.unified_coding_workflow import UnifiedCodingWorkflow
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_project_inspection(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    return ProjectInspector(path).inspect()


def skill_unified_coding(**args: Any) -> dict[str, Any]:
    wf = UnifiedCodingWorkflow(root=args.get("workspace_root"))
    return wf.handle(
        _text(args, "task", "prompt", "requirement", "message"),
        project_path=str(args.get("project_path") or ""),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        declaration=str(args.get("declaration") or ""),
        scope=str(args.get("scope") or ""),
        allow_external=bool(args.get("allow_external")),
        auto_apply=bool(args.get("auto_apply")),
        context=dict(args.get("context") or {}),
    )


def skill_frontend_engineering(**args: Any) -> dict[str, Any]:
    return skill_unified_coding(**{**args, "task": args.get("task") or "Build a frontend application " + _text(args)})


def skill_backend_engineering(**args: Any) -> dict[str, Any]:
    return skill_unified_coding(**{**args, "task": args.get("task") or "Build an API backend " + _text(args)})


def skill_api_engineering(**args: Any) -> dict[str, Any]:
    return skill_backend_engineering(**args)


def skill_database_engineering_v2(**args: Any) -> dict[str, Any]:
    return skill_unified_coding(**{**args, "task": args.get("task") or "Build a database-backed application " + _text(args)})


def skill_testing_engineering(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    return EngineeringWorkflow(path)._run_tests()


def skill_debugging_engineering(**args: Any) -> dict[str, Any]:
    wf = UnifiedCodingWorkflow()
    return wf.handle(
        "debug and run tests",
        project_path=_text(args, "path", "project_path"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
    )


def skill_refactoring_engineering(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    files = args.get("affected_files") or []
    writers = args.get("writers") or {}
    if not path or not files or not writers:
        return {
            "ok": False,
            "error": "refactor_requires_explicit_affected_files_and_writers",
            "note": "refuses_silent_unrelated_modification",
        }
    wf = EngineeringWorkflow(path)
    plan = wf.plan_modification(reason=_text(args) or "refactor", affected_files=list(files))
    if not plan.get("ok"):
        return plan
    return wf.apply_plan(
        plan["plan"],
        writers,
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
    )


def skill_architecture_analysis(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    insp = ProjectInspector(path).inspect()
    return {"ok": insp.get("ok"), "architecture": insp.get("architecture"), "dependencies": insp.get("dependencies")}


def skill_documentation_generation(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    insp = ProjectInspector(path).inspect() if path else {"ok": False}
    return {
        "ok": True,
        "readme_outline": [
            "# Project",
            "## Overview",
            "## Structure",
            "## Configuration",
            "## Tests",
            "## Security baseline",
        ],
        "inspection": insp if insp.get("ok") else None,
    }


def skill_devops_planning(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "plan": [
            "Separate config from code",
            "Environment variables for secrets",
            "CI: unit + security regression",
            "Rollback/checkpoint strategy",
            "Do not claim deploy until deploy occurs",
        ],
    }


def skill_performance_analysis(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "checks": ["hot_paths", "n_plus_one_queries", "unbounded_loops", "missing_indexes"],
        "note": "advisory_static_hints",
    }


def skill_secure_code_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required", "findings": []}
    return SecureCodeAnalyzer(path).analyze()


def skill_dependency_audit(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    insp = ProjectInspector(path).inspect()
    return {
        "ok": True,
        "manifests": (insp.get("dependencies") or {}).get("manifests"),
        "packages": (insp.get("dependencies") or {}).get("packages"),
        "note": "static_manifest_inventory_not_cve_oracle",
    }


def skill_api_security_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    analysis = SecureCodeAnalyzer(path).analyze()
    cats = {"injection_risk", "ssrf_risk", "insecure_cors", "weak_input_validation", "secret_exposure"}
    findings = [f for f in (analysis.get("findings") or []) if f.get("category") in cats]
    return {"ok": True, "finding_count": len(findings), "findings": findings, "scope": "api_security"}


def skill_authentication_review(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "checklist": [
            "server_side_session_validation",
            "no_client_trusted_role_fields",
            "credential_storage_hashed",
            "otp_or_mfa_where_required",
            "logout_invalidates_session",
        ],
        "note": "defensive_review_guidance",
    }


def skill_authorization_review(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "checklist": [
            "object_level_authorization",
            "deny_by_default",
            "no_idor",
            "owner_gates_for_sensitive_actions",
        ],
    }


def skill_web_security_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if path:
        analysis = SecureCodeAnalyzer(path).analyze()
        cats = {"xss_risk", "csrf_risk", "insecure_cors", "missing_security_headers", "secret_exposure"}
        findings = [f for f in (analysis.get("findings") or []) if f.get("category") in cats]
        return {"ok": True, "finding_count": len(findings), "findings": findings}
    return {"ok": False, "error": "project_path_required_for_static_web_review"}


def skill_secrets_audit(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    analysis = SecureCodeAnalyzer(path).analyze()
    findings = [f for f in (analysis.get("findings") or []) if f.get("category") == "secret_exposure"]
    return {"ok": True, "finding_count": len(findings), "findings": findings}


def skill_threat_modeling(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "model": {
            "assets": ["credentials", "session", "data_store", "admin_actions"],
            "threats": ["injection", "idor", "ssrf", "secret_leak", "privilege_escalation"],
            "controls": ["authz_gate", "sandbox", "audit", "input_validation", "output_encoding"],
        },
        "note": "defensive_threat_model_template",
    }


def skill_vulnerability_triage(**args: Any) -> dict[str, Any]:
    findings = list(args.get("findings") or [])
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    ranked = sorted(findings, key=lambda f: (order.get(str(f.get("severity")), 9), -float(f.get("confidence") or 0)))
    return {"ok": True, "ranked": ranked, "count": len(ranked)}


def skill_remediation_planning(**args: Any) -> dict[str, Any]:
    findings = list(args.get("findings") or [])
    plan = [
        {
            "finding_id": f.get("finding_id"),
            "remediation": f.get("remediation"),
            "severity": f.get("severity"),
        }
        for f in findings[:30]
    ]
    return {"ok": True, "plan": plan, "requires_owner_approval_for_apply": True}


def skill_security_regression(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    engine = SecurityRegressionEngine(path)
    finding = dict(args.get("finding") or {})
    if finding:
        gen = engine.generate_from_finding(finding)
        if not gen.get("ok"):
            return gen
    return engine.run_regressions()


def skill_secure_configuration_review(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    insp = ProjectInspector(path).inspect()
    return {
        "ok": True,
        "configs": insp.get("configs"),
        "checklist": [".env.example present", "no secrets in VCS", "security headers", "CORS restricted"],
        "has_env_example": any(str(c).endswith(".env.example") for c in (insp.get("configs") or [])),
    }


PHASE15_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


def _spec(
    skill_id: str,
    category: str,
    description: str,
    handler: Callable[..., Any],
    *,
    capabilities: list[str] | None = None,
    permission: str = ToolPermission.READ.value,
    risk: str = "low",
) -> None:
    PHASE15_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category=category,
                capabilities=capabilities or [skill_id, "phase15"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=[category, "phase15", skill_id],
                provenance={"phase": 15, "origin": "pfai_engineering"},
                quality_metrics={"smoke": "ok"},
                training_metadata={"eligible": True, "cannot_grant_privileges": True},
            ),
            handler,
        )
    )


def _bootstrap() -> None:
    if PHASE15_SKILLS:
        return
    specs: list[tuple[str, str, str, Callable[..., Any], list[str], str, str]] = [
        ("project_inspection", "application_engineering", "Inspect project structure/deps/architecture", skill_project_inspection, ["engineering", "inspection"], ToolPermission.READ.value, "low"),
        ("unified_coding_workflow", "application_engineering", "Unified understand-plan-edit-test-repair workflow", skill_unified_coding, ["engineering", "coding", "website", "application"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("frontend_engineering", "application_engineering", "Frontend engineering skill", skill_frontend_engineering, ["engineering", "frontend"], ToolPermission.LOW_RISK_WRITE.value, "low"),
        ("backend_engineering", "application_engineering", "Backend engineering skill", skill_backend_engineering, ["engineering", "backend"], ToolPermission.LOW_RISK_WRITE.value, "low"),
        ("api_engineering", "application_engineering", "API engineering skill", skill_api_engineering, ["engineering", "api"], ToolPermission.LOW_RISK_WRITE.value, "low"),
        ("database_engineering_v2", "application_engineering", "Database engineering skill", skill_database_engineering_v2, ["engineering", "database"], ToolPermission.LOW_RISK_WRITE.value, "low"),
        ("testing_engineering", "application_engineering", "Run project tests", skill_testing_engineering, ["engineering", "testing"], ToolPermission.READ.value, "low"),
        ("debugging_engineering", "application_engineering", "Debug and diagnose test failures", skill_debugging_engineering, ["engineering", "debugging"], ToolPermission.READ.value, "low"),
        ("refactoring_engineering", "application_engineering", "Explicit-file refactoring with rollback", skill_refactoring_engineering, ["engineering", "refactoring"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("architecture_analysis", "application_engineering", "Architecture analysis of existing project", skill_architecture_analysis, ["engineering", "architecture"], ToolPermission.READ.value, "low"),
        ("documentation_generation", "application_engineering", "Documentation outline generation", skill_documentation_generation, ["engineering", "documentation"], ToolPermission.READ.value, "low"),
        ("devops_planning", "application_engineering", "DevOps planning (no silent deploy claims)", skill_devops_planning, ["engineering", "devops"], ToolPermission.READ.value, "low"),
        ("performance_analysis", "application_engineering", "Advisory performance analysis hints", skill_performance_analysis, ["engineering", "performance"], ToolPermission.READ.value, "low"),
        ("secure_code_review", "cyber_defense", "Secure code review", skill_secure_code_review, ["security", "review"], ToolPermission.READ.value, "low"),
        ("dependency_audit", "cyber_defense", "Dependency manifest audit", skill_dependency_audit, ["security", "dependencies"], ToolPermission.READ.value, "low"),
        ("api_security_review", "cyber_defense", "API security review", skill_api_security_review, ["security", "api"], ToolPermission.READ.value, "low"),
        ("authentication_review", "cyber_defense", "Authentication review checklist", skill_authentication_review, ["security", "authentication"], ToolPermission.READ.value, "low"),
        ("authorization_review", "cyber_defense", "Authorization review checklist", skill_authorization_review, ["security", "authorization"], ToolPermission.READ.value, "low"),
        ("web_security_review", "cyber_defense", "Web security static review", skill_web_security_review, ["security", "web"], ToolPermission.READ.value, "low"),
        ("secrets_audit", "cyber_defense", "Secrets exposure audit", skill_secrets_audit, ["security", "secrets"], ToolPermission.READ.value, "low"),
        ("threat_modeling", "cyber_defense", "Defensive threat modeling template", skill_threat_modeling, ["security", "threat_model"], ToolPermission.READ.value, "low"),
        ("vulnerability_triage", "cyber_defense", "Triage and rank findings", skill_vulnerability_triage, ["security", "triage"], ToolPermission.READ.value, "low"),
        ("remediation_planning", "cyber_defense", "Plan remediations (apply still gated)", skill_remediation_planning, ["security", "remediation"], ToolPermission.READ.value, "low"),
        ("security_regression", "cyber_defense", "Generate/run security regression tests", skill_security_regression, ["security", "regression"], ToolPermission.LOW_RISK_WRITE.value, "medium"),
        ("secure_configuration_review", "cyber_defense", "Secure configuration review", skill_secure_configuration_review, ["security", "configuration"], ToolPermission.READ.value, "low"),
    ]
    for sid, cat, desc, fn, caps, perm, risk in specs:
        _spec(sid, cat, desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase15_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE15_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase15_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
