"""PHASE 18 unified chat fabric — Arabic/English engineering & security routes; never bypasses registry."""
from __future__ import annotations

import time
from typing import Any

from pfai.engineering.application_engineering import ApplicationEngineering
from pfai.engineering.coding_agent_bridge import CodingAgentBridge
from pfai.engineering.engineering_metrics import EngineeringMetrics
from pfai.engineering.phase18_security import Phase18SecurityAnalysis
from pfai.engineering.remediation_engine import RemediationEngine
from pfai.engineering.authorized_web_ops import AuthorizedWebFabricOps
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    t = text or ""
    tl = t.lower()
    for n in needles:
        if n.lower() in tl or n in t:
            return True
    return False


class Phase18ChatFabric:
    """
    Routes unified chat intents for Phase 18 without bypassing TargetRegistry / AuthorizationGate.

    Examples:
    - ابنِ لي موقعاً... → build pipeline
    - افحص موقعي... → registered target security analysis
    - أصلح هذه الثغرة... → authorized remediation
    - طوّر التطبيق... → inspect → plan → implement → test → version
    """

    VERSION = "18.0.0"

    BUILD_HINTS = (
        "build me a website",
        "build a website",
        "create an application",
        "build an api",
        "build a web application",
        "full-stack",
        "ابن",
        "ابنِ",
        "ابني",
        "موقعا",
        "موقع",
        "تطبيق",
    )
    INSPECT_SITE_HINTS = (
        "افحص",
        "افحص موقعي",
        "check my site",
        "scan my site",
        "inspect my website",
        "security assessment of my",
    )
    FIX_HINTS = (
        "أصلح",
        "اصلح",
        "fix this vulnerabilit",
        "fix the vulnerabilit",
        "remediat",
        "apply the fix",
    )
    IMPROVE_HINTS = (
        "طوّر",
        "طور",
        "improve the app",
        "develop the application",
        "enhance the application",
        "refactor the application",
    )

    def __init__(
        self,
        *,
        registry: TargetRegistry | None = None,
        metrics: EngineeringMetrics | None = None,
        root: str | None = None,
    ) -> None:
        self.registry = registry or TargetRegistry()
        self.metrics = metrics or EngineeringMetrics()
        self.engineering = ApplicationEngineering(root=root)
        self.coding = CodingAgentBridge(registry=self.registry)
        self.security = Phase18SecurityAnalysis()
        self.remediation = RemediationEngine(registry=self.registry, allow_auto_safe_fixes=False)
        self.web_ops = AuthorizedWebFabricOps(registry=self.registry)

    def detect_intent(self, message: str) -> str:
        if _contains_any(message, self.FIX_HINTS):
            return "remediate"
        if _contains_any(message, self.INSPECT_SITE_HINTS):
            return "inspect_site"
        if _contains_any(message, self.IMPROVE_HINTS):
            return "improve"
        if _contains_any(message, self.BUILD_HINTS):
            return "build"
        return "general"

    def handle(
        self,
        message: str,
        *,
        approved: bool = False,
        actor: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        ctx = dict(context or {})
        intent = self.detect_intent(message)
        target_id = str(ctx.get("target_id") or "")
        project_path = str(ctx.get("project_path") or ctx.get("path") or "")

        # Hard rule: chat never authorizes from URL alone
        url = str(ctx.get("url") or "")
        if url and not target_id and intent in ("inspect_site", "remediate"):
            self.metrics.record_auth_failure(reason="url_alone", actor=actor)
            return {
                "ok": False,
                "denied": True,
                "intent": intent,
                "error": "unregistered_target_or_domain",
                "note": "URL_alone_never_authorizes_use_TargetRegistry",
                "workflow_id": new_id("p18chat"),
                "phase": 18,
            }

        if intent == "build":
            out = self.engineering.build(message, approved=approved, actor=actor, run_tests=True, security_review=True)
            self.metrics.record_task(name="build", duration_seconds=time.time() - started, success=bool(out.get("complete")))
            return {**out, "intent": intent, "workflow_id": new_id("p18chat"), "phase": 18}

        if intent == "inspect_site":
            if not target_id and not project_path:
                return {
                    "ok": False,
                    "denied": True,
                    "intent": intent,
                    "error": "registered_target_or_project_path_required",
                    "phase": 18,
                }
            if target_id:
                resolved = self.registry.resolve(target_id=target_id)
                if not resolved.get("ok"):
                    self.metrics.record_auth_failure(reason="unknown_target", actor=actor)
                    return {"ok": False, "denied": True, "error": "unknown_target", "intent": intent, "phase": 18}
                target = resolved["target"]
                if target.get("authorization_status") != "AUTHORIZED":
                    self.metrics.record_auth_failure(reason="not_authorized", actor=actor)
                    return {
                        "ok": False,
                        "denied": True,
                        "error": f"authorization_status_{target.get('authorization_status', 'DENIED').lower()}",
                        "intent": intent,
                        "phase": 18,
                    }
            analysis = self.security.analyze(project_path) if project_path else {"ok": True, "findings": [], "finding_count": 0}
            plan = {
                "steps": [
                    "verify_registered_target",
                    "verify_authorization",
                    "security_analysis",
                    "bounded_testing",
                    "findings",
                    "remediation_plan",
                ],
                "claim_100_percent_secure": False,
            }
            self.metrics.record("security_analysis_duration", time.time() - started, intent=intent)
            return {
                "ok": True,
                "intent": intent,
                "analysis": analysis,
                "finding_count": analysis.get("finding_count"),
                "findings": analysis.get("findings"),
                "plan": plan,
                "target_id": target_id,
                "workflow_id": new_id("p18chat"),
                "phase": 18,
            }

        if intent == "remediate":
            if not project_path:
                return {"ok": False, "error": "project_path_required", "intent": intent, "phase": 18}
            out = self.remediation.run(
                project_path,
                approved=approved,
                actor=actor,
                target_id=target_id,
                auto_apply=bool(ctx.get("auto_apply")),
                owner_approved_sensitive=bool(ctx.get("owner_approved_sensitive")),
            )
            self.metrics.record(
                "remediation_success",
                1.0 if out.get("ok") and not out.get("denied") else 0.0,
                intent=intent,
            )
            return {**out, "intent": intent, "workflow_id": new_id("p18chat"), "phase": 18}

        if intent == "improve":
            if not project_path:
                return {"ok": False, "error": "project_path_required", "intent": intent, "phase": 18}
            insp = self.coding.inspect_repository(project_path, target_id=target_id, actor=actor, approved=approved)
            if insp.get("denied"):
                return {**insp, "intent": intent, "phase": 18}
            plan = ["inspect", "plan", "implement", "test", "evaluate", "version"]
            writers = dict(ctx.get("writers") or {})
            mod: dict[str, Any] = {"ok": True, "note": "plan_only_until_writers_provided"}
            if writers:
                mod = self.coding.apply_modification(
                    project_path,
                    writers=writers,
                    reason=str(ctx.get("reason") or message[:200]),
                    approved=approved,
                    actor=actor,
                    target_id=target_id,
                )
            return {
                "ok": bool(mod.get("ok")),
                "intent": intent,
                "inspection": insp,
                "plan": plan,
                "modification": mod,
                "workflow_id": new_id("p18chat"),
                "phase": 18,
            }

        return {
            "ok": True,
            "intent": "general",
            "plan": ["Clarify requirements", "Register targets if needed", "Build or analyze under authorization"],
            "note": "phase18_general_guidance",
            "WEB_FABRIC_STATUS": self.web_ops.status().get("WEB_FABRIC_STATUS"),
            "workflow_id": new_id("p18chat"),
            "phase": 18,
        }
