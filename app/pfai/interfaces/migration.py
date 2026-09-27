"""Schema versioning and data migration framework contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


# Monotonic platform schema number. Bump only with an accompanying migration.
PFAI_SCHEMA_VERSION = 5


@dataclass
class Migration:
    version: int
    name: str
    upgrade: Callable[[Any], None] | None = None
    downgrade: Callable[[Any], None] | None = None
    description: str = ""


@dataclass
class MigrationReport:
    from_version: int
    to_version: int
    applied: list[str] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    dry_run: bool = False


@runtime_checkable
class MigrationRunnerProtocol(Protocol):
    def current_version(self) -> int:
        ...

    def target_version(self) -> int:
        ...

    def plan(self, target: int | None = None) -> list[Migration]:
        ...

    def run(self, target: int | None = None, *, dry_run: bool = True) -> MigrationReport:
        ...

    def register(self, migration: Migration) -> None:
        ...
