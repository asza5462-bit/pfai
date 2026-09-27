"""Active model runtime pointer — activation/rollback switches what PFAI serves."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class ActiveModelRuntime:
    """Persists the model reference used by the platform (not just DB status).

    Inference backends that understand checkpoint paths can read `current()`.
    """

    def __init__(self, path: str = "data/longevity/training/active_runtime.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def current(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {
                    "model_id": None,
                    "checkpoint_ref": None,
                    "status": "UNAVAILABLE",
                    "loaded": False,
                    "note": "No active training-derived model pointer.",
                }
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {"model_id": None, "status": "ERROR", "loaded": False}
            data.setdefault("loaded", bool(data.get("checkpoint_ref")))
            return data

    def switch_to(
        self,
        *,
        model_id: str,
        checkpoint_ref: str,
        dataset_version: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self.current()
            payload = {
                "model_id": model_id,
                "checkpoint_ref": checkpoint_ref,
                "dataset_version": dataset_version,
                "previous_model_id": previous.get("model_id"),
                "previous_checkpoint_ref": previous.get("checkpoint_ref"),
                "activated_at": time.time(),
                "status": "ACTIVE",
                "loaded": bool(checkpoint_ref),
                "meta": meta or {},
            }
            # Integrity: refuse empty checkpoint
            if not checkpoint_ref:
                payload["status"] = "FAILED"
                payload["loaded"] = False
                payload["error"] = "missing_checkpoint"
                return payload
            cp = Path(checkpoint_ref)
            if not cp.exists():
                payload["status"] = "FAILED"
                payload["loaded"] = False
                payload["error"] = "checkpoint_missing_on_disk"
                return payload
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return payload

    def rollback_to_previous(self) -> dict[str, Any]:
        cur = self.current()
        prev_id = cur.get("previous_model_id")
        prev_cp = cur.get("previous_checkpoint_ref")
        if not prev_id or not prev_cp:
            return {"ok": False, "error": "no_previous_runtime"}
        switched = self.switch_to(
            model_id=str(prev_id),
            checkpoint_ref=str(prev_cp),
            meta={"via": "rollback"},
        )
        return {"ok": switched.get("status") == "ACTIVE", "runtime": switched}
