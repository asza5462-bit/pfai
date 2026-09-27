"""Future Compatibility Layer — assume today's tech may vanish in 20 years."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class CompatibilityReport:
    python_ok: bool = True
    dependencies_ok: bool = True
    schema_ok: bool = True
    providers_ok: bool = True
    storage_ok: bool = True
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CompatibilityLayerProtocol(Protocol):
    """Checks and adapters for upgrading runtime/deps/DBs/providers/OS/host."""

    def check(self) -> CompatibilityReport:
        ...

    def schema_version(self) -> int:
        ...

    def supported_provider_kinds(self) -> list[str]:
        ...

    def supported_storage_kinds(self) -> list[str]:
        ...
