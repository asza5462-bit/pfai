"""Self-check / Self-heal contracts — over BackupManager + tests (later phases)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SelfCheckReport:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SelfCheckProtocol(Protocol):
    def run_checks(self) -> SelfCheckReport:
        ...


@runtime_checkable
class SelfHealProtocol(Protocol):
    """Healing is always gated; never silent production model promotion."""

    def propose_fix(self, report: SelfCheckReport) -> dict[str, Any]:
        ...

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> dict[str, Any]:
        ...
