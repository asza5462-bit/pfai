"""Long-term memory adapter over MemoryStore (model-agnostic, durable versions).

PHASE 3: version history persists in SQLite; kinds survive across restarts;
export/import roundtrip without depending on any LLM vendor.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pfai.interfaces.memory import MemoryKind, MemoryRecord, MemoryScope, MemorySystemProtocol

__all__ = ["LongTermMemory", "MemorySystem", "MemoryScope", "MemorySystemProtocol", "MemoryKind", "MemoryRecord"]

PHASE = 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_KIND_TO_SCOPE = {
    MemoryKind.EPISODIC: MemoryScope.SESSION,
    MemoryKind.SEMANTIC: MemoryScope.SYSTEM,
    MemoryKind.PROCEDURAL: MemoryScope.SYSTEM,
    MemoryKind.USER_PREFERENCE: MemoryScope.PREFERENCE,
    MemoryKind.PROJECT_KNOWLEDGE: MemoryScope.SYSTEM,
    MemoryKind.LEARNED_LESSON: MemoryScope.DECISION,
    MemoryKind.VERIFIED_KNOWLEDGE: MemoryScope.SYSTEM,
    MemoryKind.INTERACTION_HISTORY: MemoryScope.COMMAND,
}

# Kinds accepted by CommandMemory without remapping — keep in sync when wrapping chat memory.
LTM_KIND_VALUES = {k.value for k in MemoryKind}


class LongTermMemory:
    """Wraps MemoryStore / CommandMemory-like objects behind LTM kinds.

    Version history is durable under ``versions_path`` (SQLite). Content rows live
    in the backend store; version metadata never stores secrets.
    """

    def __init__(
        self,
        backend: Any,
        *,
        versions_path: str = "data/longevity/ltm_versions.sqlite3",
    ) -> None:
        self.backend = backend
        self.versions_path = Path(versions_path)
        self.versions_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._vdb = sqlite3.connect(self.versions_path, check_same_thread=False)
        with self._lock:
            self._vdb.execute(
                """CREATE TABLE IF NOT EXISTS ltm_versions (
                    record_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT,
                    confidence REAL,
                    status TEXT,
                    scope TEXT,
                    store_id INTEGER,
                    created_at TEXT,
                    updated_at TEXT,
                    provenance TEXT,
                    meta TEXT,
                    PRIMARY KEY (record_id, version)
                )"""
            )
            self._vdb.commit()

    def _write_backend(self, kind_s: str, content: str, source: str, confidence: float) -> Any:
        # Prefer raw MemoryStore when wrapped by CommandMemory so LTM kinds are preserved.
        store = getattr(self.backend, "memory", None)
        if store is not None and hasattr(store, "add"):
            return store.add(kind_s, content, source, confidence)
        if hasattr(self.backend, "add") and not hasattr(self.backend, "remember"):
            return self.backend.add(kind_s, content, source, confidence)
        if hasattr(self.backend, "remember"):
            # Expand CommandMemory allow-list path: write via underlying MemoryStore when present.
            if store is not None and hasattr(store, "add"):
                return store.add(kind_s, content, source, confidence)
            return self.backend.remember(kind_s, content, source=source, confidence=confidence)
        if hasattr(self.backend, "add"):
            return self.backend.add(kind_s, content, source, confidence)
        raise TypeError("backend must provide remember() or add()")

    def store(self, record: MemoryRecord) -> MemoryRecord:
        kind = record.kind if isinstance(record.kind, MemoryKind) else MemoryKind(str(record.kind))
        scope = record.scope or _KIND_TO_SCOPE.get(kind, MemoryScope.SYSTEM)
        scope_s = scope.value if isinstance(scope, MemoryScope) else str(scope)
        kind_s = kind.value if isinstance(kind, MemoryKind) else str(kind)
        mid = self._write_backend(kind_s, record.content, record.source, float(record.confidence))
        if not record.record_id:
            record.record_id = f"ltm-{mid or uuid.uuid4().hex[:10]}"
        record.created_at = record.created_at or _now()
        record.updated_at = _now()
        record.meta = {**(record.meta or {}), "store_id": mid, "scope": scope_s}
        with self._lock:
            cur = self._vdb.execute(
                "SELECT COALESCE(MAX(version), 0) FROM ltm_versions WHERE record_id=?",
                (record.record_id,),
            )
            nxt = int(cur.fetchone()[0]) + 1
            self._vdb.execute(
                "UPDATE ltm_versions SET status=? WHERE record_id=? AND status=?",
                ("superseded", record.record_id, "active"),
            )
            record.version = nxt
            record.status = "active"
            self._vdb.execute(
                """INSERT INTO ltm_versions
                   (record_id, version, kind, content, source, confidence, status, scope,
                    store_id, created_at, updated_at, provenance, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.record_id,
                    nxt,
                    kind_s,
                    record.content,
                    record.source,
                    float(record.confidence),
                    "active",
                    scope_s,
                    int(mid) if mid is not None else None,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.provenance or {}, ensure_ascii=False),
                    json.dumps(record.meta or {}, ensure_ascii=False),
                ),
            )
            self._vdb.commit()
        return record

    def history(self, record_id: str) -> list[MemoryRecord]:
        with self._lock:
            rows = self._vdb.execute(
                """SELECT record_id, version, kind, content, source, confidence, status, scope,
                          store_id, created_at, updated_at, provenance, meta
                   FROM ltm_versions WHERE record_id=? ORDER BY version ASC""",
                (record_id,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def active(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._vdb.execute(
                """SELECT record_id, version, kind, content, source, confidence, status, scope,
                          store_id, created_at, updated_at, provenance, meta
                   FROM ltm_versions WHERE record_id=? AND status=? ORDER BY version DESC LIMIT 1""",
                (record_id, "active"),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def _row_to_record(self, row) -> MemoryRecord:
        meta = json.loads(row[12] or "{}")
        if row[8] is not None:
            meta.setdefault("store_id", row[8])
        meta.setdefault("scope", row[7] or "")
        return MemoryRecord(
            record_id=row[0],
            kind=row[2],
            content=row[3],
            scope=row[7] or MemoryScope.SYSTEM.value,
            source=row[4] or "",
            confidence=float(row[5] or 0),
            version=int(row[1]),
            status=row[6] or "active",
            created_at=row[9] or "",
            updated_at=row[10] or "",
            provenance=json.loads(row[11] or "{}"),
            meta=meta,
        )

    def query(
        self,
        *,
        kind: MemoryKind | str | None = None,
        query: str = "",
        limit: int = 20,
    ) -> list[MemoryRecord]:
        kind_s = kind.value if isinstance(kind, MemoryKind) else (str(kind) if kind else None)
        # Prefer durable active versions when listing without text query.
        if not query:
            with self._lock:
                if kind_s:
                    rows = self._vdb.execute(
                        """SELECT record_id, version, kind, content, source, confidence, status, scope,
                                  store_id, created_at, updated_at, provenance, meta
                           FROM ltm_versions WHERE status=? AND kind=?
                           ORDER BY version DESC LIMIT ?""",
                        ("active", kind_s, int(limit)),
                    ).fetchall()
                else:
                    rows = self._vdb.execute(
                        """SELECT record_id, version, kind, content, source, confidence, status, scope,
                                  store_id, created_at, updated_at, provenance, meta
                           FROM ltm_versions WHERE status=?
                           ORDER BY version DESC LIMIT ?""",
                        ("active", int(limit)),
                    ).fetchall()
            return [self._row_to_record(r) for r in rows]

        results: list[dict[str, Any]] = []
        store = getattr(self.backend, "memory", self.backend)
        if hasattr(store, "search"):
            results = store.search(query, limit=limit) or []
        elif hasattr(self.backend, "search"):
            results = self.backend.search(query, limit=limit) or []
        elif hasattr(self.backend, "relevant"):
            results = self.backend.relevant(query, limit=limit) or []
        out: list[MemoryRecord] = []
        for r in results:
            if kind_s and r.get("kind") and r.get("kind") != kind_s:
                continue
            out.append(
                MemoryRecord(
                    record_id=str(r.get("id") or r.get("record_id") or uuid.uuid4().hex[:8]),
                    kind=r.get("kind") or kind_s or MemoryKind.SEMANTIC.value,
                    content=r.get("content") or "",
                    source=r.get("source") or "",
                    confidence=float(r.get("confidence") or 0),
                    created_at=r.get("created_at") or "",
                    meta={"raw": r, "store_id": r.get("id")},
                )
            )
            if len(out) >= limit:
                break
        return out

    def supersede(self, record_id: str, new_content: str, *, source: str = "") -> MemoryRecord:
        hist = self.history(record_id)
        base = hist[-1] if hist else MemoryRecord(record_id=record_id, kind=MemoryKind.SEMANTIC, content="")
        return self.store(
            MemoryRecord(
                record_id=record_id,
                kind=base.kind,
                content=new_content,
                source=source or base.source,
                confidence=base.confidence,
                provenance=dict(base.provenance or {}),
                scope=base.scope,
            )
        )

    def rollback(self, record_id: str, to_version: int | None = None) -> MemoryRecord:
        hist = self.history(record_id)
        if not hist:
            raise KeyError(record_id)
        if to_version is None:
            target = next((h for h in reversed(hist[:-1]) if h.status != "rolled_back"), hist[0])
        else:
            target = next((h for h in hist if h.version == int(to_version)), None)
        if not target:
            raise KeyError("version not found")
        with self._lock:
            self._vdb.execute(
                "UPDATE ltm_versions SET status=? WHERE record_id=? AND status=?",
                ("rolled_back", record_id, "active"),
            )
            self._vdb.commit()
        return self.supersede(record_id, target.content, source="ltm_rollback")

    def export_records(self, *, kind: MemoryKind | str | None = None) -> list[dict[str, Any]]:
        rows = self.query(kind=kind, query="", limit=10000)
        return [
            {
                "record_id": r.record_id,
                "kind": r.kind.value if isinstance(r.kind, MemoryKind) else r.kind,
                "content": r.content,
                "source": r.source,
                "confidence": r.confidence,
                "version": r.version,
                "status": r.status,
                "created_at": r.created_at,
                "provenance": r.provenance,
                "meta": {k: v for k, v in (r.meta or {}).items() if k != "raw"},
            }
            for r in rows
        ]

    def import_records(self, rows: list[dict[str, Any]], *, as_new: bool = True) -> int:
        """Import portable records. Always creates new versioned rows (no silent overwrite)."""
        count = 0
        for row in rows or []:
            rid = "" if as_new else str(row.get("record_id") or "")
            self.store(
                MemoryRecord(
                    record_id=rid,
                    kind=row.get("kind") or MemoryKind.SEMANTIC.value,
                    content=str(row.get("content") or ""),
                    source=str(row.get("source") or "import"),
                    confidence=float(row.get("confidence") or 0),
                    provenance=dict(row.get("provenance") or {}),
                    meta={"imported": True, **(row.get("meta") or {})},
                )
            )
            count += 1
        return count

    def remember_kind(self, kind: str, content: str, source: str = "", confidence: float = 0.0) -> int:
        rec = self.store(
            MemoryRecord(
                record_id="",
                kind=kind,
                content=content,
                source=source,
                confidence=confidence,
            )
        )
        return int((rec.meta or {}).get("store_id") or 0)


class MemorySystem:
    """Facade implementing MemorySystemProtocol over LongTermMemory / MemoryStore."""

    def __init__(self, backend: Any | None = None, ltm: LongTermMemory | None = None) -> None:
        if ltm is not None:
            self.ltm = ltm
        elif backend is not None:
            self.ltm = LongTermMemory(backend)
        else:
            self.ltm = None

    def remember(
        self,
        scope: MemoryScope | str,
        content: str,
        *,
        source: str = "",
        confidence: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if self.ltm is None:
            raise NotImplementedError("MemorySystem requires a backend")
        kind = (meta or {}).get("kind") or MemoryKind.SEMANTIC.value
        rec = self.ltm.store(
            MemoryRecord(
                record_id="",
                kind=kind,
                content=content,
                scope=scope,
                source=source,
                confidence=confidence,
                meta=dict(meta or {}),
            )
        )
        return int((rec.meta or {}).get("store_id") or 0)

    def recall(
        self,
        query: str,
        *,
        scope: MemoryScope | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if self.ltm is None:
            raise NotImplementedError("MemorySystem requires a backend")
        hits = self.ltm.query(query=query, limit=limit)
        return [
            {"id": h.record_id, "kind": h.kind, "content": h.content, "source": h.source, "confidence": h.confidence}
            for h in hits
        ]

    def forget(self, memory_id: int) -> bool:
        if self.ltm is None or not hasattr(self.ltm.backend, "forget"):
            store = getattr(getattr(self.ltm, "backend", None), "memory", None) if self.ltm else None
            if store is not None and hasattr(store, "forget"):
                return bool(store.forget(int(memory_id)))
            raise NotImplementedError("backend does not support forget")
        return bool(self.ltm.backend.forget(int(memory_id)))
