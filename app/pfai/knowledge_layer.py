"""Knowledge Layer adapter — wraps vector store / curriculum search (PHASE 2 connect)."""
from __future__ import annotations

from typing import Any, Callable

from pfai.interfaces.knowledge import KnowledgeHit, KnowledgeLayerProtocol

__all__ = ["KnowledgeHit", "KnowledgeLayerProtocol", "KnowledgeLayer"]

PHASE = 2


class KnowledgeLayer:
    """Additive retrieval facade; does not replace RAGEngine."""

    def __init__(
        self,
        search_fn: Callable[..., list[dict[str, Any]]] | None = None,
        answer_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._search_fn = search_fn
        self._answer_fn = answer_fn

    def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        if self._search_fn is None:
            return []
        raw = self._search_fn(query, limit) or []
        hits: list[KnowledgeHit] = []
        for r in raw:
            hits.append(
                KnowledgeHit(
                    source=str(r.get("source") or r.get("id") or ""),
                    content=str(r.get("content") or r.get("excerpt") or ""),
                    score=float(r.get("score") or 0),
                    verified=bool(r.get("verified", True)),
                    meta={k: v for k, v in r.items() if k not in ("source", "content", "score", "verified")},
                )
            )
        return hits

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
