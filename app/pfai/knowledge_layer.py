"""Knowledge Layer scaffold (PHASE 1). Implementation in PHASE 3.

Wraps RAGEngine / vector store / coding knowledge JSON — additive only.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.knowledge import KnowledgeHit, KnowledgeLayerProtocol

__all__ = ["KnowledgeHit", "KnowledgeLayerProtocol", "KnowledgeLayer"]

PHASE = 3


class KnowledgeLayer:
    """Placeholder — retrieval adapters land in PHASE 3."""

    def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        raise NotImplementedError("KnowledgeLayer adapters land in PHASE 3")

    def answer(self, question: str, *, limit: int = 5) -> dict[str, Any]:
        raise NotImplementedError("KnowledgeLayer adapters land in PHASE 3")
