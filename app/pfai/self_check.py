"""Self-check and bounded self-heal (PHASE 2) — reversible, owner-gated."""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from pfai.interfaces.self_check import HealProposal, HealResult, SelfCheckReport

__all__ = ["SelfCheck", "SelfHeal", "HealProposal", "HealResult", "SelfCheckReport"]

PHASE = 7


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
    """Bounded heal: detect→diagnose→propose→apply_safe→test→rollback.

    Never auto-applies irreversible or high-risk changes.
    Does not mutate model weights, security settings, or core architecture.
    """

    def __init__(self, self_check: SelfCheck | None = None) -> None:
        self.self_check = self_check or SelfCheck()
        self._proposals: dict[str, HealProposal] = {}
        self._applied: dict[str, dict[str, Any]] = {}
        self._safe_actions: dict[str, Callable[[], dict[str, Any]]] = {}

    def register_safe_action(self, name: str, fn: Callable[[], dict[str, Any]]) -> None:
        self._safe_actions[name] = fn

    def propose_fix(self, report: SelfCheckReport) -> HealProposal:
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
                meta={"failures": []},
            )
            self._proposals[pid] = prop
            return prop
        # Only propose named safe actions — never code/weight/security mutation
        steps = []
        for f in failures:
            action = f"refresh_check:{f.get('name')}"
            if action not in self._safe_actions:
                # register a no-op re-check binder
                name = f.get("name")
                if name in self.self_check.checks:
                    self._safe_actions[action] = lambda n=name: self.self_check.checks[n]()
            steps.append(action)
        prop = HealProposal(
            proposal_id=pid,
            diagnosis=f"{len(failures)} failing check(s)",
            safe=True,
            reversible=True,
            steps=steps,
            risk="low",
            requires_owner=True,
            meta={"failures": failures, "forbidden": ["weight_mutation", "security_change", "code_rewrite"]},
        )
        self._proposals[pid] = prop
        return prop

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> HealResult:
        prop = self._proposals.get(proposal_id)
        if not prop:
            return HealResult(ok=False, proposal_id=proposal_id, message="unknown proposal")
        if prop.requires_owner and not approved:
            return HealResult(
                ok=False,
                proposal_id=proposal_id,
                message="owner approval required",
                meta={"needs_approval": True},
            )
        if not prop.safe or not prop.reversible:
            return HealResult(
                ok=False,
                proposal_id=proposal_id,
                message="refusing unsafe or irreversible heal",
            )
        results = []
        for step in prop.steps:
            fn = self._safe_actions.get(step)
            if not fn:
                return HealResult(ok=False, proposal_id=proposal_id, message=f"unknown safe action: {step}")
            results.append({"step": step, "result": fn()})
        self._applied[proposal_id] = {"results": results, "at": _now()}
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
        return HealResult(
            ok=ok,
            proposal_id=proposal_id,
            tested=True,
            message="recheck_passed" if ok else "recheck_failed",
            meta={"report": {"ok": report.ok, "summary": report.summary}},
        )

    def rollback_fix(self, proposal_id: str) -> HealResult:
        # Safe actions in PHASE 2 are re-checks only — rollback clears applied marker
        self._applied.pop(proposal_id, None)
        return HealResult(
            ok=True,
            proposal_id=proposal_id,
            rolled_back=True,
            message="heal state cleared (no irreversible mutation was performed)",
        )
