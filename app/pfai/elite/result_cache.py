"""PHASE 21 safe result cache — never stores secrets; version-aware keys; TTL + invalidation."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from pfai.authorized_execution import sanitize_args


_SECRET_MARKERS = (
    "password",
    "otp",
    "api_key",
    "apikey",
    "secret",
    "token",
    "credential",
    "authorization",
    "private_key",
    "session",
)


class ResultCache:
    VERSION = "21.0.0"

    def __init__(self, *, default_ttl_seconds: float = 60.0, max_entries: int = 512) -> None:
        self.default_ttl = float(default_ttl_seconds)
        self.max_entries = int(max_entries)
        self._lock = threading.RLock()
        self._store: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.rejects = 0

    def _contains_secret(self, payload: Any) -> bool:
        blob = json.dumps(payload, default=str).lower()
        return any(m in blob for m in _SECRET_MARKERS)

    def make_key(
        self,
        *,
        namespace: str,
        payload: dict[str, Any],
        model_version: str = "",
        skill_version: str = "",
        knowledge_version: str = "",
        cache_version: str = "1",
    ) -> str:
        material = {
            "ns": namespace,
            "payload": sanitize_args(payload),
            "model_version": model_version,
            "skill_version": skill_version,
            "knowledge_version": knowledge_version,
            "cache_version": cache_version,
        }
        raw = json.dumps(material, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._store.get(key)
            if not row:
                self.misses += 1
                return None
            if row["expires_at"] < time.time():
                self._store.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return dict(row["value"])

    def put(self, key: str, value: dict[str, Any], *, ttl_seconds: float | None = None) -> dict[str, Any]:
        safe = sanitize_args(value)
        if self._contains_secret(safe):
            self.rejects += 1
            return {"ok": False, "error": "secret_blocked"}
        # Never cache auth material / private owner data markers
        if any(k in safe for k in ("password", "otp", "owner_credentials", "session_secret")):
            self.rejects += 1
            return {"ok": False, "error": "auth_material_blocked"}
        ttl = self.default_ttl if ttl_seconds is None else float(ttl_seconds)
        with self._lock:
            if len(self._store) >= self.max_entries:
                # Evict oldest
                oldest = sorted(self._store.items(), key=lambda kv: kv[1]["created_at"])[: max(1, self.max_entries // 10)]
                for k, _ in oldest:
                    self._store.pop(k, None)
            self._store[key] = {
                "value": safe,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
                "stale_override_forbidden": True,
            }
        return {"ok": True, "cached": True, "ttl": ttl}

    def invalidate(self, key: str | None = None, *, namespace_prefix: str = "") -> int:
        with self._lock:
            if key:
                return 1 if self._store.pop(key, None) else 0
            if namespace_prefix:
                # Keys are hashes — namespace invalidation via full clear of matching tag unsupported; clear all
                n = len(self._store)
                self._store.clear()
                return n
            n = len(self._store)
            self._store.clear()
            return n

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "rejects": self.rejects,
                "default_ttl": self.default_ttl,
                "max_entries": self.max_entries,
                "never_caches_secrets": True,
            }
