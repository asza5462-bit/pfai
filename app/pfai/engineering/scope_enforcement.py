"""PHASE 17 Scope Enforcement Layer — fail closed; client claims never authorize."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id
from pfai.interfaces.tools import ToolPermission


DESTRUCTIVE_METHODS = frozenset(
    {
        "destructive_exploit",
        "credential_theft",
        "persistence",
        "malware",
        "ransomware",
        "unrestricted_scan",
        "stealth",
        "evasion",
        "dos",
        "data_destruction",
    }
)


class ScopeEnforcementLayer:
    """
    Owner/AuthZ → Target Authorization → Scope Validation → Tool Permission →
    Sandbox → Audit → Execution

    Fail closed. Client-side role/admin/owner fields are ignored.
    """

    def __init__(
        self,
        registry: TargetRegistry | None = None,
        gate: TargetAuthorizationGate | None = None,
        *,
        executor: AuthorizedExecutor | None = None,
        audit_path: str = "data/longevity/engineering/scope_enforcement_audit.jsonl",
    ) -> None:
        self.registry = registry or TargetRegistry()
        self.gate = gate or TargetAuthorizationGate()
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._request_counts: dict[str, list[float]] = {}

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, "audit_id": new_id("scaud"), **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def enforce(
        self,
        *,
        target_id: str = "",
        operation: str,
        method: str,
        actor: str,
        approved: bool = False,
        resource: str = "",
        client_claims: dict[str, Any] | None = None,
        tool_permission: ToolPermission = ToolPermission.READ,
    ) -> dict[str, Any]:
        # Explicitly ignore client privilege claims
        claims = dict(client_claims or {})
        ignored = {k: claims.get(k) for k in ("role", "admin", "owner", "permission", "authorization") if k in claims}
        if ignored:
            self._audit("client_claims_ignored", ignored_keys=list(ignored.keys()), actor=actor)

        if method.lower() in DESTRUCTIVE_METHODS or operation.lower() in DESTRUCTIVE_METHODS:
            self._audit("deny_destructive", method=method, operation=operation, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "destructive_or_offensive_method_forbidden"}

        if not target_id:
            # Fall back to legacy gate for ad-hoc local/declaration flows
            legacy = self.gate.require_authorized(
                resource or operation,
                declaration=str(claims.get("declaration") or ""),
                scope=str(claims.get("scope") or ""),
                approved=approved,
                actor=actor,
                allow_external=bool(claims.get("allow_external")),
            )
            self._audit("legacy_gate", decision=legacy.get("decision"), ok=legacy.get("ok"), actor=actor)
            if not legacy.get("ok"):
                return {"ok": False, "decision": legacy.get("decision") or "DENY", "error": legacy.get("error"), "layer": "legacy_gate"}
            return {"ok": True, "decision": "ALLOW", "layer": "legacy_gate", "auth": legacy}

        refreshed = self.registry.refresh_expiration(target_id)
        target = (refreshed.get("target") if refreshed.get("ok") else None) or self.registry.get(target_id)
        if not target:
            self._audit("deny_unknown_target", target_id=target_id, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "unauthorized_target"}

        status = target.get("authorization_status") or "DENIED"
        if status in ("DENIED", "PENDING", "REVOKED"):
            self._audit("deny_status", target_id=target_id, status=status, actor=actor)
            return {"ok": False, "decision": "DENY", "error": f"authorization_status_{status.lower()}"}
        if status == "EXPIRED":
            self._audit("deny_expired", target_id=target_id, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "expired_authorization"}
        if status != "AUTHORIZED":
            return {"ok": False, "decision": "DENY", "error": "authorization_not_established"}

        exp = float(target.get("expiration") or 0)
        if exp and time.time() > exp:
            self.registry.refresh_expiration(target_id)
            return {"ok": False, "decision": "DENY", "error": "expired_authorization"}

        allowed_methods = [m.lower() for m in (target.get("testing_methods") or [])]
        if method.lower() not in allowed_methods and operation.lower() not in allowed_methods:
            self._audit("deny_method", method=method, allowed=allowed_methods, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "forbidden_testing_method"}

        # Scope validation for URL resources
        if resource and "://" in resource:
            parsed = urlparse(resource)
            host = (parsed.hostname or "").lower()
            domain = host
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            allowed_hosts = [h.lower() for h in (target.get("allowed_hosts") or [])]
            allowed_domains = [d.lower() for d in (target.get("allowed_domains") or [])]
            allowed_ports = [int(p) for p in (target.get("allowed_ports") or [])]
            allowed_paths = target.get("allowed_paths") or ["/"]

            if allowed_hosts and host not in allowed_hosts:
                self._audit("deny_host", host=host, actor=actor)
                return {"ok": False, "decision": "DENY", "error": "target_outside_allowed_host"}
            if allowed_domains and not any(host == d or host.endswith("." + d) for d in allowed_domains):
                self._audit("deny_domain", host=host, actor=actor)
                return {"ok": False, "decision": "DENY", "error": "target_outside_allowed_domain"}
            if allowed_ports and port not in allowed_ports:
                self._audit("deny_port", port=port, actor=actor)
                return {"ok": False, "decision": "DENY", "error": "target_outside_allowed_port"}
            if allowed_paths and not any(path == ap or path.startswith(ap.rstrip("*")) for ap in allowed_paths):
                # allow exact or prefix; '*' suffix means prefix
                ok_path = False
                for ap in allowed_paths:
                    if ap.endswith("*"):
                        if path.startswith(ap[:-1]):
                            ok_path = True
                            break
                    elif path == ap or path.startswith(ap.rstrip("/") + "/") or ap == "/":
                        ok_path = True
                        break
                if not ok_path:
                    self._audit("deny_path", path=path, actor=actor)
                    return {"ok": False, "decision": "DENY", "error": "target_outside_allowed_path"}

        # Rate limits
        limits = target.get("rate_limits") or {}
        per_min = int(limits.get("per_minute") or 20)
        key = target_id
        now = time.time()
        stamps = [t for t in self._request_counts.get(key, []) if now - t < 60]
        if len(stamps) >= per_min:
            self._audit("deny_rate", target_id=target_id, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "excessive_rate"}
        stamps.append(now)
        self._request_counts[key] = stamps

        # Tool permission gate — high risk needs approval
        if tool_permission.requires_owner_gate() and not approved:
            self._audit("deny_tool_permission", permission=tool_permission.value, actor=actor)
            return {"ok": False, "decision": "DENY", "error": "owner_approval_required", "needs_approval": True}

        decision = {
            "ok": True,
            "decision": "ALLOW",
            "target_id": target_id,
            "operation": operation,
            "method": method,
            "actor": actor,
            "scope": target.get("authorization_scope"),
            "rate_limits": limits,
            "sandbox_required": True,
            "client_claims_trusted": False,
        }
        self._audit("allow", **decision)
        return decision
