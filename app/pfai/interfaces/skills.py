"""Skill Registry contracts — metadata + invoke boundary for Coding/Education/etc."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .tools import ToolPermission


@dataclass(frozen=True)
class Skill:
    """Registered skill metadata (implementation lives in later phases / adapters)."""

    name: str
    description: str
    permission: ToolPermission = ToolPermission.READ
    tags: tuple[str, ...] = ()
    version: str = "1"


@dataclass
class SkillContext:
    session_id: str = ""
    locale: str = "ar"
    mode: str = "general"
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    ok: bool
    output: Any = None
    reply: str = ""
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SkillRegistryProtocol(Protocol):
    def register(self, skill: Skill, handler: Any) -> None:
        ...

    def list_skills(self) -> list[Skill]:
        ...

    def get(self, name: str) -> Skill | None:
        ...

    def invoke(self, name: str, args: dict[str, Any] | None = None, *, ctx: SkillContext | None = None) -> SkillResult:
        ...
