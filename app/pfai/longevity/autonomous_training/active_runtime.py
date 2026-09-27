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
                    "base_model": None,
                    "adapter_path": None,
                    "status": "UNAVAILABLE",
                    "loaded": False,
                    "note": "No active training-derived model pointer.",
                }
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {"model_id": None, "status": "ERROR", "loaded": False, "error": "corrupt_runtime_pointer"}
            data.setdefault("loaded", bool(data.get("checkpoint_ref")))
            data.setdefault("base_model", None)
            data.setdefault("adapter_path", data.get("checkpoint_ref"))
            return data

    @staticmethod
    def verify_checkpoint(checkpoint_ref: str) -> dict[str, Any]:
        """Verify checkpoint exists, is readable, and looks like an adapter/model dir."""
        if not checkpoint_ref:
            return {"ok": False, "error": "missing_checkpoint"}
        cp = Path(checkpoint_ref)
        if not cp.exists():
            return {"ok": False, "error": "checkpoint_missing_on_disk"}
        try:
            if cp.is_file():
                _ = cp.read_bytes()[:64]
                return {"ok": True, "kind": "file", "path": str(cp)}
            files = [p for p in cp.iterdir() if p.is_file()]
            if not files:
                return {"ok": False, "error": "empty_checkpoint"}
            names = {p.name for p in files}
            has_adapter = bool(
                names & {"adapter_config.json", "adapter_model.safetensors", "adapter_model.bin", "adapter_manifest.json"}
            ) or any(p.suffix == ".safetensors" for p in files)
            has_base = "config.json" in names or any(p.name.startswith("pytorch_model") for p in files)
            # Readable probe
            for f in files[:5]:
                _ = f.read_bytes()[:32]
            return {
                "ok": True,
                "kind": "dir",
                "path": str(cp),
                "file_count": len(files),
                "has_adapter": has_adapter,
                "has_base_config": has_base,
                "inference_compatible": has_adapter or has_base,
            }
        except Exception as exc:
            return {"ok": False, "error": f"unreadable:{type(exc).__name__}"}

    def switch_to(
        self,
        *,
        model_id: str,
        checkpoint_ref: str,
        dataset_version: str = "",
        base_model: str = "",
        meta: dict[str, Any] | None = None,
        require_inference_compatible: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self.current()
            integrity = self.verify_checkpoint(checkpoint_ref)
            payload = {
                "model_id": model_id,
                "checkpoint_ref": checkpoint_ref,
                "adapter_path": checkpoint_ref,
                "base_model": base_model or (meta or {}).get("base_model"),
                "dataset_version": dataset_version,
                "previous_model_id": previous.get("model_id"),
                "previous_checkpoint_ref": previous.get("checkpoint_ref"),
                "previous_base_model": previous.get("base_model"),
                "activated_at": time.time(),
                "status": "ACTIVE",
                "loaded": False,
                "meta": meta or {},
                "integrity": integrity,
            }
            if not integrity.get("ok"):
                payload["status"] = "FAILED"
                payload["error"] = integrity.get("error") or "checkpoint_integrity_failed"
                return payload
            if require_inference_compatible and not integrity.get("inference_compatible"):
                payload["status"] = "FAILED"
                payload["error"] = "inference_incompatible_checkpoint"
                return payload
            payload["loaded"] = True
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return payload

    def reload(self) -> dict[str, Any]:
        """Re-read pointer and re-verify checkpoint (post-restart safety)."""
        cur = self.current()
        if not cur.get("checkpoint_ref"):
            return {"ok": False, "status": "UNAVAILABLE", "runtime": cur}
        integrity = self.verify_checkpoint(str(cur["checkpoint_ref"]))
        if not integrity.get("ok"):
            # Attempt LKG/previous fallback
            fb = self.fallback_to_previous(reason=str(integrity.get("error") or "corrupt"))
            return {"ok": bool(fb.get("ok")), "status": "FALLBACK" if fb.get("ok") else "FAILED", "integrity": integrity, "fallback": fb, "runtime": self.current()}
        cur["integrity"] = integrity
        cur["loaded"] = True
        cur["reloaded_at"] = time.time()
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        return {"ok": True, "status": "ACTIVE", "runtime": cur, "integrity": integrity}

    def fallback_to_previous(self, *, reason: str = "corrupt_checkpoint") -> dict[str, Any]:
        cur = self.current()
        prev_id = cur.get("previous_model_id")
        prev_cp = cur.get("previous_checkpoint_ref")
        if not prev_id or not prev_cp:
            return {"ok": False, "error": "no_lkg_or_previous_for_fallback", "reason": reason}
        switched = self.switch_to(
            model_id=str(prev_id),
            checkpoint_ref=str(prev_cp),
            base_model=str(cur.get("previous_base_model") or ""),
            meta={"via": "fallback", "reason": reason},
        )
        return {"ok": switched.get("status") == "ACTIVE", "runtime": switched, "reason": reason}

    def rollback_to_previous(self) -> dict[str, Any]:
        cur = self.current()
        prev_id = cur.get("previous_model_id")
        prev_cp = cur.get("previous_checkpoint_ref")
        if not prev_id or not prev_cp:
            return {"ok": False, "error": "no_previous_runtime"}
        switched = self.switch_to(
            model_id=str(prev_id),
            checkpoint_ref=str(prev_cp),
            base_model=str(cur.get("previous_base_model") or ""),
            meta={"via": "rollback"},
        )
        return {"ok": switched.get("status") == "ACTIVE", "runtime": switched}
