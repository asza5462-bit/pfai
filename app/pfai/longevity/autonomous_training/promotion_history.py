"""Durable production promotion / rollback history.

Append-only JSONL. Never deletes prior PROMOTION or ROLLBACK records.
Rollback target resolution uses this history — not the current LKG pointer alone.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def adapter_artifact_hash(checkpoint_ref: str | None) -> str | None:
    """SHA256 of adapter_model.safetensors when present; else None."""
    if not checkpoint_ref:
        return None
    p = Path(checkpoint_ref)
    adapter = p / "adapter_model.safetensors" if p.is_dir() else p
    if not adapter.exists() or not adapter.is_file():
        # try common alternate names
        if p.is_dir():
            for name in ("adapter_model.bin", "pytorch_model.bin"):
                alt = p / name
                if alt.exists():
                    adapter = alt
                    break
            else:
                return None
        else:
            return None
    h = hashlib.sha256()
    with adapter.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PromotionHistory:
    """Append-only promotion/rollback ledger under the training root."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _append(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def list_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def record_promotion(
        self,
        *,
        previous_active_model: str | None,
        previous_lkg_model: str | None,
        new_active_model: str,
        new_lkg_model: str,
        reason: str = "production_quality_gate_pass",
        previous_active_hash: str | None = None,
        previous_lkg_hash: str | None = None,
        new_active_hash: str | None = None,
        new_lkg_hash: str | None = None,
        dataset_version: str | None = None,
        evaluation_dataset: str | None = None,
        evaluation_samples: int | None = None,
        quality_gate_result: str | dict[str, Any] | None = None,
        evaluation_run_id: str | None = None,
        promotion_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pid = promotion_id or f"promo-{uuid.uuid4().hex[:12]}"
        row = {
            "event_type": "PROMOTION",
            "promotion_id": pid,
            "timestamp": time.time(),
            "previous_active_model": previous_active_model,
            "previous_lkg_model": previous_lkg_model,
            "new_active_model": new_active_model,
            "new_lkg_model": new_lkg_model,
            "artifact_hashes": {
                "previous_active": previous_active_hash,
                "previous_lkg": previous_lkg_hash,
                "new_active": new_active_hash,
                "new_lkg": new_lkg_hash,
            },
            "dataset_version": dataset_version,
            "evaluation_dataset": evaluation_dataset,
            "evaluation_samples": evaluation_samples,
            "evaluation_run_id": evaluation_run_id,
            "quality_gate_result": quality_gate_result or "PASS",
            "reason": reason,
        }
        if extra:
            row["extra"] = extra
        return self._append(row)

    def record_rollback(
        self,
        *,
        from_model: str,
        to_model: str,
        reason: str,
        from_hash: str | None = None,
        to_hash: str | None = None,
        promotion_id: str | None = None,
        ok: bool = True,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "event_type": "ROLLBACK",
            "rollback_id": f"rb-{uuid.uuid4().hex[:12]}",
            "promotion_id": promotion_id,
            "timestamp": time.time(),
            "from_model": from_model,
            "to_model": to_model,
            "artifact_hashes": {
                "from": from_hash,
                "to": to_hash,
            },
            "reason": reason,
            "ok": bool(ok),
            "error": error,
        }
        if extra:
            row["extra"] = extra
        return self._append(row)

    def latest_successful_promotion(
        self, *, for_model: str | None = None
    ) -> dict[str, Any] | None:
        events = self.list_events()
        for ev in reversed(events):
            if ev.get("event_type") != "PROMOTION":
                continue
            if for_model and ev.get("new_lkg_model") != for_model and ev.get("new_active_model") != for_model:
                continue
            return ev
        return None

    def resolve_previous_production_model(
        self,
        *,
        current_active: str | None = None,
        current_lkg: str | None = None,
    ) -> dict[str, Any]:
        """Return the most recent valid previous production model from history.

        Does NOT infer solely from the current LKG pointer.
        """
        current = current_active or current_lkg
        events = self.list_events()
        # Prefer the newest PROMOTION whose new_* matches current production model.
        for ev in reversed(events):
            if ev.get("event_type") != "PROMOTION":
                continue
            new_ids = {ev.get("new_active_model"), ev.get("new_lkg_model")}
            if current and current not in new_ids:
                continue
            prev = ev.get("previous_lkg_model") or ev.get("previous_active_model")
            if not prev:
                return {
                    "ok": False,
                    "error": "promotion_missing_previous_lkg",
                    "promotion": ev,
                }
            if current and prev == current:
                return {
                    "ok": False,
                    "error": "previous_lkg_equals_current",
                    "promotion": ev,
                }
            return {
                "ok": True,
                "model_id": prev,
                "promotion_id": ev.get("promotion_id"),
                "promotion": ev,
                "previous_lkg_hash": (ev.get("artifact_hashes") or {}).get("previous_lkg")
                or (ev.get("artifact_hashes") or {}).get("previous_active"),
                "source": "promotion_history",
            }
        return {"ok": False, "error": "no_promotion_history", "model_id": None}

    def previous_lkg_model(self, *, current_active: str | None = None, current_lkg: str | None = None) -> str | None:
        res = self.resolve_previous_production_model(
            current_active=current_active, current_lkg=current_lkg
        )
        return res.get("model_id") if res.get("ok") else None

    def ensure_seed_promotion(
        self,
        *,
        previous_model: str,
        new_model: str,
        previous_hash: str | None,
        new_hash: str | None,
        dataset_version: str | None = None,
        evaluation_dataset: str | None = None,
        evaluation_samples: int | None = None,
        evaluation_run_id: str | None = None,
        reason: str = "phase11_seed_production_promotion",
    ) -> dict[str, Any]:
        """Idempotently seed a PROMOTION record if none exists for new_model."""
        existing = self.latest_successful_promotion(for_model=new_model)
        if existing and existing.get("previous_lkg_model") == previous_model:
            return {"ok": True, "seeded": False, "promotion": existing}
        row = self.record_promotion(
            previous_active_model=previous_model,
            previous_lkg_model=previous_model,
            new_active_model=new_model,
            new_lkg_model=new_model,
            previous_active_hash=previous_hash,
            previous_lkg_hash=previous_hash,
            new_active_hash=new_hash,
            new_lkg_hash=new_hash,
            dataset_version=dataset_version,
            evaluation_dataset=evaluation_dataset,
            evaluation_samples=evaluation_samples,
            evaluation_run_id=evaluation_run_id,
            quality_gate_result="PASS",
            reason=reason,
        )
        return {"ok": True, "seeded": True, "promotion": row}
