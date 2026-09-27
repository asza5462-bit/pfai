"""PHASE 12 skill learning bridge — experiences → filtered training candidates."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args


class SkillLearningBridge:
    """Capture skill/tool/model experiences without secrets; optional training handoff."""

    def __init__(self, path: str = "data/longevity/skill_learning.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seen: set[str] = set()

    def _hash(self, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def record_experience(
        self,
        *,
        task: str,
        skills_used: list[str],
        models_used: list[str],
        tools_used: list[str],
        result_status: str,
        verification_status: str,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_meta = sanitize_args(meta or {})
        content = {
            "task": (task or "")[:2000],
            "skills_used": list(skills_used or []),
            "models_used": list(models_used or []),
            "tools_used": list(tools_used or []),
            "result_status": result_status,
            "verification_status": verification_status,
            "error": (error or "")[:500] or None,
            "meta": safe_meta,
        }
        # Secret scan
        blob = json.dumps(content).lower()
        if any(x in blob for x in ("password=", "api_key", "begin private key", "otp=")):
            return {"ok": False, "error": "secret_marker_blocked"}
        h = self._hash(content)
        row = {"ts": time.time(), **content, "content_hash": h}
        with self._lock:
            if h in self._seen:
                return {"ok": True, "duplicate": True, "content_hash": h}
            # also scan file for duplicates
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines()[-500:]:
                    try:
                        if json.loads(line).get("content_hash") == h:
                            self._seen.add(h)
                            return {"ok": True, "duplicate": True, "content_hash": h}
                    except Exception:
                        continue
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._seen.add(h)
        return {"ok": True, "duplicate": False, "content_hash": h, "learning_event_id": h[:16]}

    def eligible_training_candidates(self, *, min_status: str = "SUCCESS") -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("verification_status") not in ("SUCCESS", "PARTIAL_SUCCESS"):
                continue
            if row.get("result_status") not in ("SUCCESS", "PARTIAL_SUCCESS"):
                continue
            out.append(row)
        return out

    def export_to_experience_bridge(self, experience_bridge: Any, *, limit: int = 20) -> dict[str, Any]:
        """Push verified experiences into autonomous training experience bridge (no gate bypass)."""
        if experience_bridge is None:
            return {"ok": False, "error": "experience_bridge_missing"}
        exported = 0
        for row in self.eligible_training_candidates()[: int(limit)]:
            instruction = f"Task: {row.get('task')}\nSkills: {', '.join(row.get('skills_used') or [])}"
            response = f"status={row.get('result_status')}; verification={row.get('verification_status')}"
            try:
                experience_bridge.record_evaluation_lesson(
                    instruction=instruction,
                    response=response,
                    source_id=f"skill-learn-{row.get('content_hash', '')[:12]}",
                )
                exported += 1
            except Exception:
                continue
        return {"ok": True, "exported": exported}
