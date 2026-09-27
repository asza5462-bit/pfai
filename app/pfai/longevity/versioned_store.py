"""In-memory versioned store scaffold for knowledge/config/skill rollback demos."""
from __future__ import annotations

import time
from typing import Any


class InMemoryVersionedStore:
    def __init__(self) -> None:
        # entity_type -> entity_id -> list[versions]
        self._data: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def put_version(self, entity_type: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        bucket = self._data.setdefault(entity_type, {}).setdefault(entity_id, [])
        for row in bucket:
            if row.get("status") == "active":
                row["status"] = "superseded"
        version = len(bucket) + 1
        rec = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "version": version,
            "payload": dict(payload),
            "status": "active",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        bucket.append(rec)
        return rec

    def get_active(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        for row in reversed(self._data.get(entity_type, {}).get(entity_id, [])):
            if row.get("status") == "active":
                return row
        return None

    def history(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        return list(self._data.get(entity_type, {}).get(entity_id, []))

    def rollback(self, entity_type: str, entity_id: str, to_version: int | str) -> dict[str, Any]:
        rows = self._data.get(entity_type, {}).get(entity_id, [])
        target = next((r for r in rows if r["version"] == int(to_version)), None)
        if not target:
            raise KeyError(f"version not found: {to_version}")
        for row in rows:
            if row.get("status") == "active":
                row["status"] = "rolled_back"
        # Re-activate by copying target as a new active version for auditability.
        return self.put_version(entity_type, entity_id, dict(target["payload"]))
