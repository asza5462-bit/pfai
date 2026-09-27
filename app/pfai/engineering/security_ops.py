"""PHASE 17 Security operations — SDLC, reporting, remediation orchestration, monitoring."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.application_builder import ApplicationBuilder
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.security_regression import SecurityRegressionEngine
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id
from pfai.engineering.web_security_engine import WebApplicationSecurityEngine
from pfai.elite.sandbox import Sandbox
from pfai.interfaces.tools import ToolPermission


SDLC_STAGES = (
    "REQUIREMENTS",
    "ARCHITECTURE",
    "IMPLEMENTATION",
    "UNIT_TESTS",
    "SECURITY_ANALYSIS",
    "AUTHORIZED_TESTING",
    "REMEDIATION",
    "REGRESSION_TESTS",
    "SECURITY_RETEST",
    "QUALITY_GATE",
    "VERSION",
)


class SecurityReportBuilder:
    """Professional evidence-based security reports — never claims 100% secure."""

    def build(
        self,
        *,
        title: str,
        scope: dict[str, Any],
        authorization: dict[str, Any],
        methodology: list[str],
        findings: list[dict[str, Any]],
        remediation: dict[str, Any] | None = None,
        retest: dict[str, Any] | None = None,
        regression: dict[str, Any] | None = None,
        limitations: list[str] | None = None,
        audit_trail: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        findings = list(findings or [])
        # sanitize dict fields only — lists of findings sanitized element-wise
        safe_findings = [sanitize_args(f) if isinstance(f, dict) else f for f in findings]
        safe_audit = [sanitize_args(a) if isinstance(a, dict) else a for a in (audit_trail or [])]
        sev_counts: dict[str, int] = {}
        for f in safe_findings:
            if not isinstance(f, dict):
                continue
            s = str(f.get("severity") or "info")
            sev_counts[s] = sev_counts.get(s, 0) + 1
        report_id = new_id("srep")
        executive = (
            f"Assessment '{title}' identified {len(safe_findings)} evidence-backed finding(s). "
            f"Severity counts: {sev_counts or {'none': 0}}. "
            "This report does not claim the system is fully secure."
        )
        doc = {
            "report_id": report_id,
            "title": title,
            "generated_at": time.time(),
            "executive_summary": executive,
            "scope": sanitize_args(scope) if isinstance(scope, dict) else {},
            "authorization": sanitize_args(authorization) if isinstance(authorization, dict) else {},
            "methodology": methodology,
            "findings": safe_findings,
            "severity_counts": sev_counts,
            "risk": "Residual risk remains; prioritize critical/high findings.",
            "remediation": sanitize_args(remediation or {}) if isinstance(remediation, dict) else {},
            "retest_results": sanitize_args(retest or {}) if isinstance(retest, dict) else {},
            "regression_results": sanitize_args(regression or {}) if isinstance(regression, dict) else {},
            "remaining_risks": [
                "Unverified attack surface outside scope",
                "Zero-days / logic flaws not covered by static patterns",
                "Configuration drift after assessment",
            ],
            "limitations": limitations
            or [
                "Static and bounded tests only",
                "No destructive exploitation performed",
                "Not a certification of complete security",
            ],
            "audit_trail": safe_audit,
            "claim_100_percent_secure": False,
        }
        return {"ok": True, "report": doc}


class SecurityDevelopmentLifecycle:
    """REQUIREMENTS → … → VERSION; security-ready only after gate."""

    def __init__(
        self,
        *,
        scope: ScopeEnforcementLayer | None = None,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.scope = scope or ScopeEnforcementLayer()
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.engine = WebApplicationSecurityEngine()
        self.reports = SecurityReportBuilder()

    def run_for_project(
        self,
        requirement: str,
        *,
        project_path: str = "",
        approved: bool = False,
        actor: str = "",
        target_id: str = "",
        auto_remediate: bool = False,
    ) -> dict[str, Any]:
        timeline: list[dict[str, Any]] = []
        stages_hit: list[str] = []

        def hit(stage: str, **d: Any) -> None:
            stages_hit.append(stage)
            timeline.append({"stage": stage, "ts": time.time(), **sanitize_args(d)})

        hit("REQUIREMENTS", requirement=requirement[:300])
        hit("ARCHITECTURE", note="detect_kind_via_ApplicationBuilder")

        root = project_path
        build_out = None
        if not root:
            builder = ApplicationBuilder(executor=self.executor)
            build_out = builder.build(requirement, approved=approved, actor=actor, run_tests=True, security_review=False)
            hit("IMPLEMENTATION", complete=build_out.get("complete"), ok=build_out.get("ok"))
            if not build_out.get("complete"):
                return {
                    "ok": False,
                    "security_ready": False,
                    "error": "implementation_incomplete",
                    "build": build_out,
                    "stages": stages_hit,
                    "timeline": timeline,
                }
            root = (build_out.get("artifact") or {}).get("root") or ""
            hit("UNIT_TESTS", tests_ok=(build_out.get("artifact") or {}).get("validation", {}).get("tests_ok"))
        else:
            hit("IMPLEMENTATION", existing_project=root)
            hit("UNIT_TESTS", note="existing_project_tests_deferred_to_caller")

        # Scope for security analysis — local path uses legacy/local allow with declaration
        enf = self.scope.enforce(
            target_id=target_id,
            operation="security_analysis",
            method="static_analysis",
            actor=actor or "system",
            approved=approved or bool(root),
            resource=root,
            client_claims={"declaration": "owner local project", "scope": "static_analysis"} if not target_id else {},
            tool_permission=ToolPermission.READ,
        )
        if not enf.get("ok") and target_id:
            hit("SECURITY_ANALYSIS", denied=True, error=enf.get("error"))
            return {
                "ok": False,
                "security_ready": False,
                "error": enf.get("error"),
                "stages": stages_hit,
                "timeline": timeline,
            }

        analysis = self.engine.analyze_source(root)
        hit("SECURITY_ANALYSIS", finding_count=analysis.get("finding_count"))
        hit("AUTHORIZED_TESTING", mode="static_first", note="active external tests require registry auth")

        rem_report = None
        regression = None
        retest = None
        if auto_remediate and analysis.get("finding_count"):
            ws = ProjectWorkspace(root)
            rem_report = RemediationLoop(ws, executor=self.executor).run(
                approved=approved, actor=actor, auto_apply=True
            )
            hit("REMEDIATION", fixed_count=rem_report.get("fixed_count"), rolled_back=rem_report.get("rolled_back"))
            eng = SecurityRegressionEngine(root)
            for v in rem_report.get("verifications") or []:
                if v.get("marked_fixed"):
                    finding = {
                        "finding_id": v.get("finding_id"),
                        "category": v.get("category"),
                        "file_path": v.get("affected_component"),
                        "verified": True,
                        "marked_fixed": True,
                    }
                    eng.generate_from_finding(finding)
            regression = eng.run_regressions()
            hit("REGRESSION_TESTS", passed=regression.get("passed"))
            retest = self.engine.analyze_source(root)
            hit("SECURITY_RETEST", finding_count=retest.get("finding_count"))
        else:
            hit("REMEDIATION", skipped=not auto_remediate)
            hit("REGRESSION_TESTS", skipped=True)
            hit("SECURITY_RETEST", skipped=True)
            retest = analysis

        remaining = int((retest or analysis).get("finding_count") or 0)
        # Security-ready requires: implementation complete, tests ok (when built), critical/high cleared
        highs = [
            f
            for f in ((retest or analysis).get("findings") or [])
            if f.get("severity") in ("critical", "high")
        ]
        tests_ok = True
        if build_out:
            tests_ok = bool((build_out.get("artifact") or {}).get("validation", {}).get("tests_ok"))
        security_ready = tests_ok and len(highs) == 0 and (build_out is None or bool(build_out.get("complete")))
        hit(
            "QUALITY_GATE",
            security_ready=security_ready,
            high_remaining=len(highs),
            note="compiles_alone_insufficient",
        )
        version_id = new_id("sdlc")
        hit("VERSION", version_id=version_id)

        report = self.reports.build(
            title=f"SDLC Security — {requirement[:80]}",
            scope={"project": root, "target_id": target_id or None},
            authorization=enf,
            methodology=list(SDLC_STAGES),
            findings=(retest or analysis).get("findings") or [],
            remediation=rem_report,
            retest=retest,
            regression=regression,
            audit_trail=timeline,
        )

        # Persist report under project if possible
        if root:
            try:
                ws = ProjectWorkspace(root)
                ws.write_text(
                    ".pfai/security_report.json",
                    json.dumps(report.get("report"), indent=2),
                    overwrite=True,
                )
            except Exception:
                pass

        return {
            "ok": True,
            "security_ready": security_ready,
            "version_id": version_id,
            "project": root,
            "stages": stages_hit,
            "pipeline": list(SDLC_STAGES),
            "analysis": {"finding_count": analysis.get("finding_count")},
            "retest": {"finding_count": (retest or {}).get("finding_count")},
            "remediation": rem_report,
            "regression": regression,
            "report": report.get("report"),
            "timeline": timeline,
            "sandbox": Sandbox(timeout=1.0).metadata().get("SANDBOX_STATUS"),
            "claim_100_percent_secure": False,
        }


class DefensiveMonitoringFramework:
    """Optional monitoring for authorized registered targets — no arbitrary Internet scanning."""

    def __init__(self, registry: TargetRegistry | None = None, path: str = "data/longevity/engineering/security_monitor.jsonl") -> None:
        self.registry = registry or TargetRegistry()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def check_project_drift(self, project_path: str, *, baseline_finding_count: int | None = None) -> dict[str, Any]:
        engine = WebApplicationSecurityEngine()
        current = engine.analyze_source(project_path)
        drift = None
        if baseline_finding_count is not None:
            drift = int(current.get("finding_count") or 0) - int(baseline_finding_count)
        row = {
            "ts": time.time(),
            "event": "project_drift_check",
            "project": project_path,
            "finding_count": current.get("finding_count"),
            "drift": drift,
            "arbitrary_internet_scan": False,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return {"ok": True, **row, "findings_preview": (current.get("findings") or [])[:5]}

    def check_registered_target(self, target_id: str, *, actor: str, scope: ScopeEnforcementLayer | None = None) -> dict[str, Any]:
        layer = scope or ScopeEnforcementLayer(registry=self.registry)
        enf = layer.enforce(
            target_id=target_id,
            operation="monitoring",
            method="passive_inspect",
            actor=actor,
            approved=True,
            tool_permission=ToolPermission.READ,
        )
        if not enf.get("ok"):
            return {"ok": False, "error": enf.get("error"), "decision": "DENY"}
        target = self.registry.get(target_id)
        row = {
            "ts": time.time(),
            "event": "authorized_monitor",
            "target_id": target_id,
            "scope_respected": True,
            "checks": [
                "configuration_drift",
                "dependency_changes",
                "security_regression",
                "auth_behavior_change",
            ],
            "note": "framework_ready_bounded; active probes require allowed methods",
            "target_type": (target or {}).get("target_type"),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(sanitize_args(row)) + "\n")
        return {"ok": True, **row}
