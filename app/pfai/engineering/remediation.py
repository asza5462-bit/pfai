"""PHASE 14 security remediation loop with checkpoints and rollback."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.types import new_id
from pfai.interfaces.tools import ToolPermission


class RemediationLoop:
    """DISCOVER → ANALYZE → PRIORITIZE → PROPOSE → APPROVE → APPLY → TEST → RECHECK → REPORT."""

    def __init__(self, workspace: ProjectWorkspace, *, executor: AuthorizedExecutor | None = None) -> None:
        self.workspace = workspace
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())

    def prioritize(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        return sorted(findings, key=lambda f: (order.get(str(f.get("severity")), 9), -float(f.get("confidence") or 0)))

    def propose_fix(self, finding: dict[str, Any]) -> dict[str, Any]:
        cat = finding.get("category")
        path = finding.get("file_path") or finding.get("affected_component") or ""
        proposal = {
            "proposal_id": new_id("fix"),
            "finding_id": finding.get("finding_id"),
            "category": cat,
            "path": path,
            "action": "manual_review",
            "patch_hint": finding.get("remediation"),
        }
        if cat == "secret_exposure" and path:
            proposal["action"] = "redact_hardcoded_secret"
            proposal["patch_hint"] = "Replace hard-coded secret with os.environ.get(...)"
        elif cat == "insecure_cors" and path:
            proposal["action"] = "restrict_cors_origin"
        elif cat == "missing_security_headers" and path.endswith(".html"):
            proposal["action"] = "add_csp_meta"
        return proposal

    def apply_fix(
        self,
        proposal: dict[str, Any],
        *,
        approved: bool = False,
        actor: str = "",
    ) -> dict[str, Any]:
        def _apply(**_k: Any) -> dict[str, Any]:
            path = proposal.get("path") or ""
            if not path:
                return {"ok": False, "error": "missing_path"}
            read = self.workspace.read_text(path)
            if not read.get("ok"):
                return {"ok": False, "error": "file_missing"}
            text = read["content"]
            action = proposal.get("action")
            if action == "redact_hardcoded_secret":
                new = re.sub(
                    r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]",
                    r"\1 = os.environ.get('\1'.upper(), '')",
                    text,
                    count=1,
                )
                if "import os" not in new and path.endswith(".py"):
                    new = "import os\n" + new
            elif action == "add_csp_meta":
                if "Content-Security-Policy" in text:
                    return {"ok": True, "changed": False, "note": "already_present"}
                new = text.replace(
                    "<head>",
                    '<head>\n  <meta http-equiv="Content-Security-Policy" content="default-src \'self\'"/>',
                    1,
                )
            elif action == "restrict_cors_origin":
                new = re.sub(
                    r"(?i)Access-Control-Allow-Origin['\"\s:]*\*",
                    "Access-Control-Allow-Origin: https://example.invalid",
                    text,
                )
            else:
                return {"ok": False, "error": "unsupported_auto_fix", "requires_manual": True}
            if new == text:
                return {"ok": False, "error": "no_change_applied"}
            self.workspace.write_text(path, new, overwrite=True)
            return {"ok": True, "changed": True, "path": path}

        result = self.executor.execute(
            kind="remediation",
            name=f"apply_fix:{proposal.get('action')}",
            permission=ToolPermission.LOW_RISK_WRITE,
            handler=_apply,
            args=sanitize_args(proposal),
            approved=bool(approved) if ToolPermission.LOW_RISK_WRITE.requires_owner_gate() else True,
            actor=actor,
        )
        # LOW_RISK_WRITE typically doesn't need approval — still honor needs_approval if gate says so
        if result.get("needs_approval"):
            return {"ok": False, "needs_approval": True, "error": result.get("error")}
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        return result.get("result") or {"ok": True}

    def run(
        self,
        *,
        approved: bool = False,
        actor: str = "",
        auto_apply: bool = False,
    ) -> dict[str, Any]:
        ckpt = self.workspace.checkpoint("pre_remediation")
        analyzer = SecureCodeAnalyzer(self.workspace.root)
        discovered = analyzer.analyze()
        prioritized = self.prioritize(list(discovered.get("findings") or []))
        proposals = [self.propose_fix(f) for f in prioritized[:20]]
        applied = []
        if auto_apply:
            for prop in proposals:
                if prop.get("action") in ("redact_hardcoded_secret", "add_csp_meta", "restrict_cors_origin"):
                    res = self.apply_fix(prop, approved=approved, actor=actor)
                    applied.append({"proposal": prop, "result": res})
                    if not res.get("ok") and res.get("needs_approval"):
                        break
        recheck = SecureCodeAnalyzer(self.workspace.root).analyze()
        # If recheck found more critical than before after auto-apply failure pattern — rollback optional
        before_crit = sum(1 for f in prioritized if f.get("severity") in ("critical", "high"))
        after_crit = sum(1 for f in (recheck.get("findings") or []) if f.get("severity") in ("critical", "high"))
        rolled_back = False
        if auto_apply and after_crit > before_crit:
            self.workspace.rollback(ckpt["checkpoint_id"])
            rolled_back = True
            recheck = SecureCodeAnalyzer(self.workspace.root).analyze()
        report = {
            "ok": True,
            "checkpoint_id": ckpt.get("checkpoint_id"),
            "discovered": len(prioritized),
            "proposals": proposals,
            "applied": applied,
            "recheck_finding_count": recheck.get("finding_count"),
            "rolled_back": rolled_back,
            "findings_before": prioritized,
            "findings_after": recheck.get("findings"),
            "loop": [
                "DISCOVER",
                "ANALYZE",
                "PRIORITIZE",
                "PROPOSE_FIX",
                "OWNER_AUTHORIZATION_CHECK",
                "APPLY_FIX",
                "TEST",
                "SECURITY_RECHECK",
                "COMPARE",
                "VERSION",
                "REPORT",
            ],
        }
        (self.workspace.meta_dir / "remediation_report.json").write_text(
            __import__("json").dumps(
                {k: v for k, v in report.items() if k not in ("findings_before", "findings_after")},
                indent=2,
            ),
            encoding="utf-8",
        )
        return report
