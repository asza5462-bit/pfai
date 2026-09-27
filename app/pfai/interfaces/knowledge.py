"""Knowledge / RAG contracts — wrap VectorStore, RAGEngine, coding knowledge."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class KnowledgeHit:
    source: str
    content: str
    score: float = 0.0
    verified: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class KnowledgeLayerProtocol(Protocol):
    """Retrieval surface; implementations adapt rag.py / vector store / curriculum."""

    def search(self, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        ...

    def answer(self, question: str, *, limit: int = 5) -> dict[str, Any]:
        """Return answer + sources; must not invent citations."""
        ...
