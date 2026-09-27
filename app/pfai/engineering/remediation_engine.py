"""PHASE 18 Remediation Engine — DETECT→…→AUDIT with authorization gates."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.phase18_security import Phase18SecurityAnalysis
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.security_regression import SecurityRegressionEngine
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id


# Categories considered safe for automatic remediation when explicitly configured
SAFE_AUTO_CATEGORIES = frozenset({"secret_exposure", "missing_security_headers", "insecure_cors"})
SENSITIVE_CATEGORIES = frozenset(
    {
        "auth_weakness",
        "access_control",
        "idor",
        "injection_risk",
        "ssrf_risk",
        "unsafe_crypto",
        "missing_api_authorization",
    }
)


class RemediationEngine:
    """
    DETECT → CLASSIFY → EXPLAIN → PROPOSE FIX → OWNER/AUTHORIZATION CHECK →
    APPLY FIX → TEST → SECURITY RECHECK → REGRESSION TEST → VERSION → AUDIT
    """

    VERSION = "18.0.0"
    PIPELINE = [
        "DETECT",
        "CLASSIFY",
        "EXPLAIN",
        "PROPOSE_FIX",
        "OWNER_AUTHORIZATION_CHECK",
        "APPLY_FIX",
        "TEST",
        "SECURITY_RECHECK",
        "REGRESSION_TEST",
        "VERSION",
        "AUDIT",
    ]

    def __init__(
        self,
        *,
        executor: AuthorizedExecutor | None = None,
        registry: TargetRegistry | None = None,
        audit_path: str = "data/longevity/engineering/remediation_engine_audit.jsonl",
        allow_auto_safe_fixes: bool = False,
    ) -> None:
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.registry = registry or TargetRegistry()
        self.scope = ScopeEnforcementLayer(registry=self.registry)
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.allow_auto_safe_fixes = bool(allow_auto_safe_fixes)
        self.analyzer = Phase18SecurityAnalysis()

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def run(
        self,
        project_path: str,
        *,
        approved: bool = False,
        actor: str = "",
        target_id: str = "",
        auto_apply: bool = False,
        owner_approved_sensitive: bool = False,
    ) -> dict[str, Any]:
        started = time.time()
        timeline: list[dict[str, Any]] = []

        if target_id:
            decision = self.scope.enforce(
                target_id=target_id,
                operation="remediation",
                method="static_analysis",
                actor=actor,
                approved=approved,
                resource=project_path,
            )
            if not decision.get("ok"):
                self._audit("denied", target_id=target_id, error=decision.get("error"), actor=actor)
                return {
                    "ok": False,
                    "denied": True,
                    "error": decision.get("error"),
                    "pipeline": self.PIPELINE,
                    "timeline": [{"event": "OWNER_AUTHORIZATION_CHECK", "ok": False}],
                }

        ws = ProjectWorkspace(project_path)
        ckpt = ws.checkpoint("pre_remediation_engine")

        # DETECT
        detected = self.analyzer.analyze(project_path)
        findings = list(detected.get("findings") or [])
        timeline.append({"event": "DETECT", "count": len(findings)})

        # CLASSIFY
        classified = []
        for f in findings:
            cat = f.get("category") or "unknown"
            classified.append(
                {
                    **f,
                    "class": (
                        "safe_auto"
                        if cat in SAFE_AUTO_CATEGORIES
                        else ("sensitive" if cat in SENSITIVE_CATEGORIES else "manual")
                    ),
                }
            )
        timeline.append({"event": "CLASSIFY", "safe_auto": sum(1 for c in classified if c["class"] == "safe_auto")})

        # EXPLAIN + PROPOSE (via existing loop helpers)
        loop = RemediationLoop(ws, executor=self.executor)
        prioritized = loop.prioritize(classified)
        proposals = []
        for f in prioritized[:20]:
            prop = loop.propose_fix(f)
            prop["class"] = f.get("class")
            prop["explanation"] = f.get("explanation")
            proposals.append(prop)
        timeline.append({"event": "EXPLAIN"})
        timeline.append({"event": "PROPOSE_FIX", "count": len(proposals)})

        # OWNER/AUTHORIZATION CHECK
        can_auto = bool(auto_apply and self.allow_auto_safe_fixes)
        timeline.append(
            {
                "event": "OWNER_AUTHORIZATION_CHECK",
                "approved": approved,
                "allow_auto_safe_fixes": self.allow_auto_safe_fixes,
                "owner_approved_sensitive": owner_approved_sensitive,
            }
        )

        applied = []
        skipped_sensitive = []
        if can_auto or (approved and auto_apply):
            for prop in proposals:
                cls = prop.get("class")
                if cls == "sensitive" and not owner_approved_sensitive:
                    skipped_sensitive.append(prop)
                    continue
                if cls == "safe_auto" and (can_auto or approved):
                    res = loop.apply_fix(prop, approved=approved or can_auto, actor=actor)
                    applied.append({"proposal": prop, "result": res})
                elif cls != "safe_auto" and approved and owner_approved_sensitive:
                    res = loop.apply_fix(prop, approved=True, actor=actor)
                    applied.append({"proposal": prop, "result": res})
                elif cls == "manual":
                    skipped_sensitive.append(prop)
        timeline.append({"event": "APPLY_FIX", "applied": len(applied), "skipped": len(skipped_sensitive)})

        # TEST + SECURITY RECHECK
        recheck = self.analyzer.analyze(project_path)
        timeline.append({"event": "SECURITY_RECHECK", "findings": recheck.get("finding_count")})

        regression = SecurityRegressionEngine(project_path).run_regressions()
        timeline.append({"event": "REGRESSION_TEST", "ok": regression.get("ok")})

        # Rollback if critical findings increased
        before_crit = sum(1 for f in prioritized if f.get("severity") in ("critical", "high"))
        after_crit = sum(1 for f in (recheck.get("findings") or []) if f.get("severity") in ("critical", "high"))
        rolled_back = False
        if applied and after_crit > before_crit:
            ws.rollback(ckpt["checkpoint_id"])
            rolled_back = True
            recheck = self.analyzer.analyze(project_path)
            timeline.append({"event": "ROLLBACK", "checkpoint_id": ckpt.get("checkpoint_id")})

        version = {
            "remediation_version": 1,
            "engine_version": self.VERSION,
            "artifact_id": new_id("rem"),
        }
        timeline.append({"event": "VERSION", **version})

        report = {
            "ok": True,
            "pipeline": self.PIPELINE,
            "timeline": timeline,
            "checkpoint_id": ckpt.get("checkpoint_id"),
            "detected": len(prioritized),
            "proposals": proposals,
            "applied": applied,
            "skipped_sensitive": skipped_sensitive,
            "requires_owner_approval_for_sensitive": True,
            "recheck_finding_count": recheck.get("finding_count"),
            "regression": regression,
            "rolled_back": rolled_back,
            "version": version,
            "claim_100_percent_secure": False,
            "duration_seconds": time.time() - started,
            "phase": 18,
        }
        self._audit(
            "remediation_complete",
            artifact_id=version["artifact_id"],
            applied=len(applied),
            rolled_back=rolled_back,
            actor=actor,
            target_id=target_id,
        )
        timeline.append({"event": "AUDIT"})
        report["timeline"] = timeline
        (ws.meta_dir / "remediation_engine_report.json").write_text(
            json.dumps(
                {k: v for k, v in report.items() if k not in ("proposals",)},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return report
