"""Immutable training audit log (never records secrets/OTPs)."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_REDACT = re.compile(
    r"(?i)(password|passcode|otp|api[_-]?key|secret|token|authorization)\s*[:=]\s*\S+"
)


class TrainingAuditLog:
    def __init__(self, path: str = "data/longevity/training/training_audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _scrub(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if any(s in lk for s in ("password", "passcode", "otp", "secret", "token", "api_key")):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = self._scrub(v)
            return out
        if isinstance(obj, list):
            return [self._scrub(x) for x in obj]
        if isinstance(obj, str):
            return _REDACT.sub(r"\1=[REDACTED]", obj)
        return obj

    def record(self, event: str, **detail: Any) -> dict[str, Any]:
        row = {
            "ts": time.time(),
            "event": event,
            "detail": self._scrub(detail),
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [json.loads(x) for x in lines[-int(limit) :]]
