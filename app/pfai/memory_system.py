"""Memory System scaffold (PHASE 1). Implementation in PHASE 3.

Will wrap MemoryStore, CommandMemoryService, and Coding Academy memory —
not replace them.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.memory import MemoryScope, MemorySystemProtocol

__all__ = ["MemoryScope", "MemorySystemProtocol", "MemorySystem"]

PHASE = 3


class MemorySystem:
    """Placeholder facade — adapters land in PHASE 3."""

    def remember(
        self,
        scope: MemoryScope | str,
        content: str,
        *,
        source: str = "",
        confidence: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> int:
        raise NotImplementedError("MemorySystem adapters land in PHASE 3")

    def recall(
        self,
        query: str,
        *,
        scope: MemoryScope | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("MemorySystem adapters land in PHASE 3")

    def forget(self, memory_id: int) -> bool:
        raise NotImplementedError("MemorySystem adapters land in PHASE 3")
