"""PHASE 17 Authorized Target Registry — DENY default; URL alone is never authorization."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.engineering.types import new_id


TARGET_TYPES = (
    "web_application",
    "API",
    "mobile_backend",
    "source_repository",
    "local_application",
    "staging_environment",
    "sandbox_environment",
)

AUTHORIZATION_STATUSES = ("DENIED", "PENDING", "AUTHORIZED", "EXPIRED", "REVOKED")


@dataclass
class RegisteredTarget:
    target_id: str
    name: str
    target_type: str
    environment: str = "unknown"
    owner: str = ""
    authorization_status: str = "DENIED"
    authorization_scope: str = ""
    allowed_domains: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    testing_methods: list[str] = field(default_factory=list)
    rate_limits: dict[str, Any] = field(default_factory=lambda: {"per_minute": 20, "max_requests": 50})
    expiration: float = 0.0
    approval_reference: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegisteredTarget":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class TargetRegistry:
    """Secure registry of explicitly authorized targets. Default DENY."""

    DEFAULT_STATUS = "DENIED"

    def __init__(self, path: str = "data/longevity/engineering/target_registry.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.path.with_suffix(".audit.jsonl")
        self._lock = threading.RLock()
        self._targets: dict[str, RegisteredTarget] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("targets") or []:
            try:
                t = RegisteredTarget.from_dict(row)
                self._targets[t.target_id] = t
            except Exception:
                continue

    def _save(self) -> None:
        payload = {
            "updated_at": time.time(),
            "default": self.DEFAULT_STATUS,
            "targets": [t.to_dict() for t in self._targets.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def register(
        self,
        *,
        name: str,
        target_type: str,
        owner: str,
        environment: str = "staging",
        authorization_scope: str = "",
        allowed_domains: list[str] | None = None,
        allowed_hosts: list[str] | None = None,
        allowed_ports: list[int] | None = None,
        allowed_paths: list[str] | None = None,
        testing_methods: list[str] | None = None,
        rate_limits: dict[str, Any] | None = None,
        expiration: float = 0.0,
        approval_reference: str = "",
        authorize_now: bool = False,
        actor: str = "",
    ) -> dict[str, Any]:
        if target_type not in TARGET_TYPES:
            return {"ok": False, "error": "invalid_target_type", "allowed": list(TARGET_TYPES)}
        # Never authorize solely because a URL/name was provided
        status = "AUTHORIZED" if authorize_now and approval_reference and authorization_scope else "DENIED"
        if authorize_now and not (approval_reference and authorization_scope and owner):
            return {
                "ok": False,
                "error": "authorization_requires_owner_scope_and_approval_reference",
                "authorization_status": "DENIED",
            }
        now = time.time()
        target = RegisteredTarget(
            target_id=new_id("tgt"),
            name=name[:200],
            target_type=target_type,
            environment=environment,
            owner=owner,
            authorization_status=status,
            authorization_scope=authorization_scope,
            allowed_domains=[d.lower() for d in (allowed_domains or [])],
            allowed_hosts=[h.lower() for h in (allowed_hosts or [])],
            allowed_ports=list(allowed_ports or []),
            allowed_paths=list(allowed_paths or ["/"]),
            testing_methods=list(testing_methods or ["static_analysis", "security_headers", "passive_inspect"]),
            rate_limits=dict(rate_limits or {"per_minute": 20, "max_requests": 50}),
            expiration=float(expiration or 0.0),
            approval_reference=approval_reference,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._targets[target.target_id] = target
            self._save()
        self._audit("register", target_id=target.target_id, status=status, actor=actor or owner)
        return {"ok": True, "target": target.to_dict()}

    def authorize(
        self,
        target_id: str,
        *,
        approval_reference: str,
        authorization_scope: str,
        actor: str,
        expiration: float | None = None,
        testing_methods: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            t = self._targets.get(target_id)
            if not t:
                return {"ok": False, "error": "target_not_found"}
            if not approval_reference or not authorization_scope or not actor:
                return {"ok": False, "error": "approval_reference_scope_and_actor_required", "authorization_status": "DENIED"}
            t.authorization_status = "AUTHORIZED"
            t.approval_reference = approval_reference
            t.authorization_scope = authorization_scope
            if expiration is not None:
                t.expiration = float(expiration)
            if testing_methods is not None:
                t.testing_methods = list(testing_methods)
            t.updated_at = time.time()
            self._save()
        self._audit("authorize", target_id=target_id, actor=actor)
        return {"ok": True, "target": t.to_dict()}

    def revoke(self, target_id: str, *, actor: str = "") -> dict[str, Any]:
        with self._lock:
            t = self._targets.get(target_id)
            if not t:
                return {"ok": False, "error": "target_not_found"}
            t.authorization_status = "REVOKED"
            t.updated_at = time.time()
            self._save()
        self._audit("revoke", target_id=target_id, actor=actor)
        return {"ok": True, "target": t.to_dict()}

    def get(self, target_id: str) -> dict[str, Any] | None:
        t = self._targets.get(target_id)
        return t.to_dict() if t else None

    def list_targets(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._targets.values()]

    def refresh_expiration(self, target_id: str) -> dict[str, Any]:
        with self._lock:
            t = self._targets.get(target_id)
            if not t:
                return {"ok": False, "error": "target_not_found"}
            if t.expiration and time.time() > t.expiration and t.authorization_status == "AUTHORIZED":
                t.authorization_status = "EXPIRED"
                t.updated_at = time.time()
                self._save()
                self._audit("expired", target_id=target_id)
            return {"ok": True, "target": t.to_dict()}
