"""PHASE 15 Unified Coding Workflow — understand → plan → edit → test → repair → report."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.application_builder import ApplicationBuilder
from pfai.engineering.engineering_workflow import EngineeringWorkflow
from pfai.engineering.project_inspector import ProjectInspector
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.security_regression import SecurityRegressionEngine
from pfai.engineering.skill_metrics import SkillEvaluationLedger
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.types import new_id
from pfai.interfaces.tools import ToolPermission


class UnifiedCodingWorkflow:
    """
    Connects ModelRouter / SkillFabric / ToolFabric / Sandbox / ApplicationEngineering
    via AuthorizedExecutor. Bounded: no silent unrelated edits; no unauthorized testing.
    """

    def __init__(
        self,
        root: str | None = None,
        *,
        executor: AuthorizedExecutor | None = None,
        experience_bridge: Any = None,
        skill_metrics: SkillEvaluationLedger | None = None,
    ) -> None:
        self.base = Path(root or tempfile.mkdtemp(prefix="pfai-coding-"))
        self.base.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.experience_bridge = experience_bridge
        self.skill_metrics = skill_metrics or SkillEvaluationLedger(
            path=str(self.base / "skill_evaluations.jsonl")
        )
        self.builder = ApplicationBuilder(root=str(self.base / "generated"), executor=self.executor)

    def handle(
        self,
        message: str,
        *,
        project_path: str = "",
        approved: bool = False,
        actor: str = "",
        declaration: str = "",
        scope: str = "",
        allow_external: bool = False,
        auto_apply: bool = False,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        ctx = dict(context or {})
        timeline: list[dict[str, Any]] = []
        intent = self._detect_intent(message, project_path=project_path or ctx.get("project_path", ""))
        timeline.append({"event": "understand", "intent": intent})

        result: dict[str, Any]
        if intent == "build":
            result = self._build(message, approved=approved, actor=actor, timeline=timeline)
        elif intent == "inspect":
            path = project_path or str(ctx.get("project_path") or "")
            result = self._inspect(path, timeline=timeline)
        elif intent == "security_review":
            path = project_path or str(ctx.get("project_path") or "")
            result = self._security_review(
                path,
                message=message,
                approved=approved,
                actor=actor,
                declaration=declaration or str(ctx.get("declaration") or ""),
                scope=scope or str(ctx.get("scope") or ""),
                allow_external=allow_external or bool(ctx.get("allow_external")),
                timeline=timeline,
            )
        elif intent == "remediate":
            path = project_path or str(ctx.get("project_path") or "")
            result = self._remediate(
                path, approved=approved, actor=actor, auto_apply=auto_apply, timeline=timeline
            )
        elif intent == "modify":
            path = project_path or str(ctx.get("project_path") or "")
            result = self._modify(
                path,
                message=message,
                approved=approved,
                actor=actor,
                writers=ctx.get("writers") or {},
                affected_files=list(ctx.get("affected_files") or []),
                timeline=timeline,
            )
        elif intent == "debug_test":
            path = project_path or str(ctx.get("project_path") or "")
            result = self._debug_test(path, timeline=timeline)
        else:
            result = {
                "ok": True,
                "intent": intent,
                "plan": [
                    "Clarify requirements",
                    "Inspect or create project",
                    "Implement with tests",
                    "Security review",
                    "Validate",
                ],
                "note": "general_engineering_guidance",
            }
            timeline.append({"event": "plan", "plan": result["plan"]})

        duration = time.time() - started
        self.skill_metrics.record(
            skill_id=f"unified_coding:{intent}",
            success=bool(result.get("ok")),
            validation_ok=result.get("complete") if "complete" in result else result.get("ok"),
            security_findings=int(result.get("finding_count") or 0),
            user_approved=approved or None,
            duration_seconds=duration,
        )
        self._maybe_learn(result, intent=intent, actor=actor)
        return {
            **result,
            "intent": intent,
            "timeline": timeline,
            "duration_seconds": duration,
            "workflow_id": new_id("ucw"),
            "phase": 15,
            "deployment_claimed": False,
        }

    def _detect_intent(self, message: str, *, project_path: str = "") -> str:
        t = (message or "").lower()
        if any(
            w in t
            for w in (
                "build me a website",
                "build a website",
                "create a full-stack",
                "full-stack application",
                "build an api",
                "create an application",
                "build a web application",
                "build me an app",
            )
        ):
            return "build"
        if any(
            w in t
            for w in (
                "fix the vulnerabilit",
                "remediat",
                "apply fix",
                "fix security",
                "run the tests again",
            )
        ):
            return "remediate"
        if any(
            w in t
            for w in (
                "security review",
                "security problems",
                "security weaknesses",
                "vulnerabilit",
                "secure code",
                "authorized test",
                "for security",
                "application for security",
                "analyze this api",
            )
        ):
            return "security_review"
        if any(w in t for w in ("inspect project", "analyze architecture", "repository inspection", "project structure")):
            return "inspect"
        if any(w in t for w in ("refactor", "modify", "edit the", "update the code", "change the")):
            return "modify"
        if any(w in t for w in ("debug", "run tests", "fix failing", "diagnose")):
            return "debug_test"
        if project_path and "review" in t:
            return "inspect"
        return "general"

    def _build(self, message: str, *, approved: bool, actor: str, timeline: list) -> dict[str, Any]:
        timeline.append({"event": "plan", "steps": ["specify", "materialize", "test", "security_review"]})
        out = self.builder.build(message, approved=approved, actor=actor, run_tests=True, security_review=True)
        timeline.append({"event": "build", "ok": out.get("ok"), "complete": out.get("complete")})
        if out.get("complete") and out.get("artifact"):
            root = (out["artifact"] or {}).get("root")
            if root:
                sec = SecureCodeAnalyzer(root).analyze()
                timeline.append({"event": "security_review", "findings": sec.get("finding_count")})
                out["post_build_security"] = {"finding_count": sec.get("finding_count")}
        out["deployment_claimed"] = False
        return out

    def _inspect(self, path: str, *, timeline: list) -> dict[str, Any]:
        if not path:
            return {"ok": False, "error": "project_path_required"}
        timeline.append({"event": "inspect", "path": path})
        return ProjectInspector(path).inspect()

    def _security_review(
        self,
        path: str,
        *,
        message: str,
        approved: bool,
        actor: str,
        declaration: str,
        scope: str,
        allow_external: bool,
        timeline: list,
    ) -> dict[str, Any]:
        # Authorization first for non-local / when no local path
        if not path:
            from pfai.engineering.authorized_testing import AuthorizedSecurityTester

            gate = TargetAuthorizationGate(path=str(self.base / "target_auth.jsonl"))
            tester = AuthorizedSecurityTester(gate=gate, audit_path=str(self.base / "auth_test.jsonl"))
            timeline.append({"event": "authorization_check"})
            out = tester.run(
                message,
                declaration=declaration,
                scope=scope or "headers_only",
                approved=approved,
                actor=actor,
                allow_external=allow_external,
            )
            timeline.append({"event": "authorized_testing", "denied": out.get("denied"), "ok": out.get("ok")})
            return out

        # Local project: static analysis first
        timeline.append({"event": "authorization_check", "mode": "local_project"})
        analysis = SecureCodeAnalyzer(path).analyze()
        timeline.append({"event": "security_analysis", "findings": analysis.get("finding_count")})
        findings = []
        for f in analysis.get("findings") or []:
            findings.append(
                {
                    **f,
                    "remediation_status": f.get("remediation_status") or "open",
                    "verification_status": f.get("verification_status") or "open",
                }
            )
        return {
            "ok": True,
            "project": path,
            "finding_count": len(findings),
            "findings": findings,
            "fabricated": False,
            "authorization": "local_static_analysis",
        }

    def _remediate(
        self,
        path: str,
        *,
        approved: bool,
        actor: str,
        auto_apply: bool,
        timeline: list,
    ) -> dict[str, Any]:
        if not path:
            return {"ok": False, "error": "project_path_required"}
        from pfai.engineering.project_workspace import ProjectWorkspace

        ws = ProjectWorkspace(path)
        timeline.append({"event": "remediation_start"})
        loop = RemediationLoop(ws, executor=self.executor)
        report = loop.run(approved=approved, actor=actor, auto_apply=auto_apply)
        timeline.append({"event": "remediation", "rolled_back": report.get("rolled_back")})

        # VERIFY each applied finding; mark fixed only when verification succeeds
        engine = SecurityRegressionEngine(path)
        verifications = []
        for item in report.get("applied") or []:
            prop = item.get("proposal") or {}
            finding = {"finding_id": prop.get("finding_id"), "category": prop.get("category"), "file_path": prop.get("path")}
            # locate original finding
            for f in report.get("findings_before") or []:
                if f.get("finding_id") == prop.get("finding_id"):
                    finding = f
                    break
            v = engine.verify_finding_fixed(finding)
            verifications.append(v)
            if v.get("verified") and item.get("result", {}).get("ok"):
                gen = engine.generate_from_finding({**finding, "verified": True, "marked_fixed": True})
                verifications[-1]["regression"] = gen
        reg_run = engine.run_regressions()
        timeline.append({"event": "security_retest", "verifications": len(verifications)})
        timeline.append({"event": "regression", "passed": reg_run.get("passed")})
        report["verifications"] = verifications
        report["regression"] = reg_run
        # Do not claim fixed without verification
        report["fixed_count"] = sum(1 for v in verifications if v.get("marked_fixed"))
        report["unverified_count"] = sum(1 for v in verifications if not v.get("verified"))
        return report

    def _modify(
        self,
        path: str,
        *,
        message: str,
        approved: bool,
        actor: str,
        writers: dict[str, str],
        affected_files: list[str],
        timeline: list,
    ) -> dict[str, Any]:
        if not path:
            return {"ok": False, "error": "project_path_required"}
        if not affected_files or not writers:
            return {
                "ok": False,
                "error": "explicit_affected_files_and_writers_required",
                "note": "refuses_silent_unrelated_modification",
            }
        wf = EngineeringWorkflow(path, executor=self.executor)
        plan = wf.plan_modification(reason=message[:500], affected_files=affected_files)
        timeline.append({"event": "plan", "plan_id": (plan.get("plan") or {}).get("plan_id")})
        if not plan.get("ok"):
            return plan
        out = wf.apply_plan(plan["plan"], writers, approved=approved, actor=actor, run_tests=True)
        timeline.append({"event": "edit", "ok": out.get("ok"), "rolled_back": out.get("rolled_back")})
        return out

    def _debug_test(self, path: str, *, timeline: list) -> dict[str, Any]:
        if not path:
            return {"ok": False, "error": "project_path_required"}
        wf = EngineeringWorkflow(path, executor=self.executor)
        timeline.append({"event": "diagnose"})
        tests = wf._run_tests()
        timeline.append({"event": "test", "ok": tests.get("ok"), "ran": tests.get("ran")})
        return {"ok": bool(tests.get("ok") or tests.get("ran") is False), "tests": tests, "inspection": wf.inspect()}

    def _maybe_learn(self, result: dict[str, Any], *, intent: str, actor: str) -> None:
        if self.experience_bridge is None:
            return
        # Only validated outcomes — never secrets / never policy mutation
        if not result.get("ok"):
            return
        payload = sanitize_args(
            {
                "kind": "phase15_engineering",
                "intent": intent,
                "actor": actor,
                "complete": result.get("complete"),
                "finding_count": result.get("finding_count"),
                "fixed_count": result.get("fixed_count"),
                "validated": True,
            }
        )
        try:
            if hasattr(self.experience_bridge, "record_experience"):
                self.experience_bridge.record_experience(payload)
            elif hasattr(self.experience_bridge, "add"):
                self.experience_bridge.add(payload)
        except Exception:
            return
