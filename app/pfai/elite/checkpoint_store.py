"""PHASE 21 checkpoint store — resumable long-running tasks; never stores secrets."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.types import new_id


class CheckpointStore:
    VERSION = "21.0.0"

    def __init__(self, root: str = "data/longevity/elite/checkpoints") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, task_id: str) -> Path:
        safe = "".join(c for c in task_id if c.isalnum() or c in ("-", "_"))[:120]
        return self.root / f"{safe}.json"

    def save(
        self,
        *,
        task_id: str,
        state: str,
        completed_subtasks: list[Any],
        pending_subtasks: list[Any],
        dependencies: list[Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        errors: list[Any] | None = None,
        retry_counts: dict[str, int] | None = None,
        versions: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = sanitize_args(
            {
                "task_id": task_id,
                "state": state,
                "completed_subtasks": completed_subtasks,
                "pending_subtasks": pending_subtasks,
                "dependencies": dependencies or [],
                "artifacts": artifacts or {},
                "errors": errors or [],
                "retry_counts": retry_counts or {},
                "versions": versions or {},
                "meta": meta or {},
                "checkpoint_id": new_id("ckpt"),
                "saved_at": time.time(),
                "version": self.VERSION,
            }
        )
        path = self._path(task_id)
        with self._lock:
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {"ok": True, "path": str(path), "checkpoint_id": payload["checkpoint_id"]}

    def load(self, task_id: str) -> dict[str, Any] | None:
        path = self._path(task_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def resume_plan(self, task_id: str) -> dict[str, Any]:
        ckpt = self.load(task_id)
        if not ckpt:
            return {"ok": False, "error": "checkpoint_missing", "restart_required": True}
        completed_ids = {
            (s.get("step_id") if isinstance(s, dict) else s) for s in (ckpt.get("completed_subtasks") or [])
        }
        pending = []
        for s in ckpt.get("pending_subtasks") or []:
            if isinstance(s, dict) and s.get("step_id") not in completed_ids:
                pending.append(s)
            elif not isinstance(s, dict) and s not in completed_ids:
                pending.append(s)
        return {
            "ok": True,
            "task_id": task_id,
            "state": ckpt.get("state"),
            "completed_subtasks": ckpt.get("completed_subtasks") or [],
            "pending_subtasks": pending,
            "dependencies": ckpt.get("dependencies") or [],
            "artifacts": ckpt.get("artifacts") or {},
            "errors": ckpt.get("errors") or [],
            "retry_counts": ckpt.get("retry_counts") or {},
            "versions": ckpt.get("versions") or {},
            "restart_required": False,
            "checkpoint_id": ckpt.get("checkpoint_id"),
        }

    def delete(self, task_id: str) -> bool:
        path = self._path(task_id)
        with self._lock:
            if path.is_file():
                path.unlink()
                return True
        return False
