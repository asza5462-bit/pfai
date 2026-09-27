"""Model rollback to last-known-good — updates registry AND active runtime pointer."""
from __future__ import annotations

import time
from typing import Any

from .active_runtime import ActiveModelRuntime
from .checkpoints import CheckpointStore
from .model_registry import ModelRegistry
from .types import ModelStatus


class ModelRollbackManager:
    def __init__(
        self,
        registry: ModelRegistry,
        audit_fn=None,
        active_runtime: ActiveModelRuntime | None = None,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        self.registry = registry
        self.audit_fn = audit_fn
        self.active_runtime = active_runtime
        self.checkpoints = checkpoints

    def last_known_good(self, slot: str = "default") -> dict[str, Any] | None:
        lkg = self.registry.last_known_good(slot)
        if lkg:
            return lkg
        active = self.registry.active(slot)
        if not active:
            return None
        prev = active.get("previous_model_id")
        if prev:
            return self.registry.get(prev)
        for m in self.registry.list_models(limit=20):
            if m["model_id"] != active.get("model_id") and m.get("status") in (
                ModelStatus.VALIDATED.value,
                ModelStatus.ROLLED_BACK.value,
                ModelStatus.ACTIVE.value,
            ):
                got = self.registry.get(m["model_id"])
                if got and got.get("model_id") != active.get("model_id"):
                    return got
        # First activation: active itself is the only LKG
        if active:
            return {**active, "is_lkg": True, "lkg_reason": "sole_active_as_lkg"}
        return None

    def rollback(self, *, slot: str = "default", reason: str = "regression") -> dict[str, Any]:
        active = self.registry.active(slot)
        target = self.registry.last_known_good(slot)
        if not target and active and active.get("previous_model_id"):
            target = self.registry.get(active["previous_model_id"])
        if not target:
            return {"ok": False, "error": "no_last_known_good", "reason": reason}
        target_id = target["model_id"]
        if active and target_id == active.get("model_id"):
            return {"ok": False, "error": "lkg_is_already_active", "reason": reason, "model_id": target_id}

        # Pre-flight: never restore a corrupted LKG checkpoint
        cp = target.get("checkpoint_ref") or ""
        integrity = None
        if self.checkpoints is not None:
            integrity = self.checkpoints.verify_integrity(cp)
        else:
            integrity = ActiveModelRuntime.verify_checkpoint(cp)
        if not integrity.get("ok"):
            return {
                "ok": False,
                "error": "lkg_checkpoint_corrupt",
                "integrity": integrity,
                "reason": reason,
                "target_model_id": target_id,
            }

        if active:
            self.registry.update_status(active["model_id"], ModelStatus.ROLLED_BACK)

        # Activate LKG without promoting the failed candidate to LKG
        result = self.registry.activate(
            target_id, slot=slot, mark_as_lkg=True, preserve_outgoing_as_lkg=False
        )
        runtime = None
        runtime_ok = True
        if self.active_runtime is not None:
            runtime = self.active_runtime.switch_to(
                model_id=target_id,
                checkpoint_ref=cp,
                dataset_version=str(target.get("dataset_version") or ""),
                base_model=str(target.get("base_model") or ""),
                meta={"via": "rollback", "reason": reason, "base_model": target.get("base_model")},
            )
            runtime_ok = runtime.get("status") == "ACTIVE"
            if not runtime_ok:
                alt = self.active_runtime.rollback_to_previous()
                runtime = alt.get("runtime") if isinstance(alt, dict) and "runtime" in alt else alt
                runtime_ok = bool(alt.get("ok")) if isinstance(alt, dict) else False
        payload = {
            "ok": runtime_ok if self.active_runtime is not None else True,
            "rolled_back_from": active.get("model_id") if active else None,
            "restored_model_id": target_id,
            "reason": reason,
            "at": time.time(),
            "active": result,
            "runtime": runtime,
            "integrity": integrity,
            "lkg_preserved": True,
        }
        if self.audit_fn:
            self.audit_fn(
                "model_rollback",
                rolled_back_from=payload.get("rolled_back_from"),
                restored_model_id=payload.get("restored_model_id"),
                reason=reason,
            )
        return payload
