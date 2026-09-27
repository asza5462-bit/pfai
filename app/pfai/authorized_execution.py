"""Unified ActionPermissionGate + AuthorizedExecutor (PHASE 4).

Distinct from legacy ``pfai.permission_gate.PermissionGate`` (escalation ledger).
Server-side only. Never trusts client role/admin/owner flags.
HIGH_RISK_WRITE and above always require explicit owner approval.
Every allow/deny is audited (no secrets in audit payloads).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.tools import ToolPermission

PHASE = 4

SENSITIVE_KEYS = (
    "secret",
    "passcode",
    "password",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "hash",
)


def risk_to_permission(risk: str, *, name: str = "", requires_approval: bool = False) -> ToolPermission:
    """Map legacy ToolRouter risk strings onto ToolPermission."""
    r = (risk or "read").strip().lower()
    n = (name or "").strip().lower()
    if any(x in n for x in ("secret", "credential", "passcode")):
        return ToolPermission.SECRETS
    if any(x in n for x in ("forget", "delete", "purge")):
        return ToolPermission.DATA_DELETE
    if any(x in n for x in ("deploy", "promote", "rollback_prod", "production")):
        return ToolPermission.PRODUCTION
    if r in ("sensitive", "high", "production"):
        return ToolPermission.HIGH_RISK_WRITE
    if r == "write":
        return ToolPermission.HIGH_RISK_WRITE if requires_approval else ToolPermission.LOW_RISK_WRITE
    return ToolPermission.READ


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sanitize_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Redact secret-like keys from audit/export payloads."""
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        lk = str(k).lower()
        if any(s in lk for s in SENSITIVE_KEYS):
            out[k] = "[redacted]"
        elif isinstance(v, dict):
            out[k] = sanitize_args(v)
        else:
            out[k] = v
    return out


@dataclass
class AuthDecision:
    allowed: bool
    permission: ToolPermission
    needs_approval: bool = False
    reason: str = ""
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class ActionPermissionGate:
    """Decide whether a tool/skill/planner action may run given ToolPermission + approval."""

    def decide(self, permission: ToolPermission | str, *, approved: bool = False) -> AuthDecision:
        perm = permission if isinstance(permission, ToolPermission) else ToolPermission(str(permission))
        if perm.requires_owner_gate() and not approved:
            return AuthDecision(
                allowed=False,
                permission=perm,
                needs_approval=True,
                reason="owner approval required for high-risk action",
            )
        return AuthDecision(allowed=True, permission=perm, reason="allowed")


# Backward-friendly alias used inside PHASE 4 modules (not the legacy ledger gate).
PermissionGate = ActionPermissionGate


class AuthorizationAudit:
    """Append-only allow/deny audit. Never stores secrets."""

    def __init__(self, path: str = "data/longevity/authz_audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record(
        self,
        *,
        kind: str,
        name: str,
        permission: ToolPermission | str,
        allowed: bool,
        approved: bool,
        actor: str = "",
        reason: str = "",
        decision_id: str = "",
        args: dict[str, Any] | None = None,
    ) -> None:
        perm = permission.value if isinstance(permission, ToolPermission) else str(permission)
        row = {
            "ts": _now(),
            "decision_id": decision_id or uuid.uuid4().hex[:12],
            "kind": kind,
            "name": name,
            "permission": perm,
            "allowed": bool(allowed),
            "approved": bool(approved),
            "actor": actor or "",
            "reason": reason or "",
            "args": sanitize_args(args),
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


class AuthorizedExecutor:
    """Single execution choke-point for tools, skills, and planner steps."""

    def __init__(
        self,
        gate: ActionPermissionGate | None = None,
        audit: AuthorizationAudit | None = None,
    ) -> None:
        self.gate = gate or ActionPermissionGate()
        self.audit = audit or AuthorizationAudit()

    def execute(
        self,
        *,
        kind: str,
        name: str,
        permission: ToolPermission | str,
        handler: Callable[..., Any],
        args: dict[str, Any] | None = None,
        approved: bool = False,
        actor: str = "",
    ) -> dict[str, Any]:
        decision = self.gate.decide(permission, approved=approved)
        self.audit.record(
            kind=kind,
            name=name,
            permission=decision.permission,
            allowed=decision.allowed,
            approved=approved,
            actor=actor,
            reason=decision.reason,
            decision_id=decision.decision_id,
            args=args,
        )
        if not decision.allowed:
            return {
                "ok": False,
                "needs_approval": decision.needs_approval,
                "error": decision.reason,
                "permission": decision.permission.value,
                "decision_id": decision.decision_id,
                "kind": kind,
                "name": name,
            }
        try:
            result = handler(**(args or {}))
            return {
                "ok": True,
                "result": result,
                "permission": decision.permission.value,
                "decision_id": decision.decision_id,
                "kind": kind,
                "name": name,
            }
        except TypeError:
            try:
                result = handler()
                return {
                    "ok": True,
                    "result": result,
                    "permission": decision.permission.value,
                    "decision_id": decision.decision_id,
                    "kind": kind,
                    "name": name,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "permission": decision.permission.value,
                    "decision_id": decision.decision_id,
                    "kind": kind,
                    "name": name,
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "permission": decision.permission.value,
                "decision_id": decision.decision_id,
                "kind": kind,
                "name": name,
            }
