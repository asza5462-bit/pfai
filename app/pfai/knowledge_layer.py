"""Knowledge Layer — versioned knowledge + store/curriculum search (PHASE 3)."""
from __future__ import annotations

import time
from typing import Any, Callable

from pfai.interfaces.knowledge import KnowledgeHit, KnowledgeLayerProtocol
from pfai.interfaces.versioning import KnowledgeVersion, Provenance, VersionStatus

__all__ = ["KnowledgeHit", "KnowledgeLayerProtocol", "KnowledgeLayer"]

PHASE = 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class KnowledgeLayer:
    """Retrieval facade over vector store, versioned knowledge, and optional curriculum.

    Does not replace RAGEngine. Publish/history/rollback delegate to KnowledgeVersionStore
    when provided.
    """

    def __init__(
        self,
        search_fn: Callable[..., list[dict[str, Any]]] | None = None,
        answer_fn: Callable[..., dict[str, Any]] | None = None,
        *,
        version_store: Any | None = None,
        curriculum_search: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self._search_fn = search_fn
        self._answer_fn = answer_fn
        self.version_store = version_store
        self._curriculum_search = curriculum_search

    def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        hits: list[KnowledgeHit] = []
        q = (query or "").strip().lower()

        # 1) Active versioned knowledge (authoritative curated facts)
        if self.version_store is not None and hasattr(self.version_store, "search_active"):
            for r in self.version_store.search_active(query, limit=limit) or []:
                hits.append(
                    KnowledgeHit(
                        source=str(r.get("knowledge_id") or r.get("source") or "knowledge_version"),
                        content=str(r.get("content") or ""),
                        score=float(r.get("score") or 1.0),
                        verified=True,
                        meta={
                            "origin": "knowledge_version",
                            "knowledge_id": r.get("knowledge_id"),
                            "version": r.get("version"),
                        },
                    )
                )
        elif self.version_store is not None and q:
            # Fallback: scan active rows via history listing helpers if present
            active_fn = getattr(self.version_store, "list_active", None)
            if callable(active_fn):
                for kv in active_fn(limit=max(limit * 5, 20)) or []:
                    content = getattr(kv, "content", "") or ""
                    if q in content.lower():
                        hits.append(
                            KnowledgeHit(
                                source=str(getattr(kv, "knowledge_id", "knowledge_version")),
                                content=content,
                                score=1.0,
                                verified=True,
                                meta={
                                    "origin": "knowledge_version",
                                    "knowledge_id": getattr(kv, "knowledge_id", ""),
                                    "version": getattr(kv, "version", 0),
                                },
                            )
                        )

        # 2) Legacy / vector store
        if self._search_fn is not None:
            raw = self._search_fn(query, limit) or []
            for r in raw:
                hits.append(
                    KnowledgeHit(
                        source=str(r.get("source") or r.get("id") or ""),
                        content=str(r.get("content") or r.get("excerpt") or ""),
                        score=float(r.get("score") or 0),
                        verified=bool(r.get("verified", True)),
                        meta={
                            "origin": "store",
                            **{k: v for k, v in r.items() if k not in ("source", "content", "score", "verified", "excerpt")},
                        },
                    )
                )

        # 3) Optional curriculum snippets
        if self._curriculum_search is not None:
            for r in self._curriculum_search(query, limit) or []:
                hits.append(
                    KnowledgeHit(
                        source=str(r.get("source") or r.get("id") or "curriculum"),
                        content=str(r.get("content") or r.get("excerpt") or ""),
                        score=float(r.get("score") or 0.5),
                        verified=bool(r.get("verified", True)),
                        meta={"origin": "curriculum", **{k: v for k, v in r.items() if k not in ("source", "content", "score")}},
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: max(1, int(limit))]

    def answer(self, question: str, *, limit: int = 5) -> dict[str, Any]:
        if self._answer_fn is not None:
            return self._answer_fn(question, limit=limit)
        hits = self.search(question, limit=limit)
        if not hits:
            return {"answer": "insufficient evidence", "hits": [], "sources": []}
        return {
            "answer": hits[0].content,
            "hits": [h.__dict__ for h in hits],
            "sources": [h.source for h in hits],
        }

    # --- Versioned knowledge surface (PHASE 3) ---
    def publish(
        self,
        knowledge_id: str,
        content: str,
        *,
        source: str = "manual",
        confidence: float = 0.8,
        actor: str = "",
        meta: dict[str, Any] | None = None,
    ) -> KnowledgeVersion:
        if self.version_store is None:
            raise NotImplementedError("version_store required for publish")
        return self.version_store.publish(
            KnowledgeVersion(
                knowledge_id=knowledge_id,
                version=0,
                content=content,
                timestamp=_now(),
                source=source,
                confidence=confidence,
                status=VersionStatus.ACTIVE,
                provenance=Provenance(source=source, actor=actor, method="knowledge_layer.publish"),
                meta=dict(meta or {}),
            )
        )

    def history(self, knowledge_id: str) -> list[KnowledgeVersion]:
        if self.version_store is None:
            raise NotImplementedError("version_store required for history")
        return self.version_store.history(knowledge_id)

    def active(self, knowledge_id: str) -> KnowledgeVersion | None:
        if self.version_store is None:
            raise NotImplementedError("version_store required for active")
        return self.version_store.active(knowledge_id)

    def rollback(self, knowledge_id: str, to_version: int) -> KnowledgeVersion:
        if self.version_store is None:
            raise NotImplementedError("version_store required for rollback")
        return self.version_store.rollback(knowledge_id, int(to_version))
