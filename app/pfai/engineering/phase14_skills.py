"""PHASE 14 engineering/defense skill handlers + bootstrap into SkillRegistry2."""
from __future__ import annotations

from typing import Any, Callable

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillDefinition
from pfai.engineering.application_builder import ApplicationBuilder
from pfai.engineering.authorized_testing import AuthorizedSecurityTester
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.skill_metrics import SkillEvaluationLedger
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.interfaces.tools import ToolPermission


def _text(args: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return str(args.get("input") or args.get("goal") or args.get("task") or "").strip()


def skill_requirements_analysis(**args: Any) -> dict[str, Any]:
    req = _text(args, "requirement", "task", "prompt")
    return {
        "ok": True,
        "requirements": [s.strip() for s in req.replace(".", "\n").split("\n") if s.strip()][:20],
        "non_functional": ["security_baseline", "tests", "config_separation"],
    }


def skill_project_planning(**args: Any) -> dict[str, Any]:
    req = _text(args, "requirement", "task")
    return {
        "ok": True,
        "plan": [
            "Analyze requirements",
            "Choose architecture/template",
            "Generate structure",
            "Implement core features",
            "Write tests",
            "Security review",
            "Validate & report",
        ],
        "requirement": req[:500],
    }


def skill_architecture_design_eng(**args: Any) -> dict[str, Any]:
    builder = ApplicationBuilder()
    spec = builder.specify(_text(args, "requirement", "task"))
    return {"ok": True, "architecture": spec["architecture"], "kind": spec["kind"]}


def skill_application_build(**args: Any) -> dict[str, Any]:
    builder = ApplicationBuilder(root=args.get("workspace_root"))
    return builder.build(
        _text(args, "requirement", "task", "prompt"),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        run_tests=bool(args.get("run_tests", True)),
        security_review=bool(args.get("security_review", True)),
    )


def skill_secure_code_analysis(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project", "target") or str(args.get("project_path") or "")
    if not path:
        return {"ok": False, "error": "project_path_required", "findings": []}
    return SecureCodeAnalyzer(path).analyze()


def skill_authorized_security_test(**args: Any) -> dict[str, Any]:
    tester = AuthorizedSecurityTester()
    return tester.run(
        _text(args, "target", "url", "path"),
        declaration=str(args.get("declaration") or ""),
        scope=str(args.get("scope") or ""),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        allow_external=bool(args.get("allow_external")),
    )


def skill_security_remediation(**args: Any) -> dict[str, Any]:
    path = _text(args, "path", "project", "project_path")
    if not path:
        return {"ok": False, "error": "project_path_required"}
    builder = ApplicationBuilder()
    return builder.remediate_project(
        path,
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        auto_apply=bool(args.get("auto_apply")),
    )


def skill_target_authorization_check(**args: Any) -> dict[str, Any]:
    gate = TargetAuthorizationGate()
    return gate.require_authorized(
        _text(args, "target", "url", "path"),
        declaration=str(args.get("declaration") or ""),
        scope=str(args.get("scope") or ""),
        approved=bool(args.get("approved")),
        actor=str(args.get("actor") or ""),
        allow_external=bool(args.get("allow_external")),
    )


def skill_defense_secure_headers(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "headers": [
            "Content-Security-Policy",
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Permissions-Policy",
        ],
        "note": "Composable defensive guidance — apply in HTTP layer",
    }


def skill_defense_input_validation(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "rules": [
            "Allowlist expected types/lengths",
            "Reject unexpected fields",
            "Parameterize database queries",
            "Encode output by context",
        ],
    }


def skill_ci_test_planning(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "plan": ["unit", "integration", "security_regression", "dependency_audit"],
    }


def skill_deployment_readiness(**args: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "checklist": [
            "secrets_in_env",
            "https",
            "migrations_reviewed",
            "tests_passing",
            "security_baseline",
            "rollback_plan",
        ],
    }


PHASE14_SKILLS: list[tuple[SkillDefinition, Callable[..., Any]]] = []


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
    PHASE14_SKILLS.append(
        (
            SkillDefinition(
                skill_id=skill_id,
                name=skill_id.replace("_", " ").title(),
                description=description,
                version="1.0.0",
                category=category,
                capabilities=capabilities or [skill_id, "phase14"],
                permissions_required=permission,
                permissions=[permission],
                risk_level=risk,
                enabled=True,
                status="draft",
                health="healthy",
                evaluation_state="smoke_ok",
                tags=[category, "phase14", skill_id],
                provenance={"phase": 14, "origin": "pfai_engineering"},
                quality_metrics={"smoke": "ok"},
                training_metadata={"eligible": True, "cannot_grant_privileges": True},
            ),
            handler,
        )
    )


def _bootstrap() -> None:
    if PHASE14_SKILLS:
        return
    for sid, desc, fn, caps in [
        ("requirements_analysis", "Analyze natural-language requirements", skill_requirements_analysis, ["engineering", "requirements"]),
        ("project_planning_eng", "Plan an engineering project", skill_project_planning, ["engineering", "planning"]),
        ("architecture_design_eng", "Design application architecture", skill_architecture_design_eng, ["engineering", "architecture"]),
        ("application_build", "Build website/app from requirements", skill_application_build, ["engineering", "codegen", "website", "application"]),
        ("frontend_development", "Frontend development guidance/build assist", skill_application_build, ["engineering", "frontend"]),
        ("backend_development", "Backend/API development assist", skill_application_build, ["engineering", "backend", "api"]),
        ("api_development", "API development assist", skill_application_build, ["engineering", "api"]),
        ("database_engineering", "Schema/migration oriented build", skill_application_build, ["engineering", "database"]),
        ("ci_test_planning", "CI and test planning", skill_ci_test_planning, ["engineering", "testing"]),
        ("deployment_readiness_analysis", "Deployment readiness checklist", skill_deployment_readiness, ["engineering", "deploy"]),
        ("secure_code_analysis", "Evidence-based secure code analysis", skill_secure_code_analysis, ["security", "analysis"]),
        ("authorized_security_test", "Authorized defensive security testing", skill_authorized_security_test, ["security", "authorized_testing"]),
        ("security_remediation", "Remediation loop with checkpoint/rollback", skill_security_remediation, ["security", "remediation"]),
        ("target_authorization_check", "Target authorization gate (deny default)", skill_target_authorization_check, ["security", "authorization"]),
        ("defense_secure_headers", "Security headers defense skill", skill_defense_secure_headers, ["security", "defense"]),
        ("defense_input_validation", "Input validation defense skill", skill_defense_input_validation, ["security", "defense"]),
    ]:
        perm = ToolPermission.READ.value
        risk = "low"
        if sid in ("application_build", "frontend_development", "backend_development", "api_development", "database_engineering"):
            perm = ToolPermission.LOW_RISK_WRITE.value
        if sid in ("security_remediation",):
            perm = ToolPermission.LOW_RISK_WRITE.value
            risk = "medium"
        if sid in ("authorized_security_test",):
            risk = "high"
        _spec(sid, "application_engineering" if "security" not in (caps or []) and "defense" not in (caps or []) else "cyber_defense", desc, fn, capabilities=caps, permission=perm, risk=risk)


def register_phase14_skills(registry: SkillRegistry2, *, activate: bool = True) -> dict[str, Any]:
    _bootstrap()
    registered = []
    skipped = []
    for definition, handler in PHASE14_SKILLS:
        result = registry.register(definition, handler, activate=activate)
        if result.get("ok"):
            registered.append(definition.skill_id)
            if activate:
                registry.mark_lkg(definition.skill_id, definition.version, approved=True, actor="phase14_bootstrap")
        else:
            skipped.append({"skill_id": definition.skill_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}


def phase14_status(*, full_tests: dict | None = None) -> dict[str, Any]:
    """Capability + gate status. PHASE_14_ALLOWED only when evaluate_phase14_gates passes."""
    from pfai.engineering.phase14_gates import evaluate_phase14_gates

    gates = evaluate_phase14_gates(full_tests=full_tests)
    gates["phase"] = 14
    gates["skill_metrics"] = SkillEvaluationLedger().summary()
    return gates
