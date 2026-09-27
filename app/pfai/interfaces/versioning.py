"""Versioning + rollback contracts for knowledge, config, skills, and schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class VersionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


@dataclass
class Provenance:
    source: str = ""
    actor: str = ""
    method: str = ""
    references: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeVersion:
    """Versioned knowledge unit with full audit metadata."""

    knowledge_id: str
    version: int
    content: str
    timestamp: str
    source: str
    confidence: float
    status: VersionStatus | str = VersionStatus.DRAFT
    provenance: Provenance = field(default_factory=Provenance)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigVersion:
    config_id: str
    version: int
    payload: dict[str, Any]
    timestamp: str
    status: VersionStatus | str = VersionStatus.DRAFT
    source: str = ""
    checksum: str = ""


@dataclass
class SkillVersion:
    skill_name: str
    version: str
    description: str = ""
    status: VersionStatus | str = VersionStatus.ACTIVE
    timestamp: str = ""
    changelog: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolVersion:
    tool_name: str
    version: str
    status: VersionStatus | str = VersionStatus.ACTIVE
    timestamp: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VersionedStoreProtocol(Protocol):
    def put_version(self, entity_type: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_active(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        ...

    def history(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        ...

    def rollback(self, entity_type: str, entity_id: str, to_version: int | str) -> dict[str, Any]:
        ...


@runtime_checkable
class KnowledgeVersioningProtocol(Protocol):
    def publish(self, record: KnowledgeVersion) -> KnowledgeVersion:
        ...

    def activate(self, knowledge_id: str, version: int, *, approved: bool = False) -> KnowledgeVersion:
        ...

    def rollback(self, knowledge_id: str, to_version: int) -> KnowledgeVersion:
        ...

    def history(self, knowledge_id: str) -> list[KnowledgeVersion]:
        ...
