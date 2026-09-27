"""Durable store of verified operational outcomes for LearningCandidate observers.

Bridge writes immediately into LearningCandidatePipeline; this store lets
scheduled candidate passes rediscover coding/eval outcomes that were verified
in the sandbox or evaluation harness — without inventing examples.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class VerifiedOutcomeStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "verified_outcomes.jsonl"
        self._lock = threading.RLock()

    def append(self, item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        row.setdefault("recorded_at", time.time())
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def list_passed_exercises(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._list_kind("coding_passed", limit=limit)

    def list_verified_solutions(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.list_passed_exercises(limit=limit)

    def learning_lessons(self) -> list[dict[str, Any]]:
        return self._list_kind("evaluation", limit=200)

    def _list_kind(self, kind: str, *, limit: int) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("kind") != kind:
                continue
            out.append(item)
            if len(out) >= limit:
                break
        out.reverse()
        return out
