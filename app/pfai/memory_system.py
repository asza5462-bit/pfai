"""Long-term memory adapter over existing MemoryStore (model-agnostic)."""
from __future__ import annotations

import time
import uuid
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


class LongTermMemory:
    """Wraps MemoryStore / CommandMemory-like objects behind LTM kinds."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self._versions: dict[str, list[MemoryRecord]] = {}

    def store(self, record: MemoryRecord) -> MemoryRecord:
        kind = record.kind if isinstance(record.kind, MemoryKind) else MemoryKind(str(record.kind))
        scope = record.scope or _KIND_TO_SCOPE.get(kind, MemoryScope.SYSTEM)
        scope_s = scope.value if isinstance(scope, MemoryScope) else str(scope)
        kind_s = kind.value
        mid = None
        if hasattr(self.backend, "remember"):
            mid = self.backend.remember(kind_s, record.content, source=record.source, confidence=record.confidence)
        elif hasattr(self.backend, "add"):
            mid = self.backend.add(kind_s, record.content, source=record.source, confidence=record.confidence)
        else:
            raise TypeError("backend must provide remember() or add()")
        if not record.record_id:
            record.record_id = f"ltm-{mid or uuid.uuid4().hex[:10]}"
        record.created_at = record.created_at or _now()
        record.updated_at = _now()
        record.meta = {**(record.meta or {}), "store_id": mid, "scope": scope_s}
        hist = self._versions.setdefault(record.record_id, [])
        for prev in hist:
            if prev.status == "active":
                prev.status = "superseded"
        record.version = len(hist) + 1
        record.status = "active"
        hist.append(record)
        return record

    def query(
        self,
        *,
        kind: MemoryKind | str | None = None,
        query: str = "",
        limit: int = 20,
    ) -> list[MemoryRecord]:
        kind_s = kind.value if isinstance(kind, MemoryKind) else (str(kind) if kind else None)
        results: list[dict[str, Any]] = []
        if query and hasattr(self.backend, "search"):
            results = self.backend.search(query, limit=limit) or []
        elif query and hasattr(self.backend, "relevant"):
            results = self.backend.relevant(query, limit=limit) or []
        elif kind_s and hasattr(self.backend, "list_by_kind"):
            results = self.backend.list_by_kind(kind_s, limit=limit) or []
        elif hasattr(self.backend, "all_documents"):
            results = (self.backend.all_documents() or [])[:limit]
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
                    meta={"raw": r},
                )
            )
            if len(out) >= limit:
                break
        return out

    def supersede(self, record_id: str, new_content: str, *, source: str = "") -> MemoryRecord:
        hist = self._versions.get(record_id) or []
        base = hist[-1] if hist else MemoryRecord(record_id=record_id, kind=MemoryKind.SEMANTIC, content="")
        return self.store(
            MemoryRecord(
                record_id=record_id,
                kind=base.kind,
                content=new_content,
                source=source or base.source,
                confidence=base.confidence,
                provenance=dict(base.provenance or {}),
            )
        )

    def rollback(self, record_id: str, to_version: int | None = None) -> MemoryRecord:
        hist = self._versions.get(record_id) or []
        if not hist:
            raise KeyError(record_id)
        target = None
        if to_version is None:
            target = next((h for h in reversed(hist[:-1]) if h.status != "rolled_back"), hist[0])
        else:
            target = next((h for h in hist if h.version == int(to_version)), None)
        if not target:
            raise KeyError("version not found")
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
                "meta": r.meta,
            }
            for r in rows
        ]

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
            raise NotImplementedError("backend does not support forget")
        return bool(self.ltm.backend.forget(int(memory_id)))
