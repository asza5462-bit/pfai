"""Checkpoint metadata store for training jobs."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self, root: str = "data/longevity/training/checkpoints") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"
        self._lock = threading.RLock()

    def record(self, job_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        row = {
            "job_id": job_id,
            "ts": time.time(),
            "path": meta.get("path"),
            "kind": meta.get("kind"),
            "step": meta.get("step"),
            "meta": {k: v for k, v in meta.items() if k not in ("path", "kind", "step")},
        }
        with self._lock:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def list_for_job(self, job_id: str) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        out = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("job_id") == job_id:
                out.append(row)
        return out

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        rows = [
            json.loads(line)
            for line in self.index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return list(reversed(rows[-int(limit) :]))
