"""Memory System contracts — unify MemoryStore / CommandMemory / CodingMemory."""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MemoryScope(str, Enum):
    """Logical memory namespaces over the shared SQLite MemoryStore."""

    SESSION = "session"
    COMMAND = "command"
    CODING = "coding"
    PREFERENCE = "preference"
    DECISION = "decision"
    CORRECTION = "correction"
    SYSTEM = "system"


@runtime_checkable
class MemorySystemProtocol(Protocol):
    """Facade over existing memory modules; does not replace MemoryStore."""

    def remember(
        self,
        scope: MemoryScope | str,
        content: str,
        *,
        source: str = "",
        confidence: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> int:
        ...

    def recall(
        self,
        query: str,
        *,
        scope: MemoryScope | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        ...

    def forget(self, memory_id: int) -> bool:
        ...
