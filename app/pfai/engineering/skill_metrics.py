"""PHASE 14 skill evaluation / usage metrics — no privilege escalation via learning."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.engineering.types import new_id


class SkillEvaluationLedger:
    """Versioned skill evaluation records. Learning cannot grant privileges."""

    def __init__(self, path: str = "data/longevity/engineering/skill_evaluations.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        skill_id: str,
        skill_version: str = "",
        success: bool,
        duration_seconds: float = 0.0,
        validation_ok: bool | None = None,
        test_results: dict[str, Any] | None = None,
        security_findings: int = 0,
        tool_reliability: float | None = None,
        user_approved: bool | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "evaluation_id": new_id("skeval"),
            "ts": time.time(),
            "skill_id": skill_id,
            "skill_version": skill_version,
            "success": bool(success),
            "duration_seconds": float(duration_seconds),
            "validation_ok": validation_ok,
            "test_results": sanitize_args(test_results or {}),
            "security_findings": int(security_findings),
            "tool_reliability": tool_reliability,
            "user_approved": user_approved,
            "privileges_granted": False,
            "authorization_bypass": False,
            "meta": sanitize_args(meta or {}),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, **row}

    def summary(self, skill_id: str | None = None) -> dict[str, Any]:
        if not self.path.exists():
            return {"ok": True, "count": 0, "skills": {}}
        stats: dict[str, dict[str, Any]] = {}
        count = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = row.get("skill_id") or ""
            if skill_id and sid != skill_id:
                continue
            count += 1
            bucket = stats.setdefault(sid, {"uses": 0, "successes": 0, "failures": 0})
            bucket["uses"] += 1
            if row.get("success"):
                bucket["successes"] += 1
            else:
                bucket["failures"] += 1
        return {"ok": True, "count": count, "skills": stats, "learning_cannot_grant_privileges": True}
