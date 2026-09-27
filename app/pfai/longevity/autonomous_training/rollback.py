"""Model rollback to previous production model via durable promotion history."""
from __future__ import annotations

import time
from typing import Any

from .active_runtime import ActiveModelRuntime
from .checkpoints import CheckpointStore
from .model_registry import ModelRegistry
from .promotion_history import PromotionHistory, adapter_artifact_hash
from .types import ModelStatus


class ModelRollbackManager:
    def __init__(
        self,
        registry: ModelRegistry,
        audit_fn=None,
        active_runtime: ActiveModelRuntime | None = None,
        checkpoints: CheckpointStore | None = None,
        promotion_history: PromotionHistory | None = None,
    ) -> None:
        self.registry = registry
        self.audit_fn = audit_fn
        self.active_runtime = active_runtime
        self.checkpoints = checkpoints
        self.promotion_history = promotion_history

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
        if active:
            return {**active, "is_lkg": True, "lkg_reason": "sole_active_as_lkg"}
        return None

    def resolve_previous_production_model(
        self, *, slot: str = "default"
    ) -> dict[str, Any]:
        """Resolve rollback target from durable promotion history (not current LKG alone)."""
        active = self.registry.active(slot) or {}
        lkg = self.registry.last_known_good(slot) or {}
        if self.promotion_history is None:
            return {
                "ok": False,
                "error": "promotion_history_unavailable",
                "model_id": None,
            }
        resolved = self.promotion_history.resolve_previous_production_model(
            current_active=active.get("model_id"),
            current_lkg=lkg.get("model_id") or active.get("model_id"),
        )
        if not resolved.get("ok"):
            return resolved
        target_id = resolved["model_id"]
        target = self.registry.get(target_id)
        if not target:
            return {
                "ok": False,
                "error": "previous_lkg_not_in_registry",
                "model_id": target_id,
                "promotion_id": resolved.get("promotion_id"),
            }
        return {
            **resolved,
            "model": target,
            "checkpoint_ref": target.get("checkpoint_ref"),
        }

    def _verify_target(self, checkpoint_ref: str) -> dict[str, Any]:
        if self.checkpoints is not None:
            return self.checkpoints.verify_integrity(checkpoint_ref)
        return ActiveModelRuntime.verify_checkpoint(checkpoint_ref)

    def rollback(self, *, slot: str = "default", reason: str = "regression") -> dict[str, Any]:
        active = self.registry.active(slot)
        active_id = active.get("model_id") if active else None

        resolved = self.resolve_previous_production_model(slot=slot)
        if not resolved.get("ok"):
            payload = {
                "ok": False,
                "error": resolved.get("error") or "no_previous_production_model",
                "reason": reason,
                "active_model_id": active_id,
                "at": time.time(),
            }
            if self.audit_fn:
                self.audit_fn("model_rollback_failed", **payload)
            if self.promotion_history is not None:
                self.promotion_history.record_rollback(
                    from_model=str(active_id or ""),
                    to_model="",
                    reason=reason,
                    ok=False,
                    error=payload["error"],
                )
            return payload

        target = resolved.get("model") or self.registry.get(resolved["model_id"])
        target_id = resolved["model_id"]
        cp = (target or {}).get("checkpoint_ref") or ""

        # Idempotent: already serving the resolved previous production model
        if active_id and active_id == target_id:
            payload = {
                "ok": True,
                "already_at_target": True,
                "rolled_back_from": active_id,
                "restored_model_id": target_id,
                "reason": reason,
                "at": time.time(),
                "lkg_preserved": True,
                "source": "promotion_history",
                "promotion_id": resolved.get("promotion_id"),
            }
            if self.audit_fn:
                self.audit_fn("model_rollback_idempotent", **payload)
            return payload

        integrity = self._verify_target(cp)
        expected_hash = resolved.get("previous_lkg_hash")
        actual_hash = adapter_artifact_hash(cp)
        hash_ok = True
        if expected_hash and actual_hash and expected_hash != actual_hash:
            hash_ok = False
            integrity = {
                **integrity,
                "ok": False,
                "error": "rollback_target_hash_mismatch",
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            }

        if not integrity.get("ok") or not hash_ok:
            payload = {
                "ok": False,
                "error": "lkg_checkpoint_corrupt"
                if integrity.get("error") != "rollback_target_hash_mismatch"
                else "rollback_target_hash_mismatch",
                "integrity": integrity,
                "reason": reason,
                "target_model_id": target_id,
                "active_model_id": active_id,
                "at": time.time(),
                # fail closed: do not change active
                "active_unchanged": True,
            }
            if self.audit_fn:
                self.audit_fn("model_rollback_failed", **payload)
            if self.promotion_history is not None:
                self.promotion_history.record_rollback(
                    from_model=str(active_id or ""),
                    to_model=str(target_id),
                    reason=reason,
                    from_hash=adapter_artifact_hash((active or {}).get("checkpoint_ref")),
                    to_hash=actual_hash,
                    promotion_id=resolved.get("promotion_id"),
                    ok=False,
                    error=payload["error"],
                )
            return payload

        from_hash = adapter_artifact_hash((active or {}).get("checkpoint_ref"))
        to_hash = actual_hash

        if active:
            self.registry.update_status(active["model_id"], ModelStatus.ROLLED_BACK)
            # Keep failed/promoted candidate production_ready cleared on demotion
            try:
                self.registry.set_production_ready(
                    active["model_id"],
                    ready=False,
                    reason=f"rolled_back:{reason}",
                )
            except Exception:
                pass

        # Activate previous production model as LKG; do NOT promote outgoing to LKG
        # record_promotion=False: ROLLBACK event is recorded separately; do not invent PROMOTION
        result = self.registry.activate(
            target_id,
            slot=slot,
            mark_as_lkg=True,
            preserve_outgoing_as_lkg=False,
            production_ready=True,
            record_promotion=False,
        )

        runtime = None
        runtime_ok = True
        if self.active_runtime is not None:
            runtime = self.active_runtime.switch_to(
                model_id=target_id,
                checkpoint_ref=cp,
                dataset_version=str((target or {}).get("dataset_version") or ""),
                base_model=str((target or {}).get("base_model") or ""),
                meta={
                    "via": "rollback",
                    "reason": reason,
                    "base_model": (target or {}).get("base_model"),
                    "production_ready": True,
                    "serving_tier": "production_ready",
                },
            )
            # Ensure production serving flags on runtime pointer
            try:
                cur = self.active_runtime.current()
                cur["production_ready"] = True
                cur["serving_tier"] = "production_ready"
                self.active_runtime.path.write_text(
                    __import__("json").dumps(cur, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
            runtime_ok = runtime.get("status") == "ACTIVE"
            if not runtime_ok:
                alt = self.active_runtime.rollback_to_previous()
                runtime = alt.get("runtime") if isinstance(alt, dict) and "runtime" in alt else alt
                runtime_ok = bool(alt.get("ok")) if isinstance(alt, dict) else False

        # Record ROLLBACK without erasing PROMOTION history
        rb_row = None
        if self.promotion_history is not None:
            rb_row = self.promotion_history.record_rollback(
                from_model=str(active_id or ""),
                to_model=str(target_id),
                reason=reason,
                from_hash=from_hash,
                to_hash=to_hash,
                promotion_id=resolved.get("promotion_id"),
                ok=runtime_ok if self.active_runtime is not None else True,
            )

        payload = {
            "ok": runtime_ok if self.active_runtime is not None else True,
            "rolled_back_from": active_id,
            "restored_model_id": target_id,
            "reason": reason,
            "at": time.time(),
            "active": result,
            "runtime": runtime,
            "integrity": integrity,
            "lkg_preserved": True,
            "from_hash": from_hash,
            "to_hash": to_hash,
            "source": "promotion_history",
            "promotion_id": resolved.get("promotion_id"),
            "rollback_record": rb_row,
            # Candidate artifact must remain on disk (pointer-only rollback)
            "candidate_retained": True,
        }
        if self.audit_fn:
            self.audit_fn(
                "model_rollback",
                rolled_back_from=payload.get("rolled_back_from"),
                restored_model_id=payload.get("restored_model_id"),
                reason=reason,
                from_hash=from_hash,
                to_hash=to_hash,
                promotion_id=resolved.get("promotion_id"),
            )
        return payload
