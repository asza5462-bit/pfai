"""Checkpoint metadata store for training jobs."""
from __future__ import annotations

import hashlib
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
        path = meta.get("path")
        integrity = self.verify_integrity(str(path)) if path else {"ok": False, "error": "missing_path"}
        row = {
            "job_id": job_id,
            "ts": time.time(),
            "path": path,
            "kind": meta.get("kind"),
            "step": meta.get("step"),
            "integrity_ok": bool(integrity.get("ok")),
            "checksum": integrity.get("checksum"),
            "meta": {k: v for k, v in meta.items() if k not in ("path", "kind", "step")},
        }
        with self._lock:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def verify_integrity(self, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": "missing"}
        try:
            if p.is_dir():
                files = sorted([x for x in p.rglob("*") if x.is_file()])
                if not files:
                    return {"ok": False, "error": "empty_checkpoint"}
                h = hashlib.sha256()
                for f in files[:50]:
                    h.update(f.name.encode())
                    h.update(f.read_bytes()[:65536])
                return {"ok": True, "checksum": h.hexdigest(), "files": len(files)}
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            return {"ok": True, "checksum": digest, "files": 1}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

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
