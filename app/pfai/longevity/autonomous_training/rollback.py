"""Model rollback to last-known-good."""
from __future__ import annotations

import time
from typing import Any

from .model_registry import ModelRegistry
from .types import ModelStatus


class ModelRollbackManager:
    def __init__(self, registry: ModelRegistry, audit_fn=None) -> None:
        self.registry = registry
        self.audit_fn = audit_fn

    def last_known_good(self, slot: str = "default") -> dict[str, Any] | None:
        active = self.registry.active(slot)
        if not active:
            return None
        prev = active.get("previous_model_id")
        if prev:
            return self.registry.get(prev)
        # Fall back to most recent VALIDATED non-active model
        for m in self.registry.list_models(limit=20):
            if m["model_id"] != active.get("model_id") and m.get("status") in (
                ModelStatus.VALIDATED.value,
                ModelStatus.ROLLED_BACK.value,
            ):
                return self.registry.get(m["model_id"])
        return None

    def rollback(self, *, slot: str = "default", reason: str = "regression") -> dict[str, Any]:
        active = self.registry.active(slot)
        target = self.last_known_good(slot)
        if not target:
            return {"ok": False, "error": "no_last_known_good", "reason": reason}
        target_id = target["model_id"]
        # Activate previous; current becomes ROLLED_BACK
        if active:
            self.registry.update_status(active["model_id"], ModelStatus.ROLLED_BACK)
        result = self.registry.activate(target_id, slot=slot)
        payload = {
            "ok": True,
            "rolled_back_from": active.get("model_id") if active else None,
            "restored_model_id": target_id,
            "reason": reason,
            "at": time.time(),
            "active": result,
        }
        if self.audit_fn:
            self.audit_fn("model_rollback", **{k: v for k, v in payload.items() if k != "active"})
            # keep active summary compact
            if payload.get("active"):
                self.audit_fn(
                    "model_rollback_active",
                    restored_model_id=payload.get("restored_model_id"),
                    rolled_back_from=payload.get("rolled_back_from"),
                )
        return payload
