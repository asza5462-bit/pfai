"""PHASE 17/18 Authorized Target Registry — versioned; DENY default; URL alone never authorizes."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.engineering.types import new_id


# Phase 17 types + Phase 18 aliases (normalized via normalize_target_type)
TARGET_TYPES = (
    # Phase 17
    "web_application",
    "API",
    "mobile_backend",
    "source_repository",
    "local_application",
    "staging_environment",
    "sandbox_environment",
    # Phase 18
    "web_app",
    "api",
    "mobile_app",
    "desktop_app",
    "repository",
    "local_project",
    "production_environment",
)

_TYPE_ALIASES = {
    "web_app": "web_application",
    "api": "API",
    "mobile_app": "mobile_backend",
    "repository": "source_repository",
    "local_project": "local_application",
}

AUTHORIZATION_STATUSES = ("DENIED", "PENDING", "AUTHORIZED", "EXPIRED", "REVOKED")


def normalize_target_type(target_type: str) -> str:
    t = (target_type or "").strip()
    return _TYPE_ALIASES.get(t, t)


@dataclass
class RegisteredTarget:
    target_id: str
    name: str
    target_type: str
    environment: str = "unknown"
    owner: str = ""
    authorization_status: str = "DENIED"
    authorization_scope: str = ""
    scope: str = ""  # Phase 18 alias of authorization_scope
    allowed_actions: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    testing_methods: list[str] = field(default_factory=list)
    rate_limits: dict[str, Any] = field(default_factory=lambda: {"per_minute": 20, "max_requests": 50})
    expiration: float = 0.0
    approval_reference: str = ""
    version: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""
    audit_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep scope synced for consumers
        d["scope"] = d.get("scope") or d.get("authorization_scope") or ""
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegisteredTarget":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        cleaned = {k: v for k, v in data.items() if k in known}
        if "scope" in cleaned and not cleaned.get("authorization_scope"):
            cleaned["authorization_scope"] = cleaned["scope"]
        if "authorization_scope" in cleaned and not cleaned.get("scope"):
            cleaned["scope"] = cleaned["authorization_scope"]
        if "allowed_actions" not in cleaned and cleaned.get("testing_methods"):
            cleaned["allowed_actions"] = list(cleaned["testing_methods"])
        cleaned.setdefault("version", 1)
        cleaned.setdefault("audit_metadata", {})
        cleaned.setdefault("allowed_actions", [])
        cleaned.setdefault("scope", "")
        return cls(**cleaned)


class TargetRegistry:
    """Secure versioned registry of explicitly authorized targets. Default DENY."""

    DEFAULT_STATUS = "DENIED"
    REGISTRY_SCHEMA_VERSION = 2

    def __init__(self, path: str = "data/longevity/engineering/target_registry.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.path.with_suffix(".audit.jsonl")
        self.history_path = self.path.with_name("target_registry_versions.jsonl")
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
            "schema_version": self.REGISTRY_SCHEMA_VERSION,
            "targets": [t.to_dict() for t in self._targets.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _version_history(self, target: RegisteredTarget, event: str, actor: str = "") -> None:
        row = {
            "ts": time.time(),
            "event": event,
            "target_id": target.target_id,
            "version": target.version,
            "authorization_status": target.authorization_status,
            "actor": actor,
        }
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def register(
        self,
        *,
        name: str,
        target_type: str,
        owner: str,
        environment: str = "staging",
        authorization_scope: str = "",
        scope: str = "",
        allowed_actions: list[str] | None = None,
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
        audit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Reject URL-as-authorization: name looking like URL does not grant auth
        normalized = normalize_target_type(target_type)
        if normalized not in TARGET_TYPES and target_type not in TARGET_TYPES:
            return {"ok": False, "error": "invalid_target_type", "allowed": list(TARGET_TYPES)}
        canonical = normalized if normalized in (
            "web_application", "API", "mobile_backend", "source_repository",
            "local_application", "staging_environment", "sandbox_environment",
            "desktop_app", "production_environment",
        ) else normalize_target_type(target_type)

        # Map aliases to stored canonical where possible
        store_type = normalize_target_type(target_type)
        if store_type not in TARGET_TYPES:
            store_type = target_type
        if store_type not in TARGET_TYPES:
            return {"ok": False, "error": "invalid_target_type", "allowed": list(TARGET_TYPES)}

        auth_scope = authorization_scope or scope
        methods = list(testing_methods or ["static_analysis", "security_headers", "passive_inspect"])
        actions = list(allowed_actions or methods)

        status = "AUTHORIZED" if authorize_now and approval_reference and auth_scope else "DENIED"
        if authorize_now and not (approval_reference and auth_scope and owner):
            return {
                "ok": False,
                "error": "authorization_requires_owner_scope_and_approval_reference",
                "authorization_status": "DENIED",
            }
        # Ambiguous authorization rejected
        if authorize_now and (not owner or owner.lower() in ("unknown", "anon", "anonymous")):
            return {"ok": False, "error": "ambiguous_authorization", "authorization_status": "DENIED"}

        now = time.time()
        target = RegisteredTarget(
            target_id=new_id("tgt"),
            name=name[:200],
            target_type=store_type,
            environment=environment,
            owner=owner,
            authorization_status=status,
            authorization_scope=auth_scope,
            scope=auth_scope,
            allowed_actions=actions,
            allowed_domains=[d.lower() for d in (allowed_domains or [])],
            allowed_hosts=[h.lower() for h in (allowed_hosts or [])],
            allowed_ports=list(allowed_ports or []),
            allowed_paths=list(allowed_paths or ["/"]),
            testing_methods=methods,
            rate_limits=dict(rate_limits or {"per_minute": 20, "max_requests": 50}),
            expiration=float(expiration or 0.0),
            approval_reference=approval_reference,
            version=1,
            created_at=now,
            updated_at=now,
            audit_metadata=sanitize_args(audit_metadata or {}),
        )
        with self._lock:
            self._targets[target.target_id] = target
            self._save()
            self._version_history(target, "register", actor=actor or owner)
        self._audit("register", target_id=target.target_id, status=status, actor=actor or owner, version=1)
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
        allowed_actions: list[str] | None = None,
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
            t.scope = authorization_scope
            if expiration is not None:
                t.expiration = float(expiration)
            if testing_methods is not None:
                t.testing_methods = list(testing_methods)
            if allowed_actions is not None:
                t.allowed_actions = list(allowed_actions)
            elif testing_methods is not None:
                t.allowed_actions = list(testing_methods)
            t.version = int(t.version or 1) + 1
            t.updated_at = time.time()
            self._save()
            self._version_history(t, "authorize", actor=actor)
        self._audit("authorize", target_id=target_id, actor=actor, version=t.version)
        return {"ok": True, "target": t.to_dict()}

    def revoke(self, target_id: str, *, actor: str = "") -> dict[str, Any]:
        with self._lock:
            t = self._targets.get(target_id)
            if not t:
                return {"ok": False, "error": "target_not_found"}
            t.authorization_status = "REVOKED"
            t.version = int(t.version or 1) + 1
            t.updated_at = time.time()
            self._save()
            self._version_history(t, "revoke", actor=actor)
        self._audit("revoke", target_id=target_id, actor=actor, version=t.version)
        return {"ok": True, "target": t.to_dict()}

    def get(self, target_id: str) -> dict[str, Any] | None:
        t = self._targets.get(target_id)
        return t.to_dict() if t else None

    def list_targets(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._targets.values()]

    def resolve(self, target_id: str = "", name: str = "") -> dict[str, Any]:
        """Resolve registered target only — never invent authorization from a URL."""
        if target_id:
            t = self.get(target_id)
            if not t:
                return {"ok": False, "error": "unknown_target"}
            return {"ok": True, "target": t}
        if name:
            # Name lookup must still be registered — URL-looking names do not auto-authorize
            for t in self._targets.values():
                if t.name == name:
                    return {"ok": True, "target": t.to_dict()}
            return {"ok": False, "error": "unregistered_target_or_domain"}
        return {"ok": False, "error": "target_id_or_name_required"}

    def refresh_expiration(self, target_id: str) -> dict[str, Any]:
        with self._lock:
            t = self._targets.get(target_id)
            if not t:
                return {"ok": False, "error": "target_not_found"}
            if t.expiration and time.time() > t.expiration and t.authorization_status == "AUTHORIZED":
                t.authorization_status = "EXPIRED"
                t.version = int(t.version or 1) + 1
                t.updated_at = time.time()
                self._save()
                self._audit("expired", target_id=target_id, version=t.version)
            return {"ok": True, "target": t.to_dict()}
