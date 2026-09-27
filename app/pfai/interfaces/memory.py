"""Long-term Memory Architecture contracts.

Memory is model-agnostic structured data. Changing the LLM must never require
rewriting or losing memory. Vector indexes are optional accelerators only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MemoryScope(str, Enum):
    """Logical namespaces used by existing command/coding facades."""

    SESSION = "session"
    COMMAND = "command"
    CODING = "coding"
    PREFERENCE = "preference"
    DECISION = "decision"
    CORRECTION = "correction"
    SYSTEM = "system"


class MemoryKind(str, Enum):
    """Long-term memory kinds for 20–30 year retention design."""

    EPISODIC = "episodic"  # interaction episodes / timelines
    SEMANTIC = "semantic"  # facts / concepts
    PROCEDURAL = "procedural"  # how-to / workflows
    USER_PREFERENCE = "user_preference"
    PROJECT_KNOWLEDGE = "project_knowledge"
    LEARNED_LESSON = "learned_lesson"
    VERIFIED_KNOWLEDGE = "verified_knowledge"
    INTERACTION_HISTORY = "interaction_history"


@dataclass
class MemoryRecord:
    """Portable memory unit — independent of any model weights or vendor."""

    record_id: str
    kind: MemoryKind | str
    content: str
    scope: MemoryScope | str = MemoryScope.SYSTEM
    source: str = ""
    confidence: float = 0.0
    version: int = 1
    status: str = "active"  # active | superseded | rolled_back | archived
    created_at: str = ""
    updated_at: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemorySystemProtocol(Protocol):
    """Facade over MemoryStore / CommandMemory / CodingMemory — not a replacement."""

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


@runtime_checkable
class LongTermMemoryProtocol(Protocol):
    """Kind-aware LTM surface for longevity (adapters land in later phases)."""

    def store(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def query(
        self,
        *,
        kind: MemoryKind | str | None = None,
        query: str = "",
        limit: int = 20,
    ) -> list[MemoryRecord]:
        ...

    def supersede(self, record_id: str, new_content: str, *, source: str = "") -> MemoryRecord:
        ...

    def rollback(self, record_id: str, to_version: int | None = None) -> MemoryRecord:
        ...

    def export_records(self, *, kind: MemoryKind | str | None = None) -> list[dict[str, Any]]:
        ...
