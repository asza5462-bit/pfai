"""PHASE 14 TargetAuthorizationGate — DENY by default for active external testing."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.types import TargetAuthDecision, TargetScope, new_id, now_ts
from pfai.interfaces.tools import ToolPermission


_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.|0\.0\.0\.0|\[::1\])",
    re.I,
)


class TargetAuthorizationGate:
    """No authorization declaration + approval = DENY active external testing."""

    DEFAULT = TargetAuthDecision.DENY.value

    def __init__(
        self,
        path: str = "data/longevity/engineering/target_authorizations.jsonl",
        *,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def classify_target(self, target: str) -> dict[str, Any]:
        t = (target or "").strip()
        if not t:
            return {"ok": False, "error": "empty_target", "local": False, "external": False}
        # Local filesystem path
        if t.startswith("/") or t.startswith(".") or t.startswith("~") or "://" not in t:
            p = Path(t).expanduser()
            return {
                "ok": True,
                "kind": "local_path",
                "local": True,
                "external": False,
                "path": str(p),
            }
        parsed = urlparse(t)
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "scheme_not_allowed", "local": False, "external": True}
        host = (parsed.hostname or "").lower()
        localish = bool(_PRIVATE_HOST_RE.match(host or "")) or host in ("localhost",)
        return {
            "ok": True,
            "kind": "url",
            "local": localish,
            "external": not localish,
            "host": host,
            "url": t,
        }

    def authorize(self, scope: TargetScope) -> dict[str, Any]:
        """Authorize a target scope. Default DENY."""
        if not scope.declaration or not scope.scope:
            decision = TargetAuthDecision.DENY.value
            self._audit("deny", reason="missing_declaration_or_scope", target_id=scope.target_id)
            return {
                "ok": False,
                "decision": decision,
                "error": "authorization_declaration_and_scope_required",
            }
        if not scope.approved:
            decision = TargetAuthDecision.NEEDS_APPROVAL.value
            self._audit("needs_approval", target_id=scope.target_id, actor=scope.actor)
            return {
                "ok": False,
                "decision": decision,
                "error": "owner_approval_required",
                "needs_approval": True,
            }
        # High-risk: external targets require explicit allow_external + approved
        if scope.allow_external and not scope.local_only:
            # Must go through AuthorizedExecutor SECRETS/PRODUCTION style gate
            result = self.executor.execute(
                kind="security_target",
                name="authorize_external_target",
                permission=ToolPermission.HIGH_RISK_WRITE,
                handler=lambda **_: {"authorized": True, "target_id": scope.target_id},
                args={"target_id": scope.target_id, "domains": scope.domains},
                approved=True,
                actor=scope.actor or "owner",
            )
            if not result.get("ok"):
                self._audit("deny_external", target_id=scope.target_id, error=result.get("error"))
                return {
                    "ok": False,
                    "decision": TargetAuthDecision.DENY.value,
                    "error": result.get("error") or "external_authorization_failed",
                }
        scope.created_at = scope.created_at or now_ts()
        self._audit(
            "allow",
            target_id=scope.target_id,
            scope=scope.scope,
            allowed_actions=scope.allowed_actions,
            local_only=scope.local_only,
            allow_external=scope.allow_external,
            actor=scope.actor,
        )
        return {
            "ok": True,
            "decision": TargetAuthDecision.ALLOW.value,
            "scope": scope.to_dict(),
            "rate_limit_per_minute": scope.rate_limit_per_minute,
            "max_requests": scope.max_requests,
            "timeout_seconds": scope.timeout_seconds,
        }

    def require_authorized(
        self,
        target: str,
        *,
        declaration: str,
        scope: str,
        allowed_actions: list[str] | None = None,
        approved: bool = False,
        actor: str = "",
        allow_external: bool = False,
    ) -> dict[str, Any]:
        classified = self.classify_target(target)
        if not classified.get("ok"):
            return {"ok": False, "decision": TargetAuthDecision.DENY.value, "error": classified.get("error")}
        if classified.get("external") and not allow_external:
            self._audit("deny", reason="external_without_allow_external", target=target)
            return {
                "ok": False,
                "decision": TargetAuthDecision.DENY.value,
                "error": "external_target_requires_explicit_allow_external_and_approval",
            }
        ts = TargetScope(
            target_id=new_id("tgt"),
            declaration=declaration,
            scope=scope,
            allowed_actions=list(allowed_actions or ["passive_inspect"]),
            approved=bool(approved),
            actor=actor,
            local_only=bool(classified.get("local")),
            allow_external=bool(allow_external and classified.get("external")),
            domains=[classified.get("host")] if classified.get("host") else [],
            paths=[classified.get("path")] if classified.get("path") else [],
        )
        auth = self.authorize(ts)
        auth["classification"] = classified
        return auth
