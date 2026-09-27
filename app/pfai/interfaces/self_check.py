"""Self-check / bounded Self-heal contracts.

Safe heal loop only:
  detect → diagnose → propose safe fix → test fix → rollback if failed
Dangerous irreversible changes are never auto-applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class HealStep(str, Enum):
    DETECT = "detect"
    DIAGNOSE = "diagnose"
    PROPOSE = "propose"
    APPLY_SAFE = "apply_safe"
    TEST = "test"
    ROLLBACK = "rollback"


@dataclass
class SelfCheckReport:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealProposal:
    proposal_id: str
    diagnosis: str
    safe: bool
    reversible: bool
    steps: list[str] = field(default_factory=list)
    risk: str = "low"  # low | medium | high
    requires_owner: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealResult:
    ok: bool
    proposal_id: str
    applied: bool = False
    tested: bool = False
    rolled_back: bool = False
    message: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SelfCheckProtocol(Protocol):
    def run_checks(self) -> SelfCheckReport:
        ...


@runtime_checkable
class SelfHealProtocol(Protocol):
    def propose_fix(self, report: SelfCheckReport) -> HealProposal:
        ...

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> HealResult:
        ...

    def test_fix(self, proposal_id: str) -> HealResult:
        ...

    def rollback_fix(self, proposal_id: str) -> HealResult:
        ...
