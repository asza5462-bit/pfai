"""Append-only audit trail for Command Chat executable actions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CommandAuditLog:
    def __init__(self, path: str = "data/security/command_audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        actor: str,
        command: str,
        tool: str | None,
        status: str,
        result: Any = None,
        required_approval: bool = False,
        approved: bool | None = None,
        conversation_id: str | None = None,
        pending_id: str | None = None,
        error: str | None = None,
    ) -> dict:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "command": command,
            "tool": tool,
            "status": status,
            "required_approval": bool(required_approval),
            "approved": approved,
            "conversation_id": conversation_id,
            "pending_id": pending_id,
            "result_summary": _summarize(result),
            "error": error,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        out = []
        for raw in lines[-max(1, int(limit)) :]:
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))


def _summarize(result: Any) -> Any:
    if result is None:
        return None
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        text = str(result)
    if len(text) > 1200:
        return text[:1200] + "…"
    try:
        return json.loads(text)
    except Exception:
        return text
