"""Self-check and bounded self-heal (PHASE 4) — reversible, owner-gated, audited.

Loop: detect → diagnose → propose → owner approval → apply_safe → test → rollback.
Never mutates model weights, security settings, core architecture, or arbitrary files/code.
Only explicitly registered safe actions may run.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.self_check import HealProposal, HealResult, SelfCheckReport
from pfai.interfaces.tools import ToolPermission
from pfai.authorized_execution import AuthorizationAudit

__all__ = ["SelfCheck", "SelfHeal", "HealProposal", "HealResult", "SelfCheckReport"]

PHASE = 7  # longevity self-check lane; platform orchestration is PHASE 4

FORBIDDEN_SAFE_ACTION_PATTERNS = (
    "weight",
    "fine_tune",
    "train",
    "security_policy",
    "modify_security",
    "rewrite_architecture",
    "arbitrary_code",
    "write_code",
    "exec_shell",
    "read_secret",
    "secret",
    "bypass_auth",
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class SelfCheck:
    """Runs injectable health checks (runtime/health, compat, eval smoke)."""

    def __init__(self, checks: dict[str, Callable[[], dict[str, Any]]] | None = None) -> None:
        self.checks = dict(checks or {})

    def add_check(self, name: str, fn: Callable[[], dict[str, Any]]) -> None:
        self.checks[name] = fn

    def run_checks(self) -> SelfCheckReport:
        results = []
        ok = True
        for name, fn in self.checks.items():
            try:
                detail = fn() or {}
                passed = bool(detail.get("ok", True))
            except Exception as exc:
                passed = False
                detail = {"ok": False, "error": str(exc)}
            results.append({"name": name, "ok": passed, "detail": detail})
            ok = ok and passed
        return SelfCheckReport(
            ok=ok,
            checks=results,
            summary="all_passed" if ok else "failures_detected",
            meta={"at": _now(), "phase": PHASE},
        )


class SelfHeal:
    """Bounded heal with durable audit. Only registered safe actions."""

    def __init__(
        self,
        self_check: SelfCheck | None = None,
        *,
        audit_path: str = "data/longevity/heal_audit.jsonl",
        authz_audit: AuthorizationAudit | None = None,
    ) -> None:
        self.self_check = self_check or SelfCheck()
        self._proposals: dict[str, HealProposal] = {}
        self._applied: dict[str, dict[str, Any]] = {}
        self._safe_actions: dict[str, Callable[[], dict[str, Any]]] = {}
        self._rollback_actions: dict[str, Callable[[], dict[str, Any]]] = {}
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.authz_audit = authz_audit
        self._lock = threading.RLock()

    def _audit(self, event: str, **payload: Any) -> None:
        row = {"ts": _now(), "event": event, **payload}
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def _is_forbidden_name(self, name: str) -> bool:
        n = (name or "").lower()
        return any(p in n for p in FORBIDDEN_SAFE_ACTION_PATTERNS)

    def register_safe_action(
        self,
        name: str,
        fn: Callable[[], dict[str, Any]],
        *,
        rollback: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if self._is_forbidden_name(name):
            raise ValueError(f"refusing to register forbidden heal action: {name}")
        self._safe_actions[name] = fn
        if rollback is not None:
            self._rollback_actions[name] = rollback

    def propose_fix(self, report: SelfCheckReport) -> HealProposal:
        self._audit("detect", summary=report.summary, ok=report.ok)
        failures = [c for c in report.checks if not c.get("ok")]
        pid = uuid.uuid4().hex[:12]
        if not failures:
            prop = HealProposal(
                proposal_id=pid,
                diagnosis="healthy",
                safe=True,
                reversible=True,
                steps=[],
                risk="low",
                requires_owner=False,
                meta={"failures": [], "phase": "diagnose"},
            )
            self._proposals[pid] = prop
            self._audit("propose", proposal_id=pid, diagnosis="healthy")
            return prop

        steps = []
        for f in failures:
            action = f"refresh_check:{f.get('name')}"
            if self._is_forbidden_name(action):
                continue
            if action not in self._safe_actions:
                name = f.get("name")
                if name in self.self_check.checks:
                    self._safe_actions[action] = lambda n=name: {"ok": True, **(self.self_check.checks[n]() or {})}
            if action in self._safe_actions:
                steps.append(action)

        # Optional named safe recoveries if registered
        for candidate in ("clear_transient_cache", "rerun_eval_smoke", "compat_recheck"):
            if candidate in self._safe_actions and candidate not in steps:
                steps.append(candidate)

        prop = HealProposal(
            proposal_id=pid,
            diagnosis=f"{len(failures)} failing check(s)",
            safe=True,
            reversible=True,
            steps=steps,
            risk="low",
            requires_owner=True,
            meta={
                "failures": failures,
                "forbidden": [
                    "weight_mutation",
                    "security_change",
                    "code_rewrite",
                    "secret_read",
                    "arbitrary_file_write",
                ],
                "phase": "diagnose",
            },
        )
        self._proposals[pid] = prop
        self._audit("propose", proposal_id=pid, diagnosis=prop.diagnosis, steps=steps)
        return prop

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> HealResult:
        prop = self._proposals.get(proposal_id)
        if not prop:
            return HealResult(ok=False, proposal_id=proposal_id, message="unknown proposal")
        if prop.requires_owner and not approved:
            if self.authz_audit:
                self.authz_audit.record(
                    kind="heal",
                    name=proposal_id,
                    permission=ToolPermission.HIGH_RISK_WRITE,
                    allowed=False,
                    approved=False,
                    reason="owner approval required",
                )
            self._audit("deny_apply", proposal_id=proposal_id, reason="owner approval required")
            return HealResult(
                ok=False,
                proposal_id=proposal_id,
                message="owner approval required",
                meta={"needs_approval": True},
            )
        if not prop.safe or not prop.reversible:
            self._audit("deny_apply", proposal_id=proposal_id, reason="unsafe/irreversible")
            return HealResult(
                ok=False,
                proposal_id=proposal_id,
                message="refusing unsafe or irreversible heal",
            )
        results = []
        for step in prop.steps:
            if self._is_forbidden_name(step):
                self._audit("deny_step", proposal_id=proposal_id, step=step, reason="forbidden")
                return HealResult(ok=False, proposal_id=proposal_id, message=f"forbidden heal action: {step}")
            fn = self._safe_actions.get(step)
            if not fn:
                return HealResult(ok=False, proposal_id=proposal_id, message=f"unknown safe action: {step}")
            results.append({"step": step, "result": fn()})
        self._applied[proposal_id] = {"results": results, "at": _now(), "steps": list(prop.steps)}
        if self.authz_audit:
            self.authz_audit.record(
                kind="heal",
                name=proposal_id,
                permission=ToolPermission.HIGH_RISK_WRITE,
                allowed=True,
                approved=True,
                reason="safe heal applied",
            )
        self._audit("apply_safe", proposal_id=proposal_id, results=results)
        return HealResult(
            ok=True,
            proposal_id=proposal_id,
            applied=True,
            message="safe actions applied",
            meta={"results": results},
        )

    def test_fix(self, proposal_id: str) -> HealResult:
        report = self.self_check.run_checks()
        ok = report.ok
        self._audit("test", proposal_id=proposal_id, ok=ok, summary=report.summary)
        return HealResult(
            ok=ok,
            proposal_id=proposal_id,
            tested=True,
            message="recheck_passed" if ok else "recheck_failed",
            meta={"report": {"ok": report.ok, "summary": report.summary}},
        )

    def rollback_fix(self, proposal_id: str) -> HealResult:
        applied = self._applied.pop(proposal_id, None)
        rollback_results = []
        if applied:
            for step in reversed(list(applied.get("steps") or [])):
                fn = self._rollback_actions.get(step)
                if fn:
                    rollback_results.append({"step": step, "result": fn()})
        self._audit("rollback", proposal_id=proposal_id, results=rollback_results)
        return HealResult(
            ok=True,
            proposal_id=proposal_id,
            rolled_back=True,
            message="heal rolled back (no irreversible mutation retained)",
            meta={"rollback_results": rollback_results},
        )
