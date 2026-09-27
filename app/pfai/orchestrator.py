"""Orchestrator scaffold (PHASE 1).

Full coordination is PHASE 2. This module only re-exports contracts and
provides an explicit NotImplemented placeholder so imports are stable.
"""
from __future__ import annotations

from pfai.interfaces.orchestrator import OrchestratorProtocol
from pfai.interfaces.types import OrchestratorRequest, OrchestratorResult, TimelineStatus

__all__ = [
    "OrchestratorProtocol",
    "OrchestratorRequest",
    "OrchestratorResult",
    "TimelineStatus",
    "Orchestrator",
]

PHASE = 2  # implementation target phase


class Orchestrator:
    """Placeholder — do not use from API until PHASE 2 wires adapters."""

    def handle(self, request: OrchestratorRequest) -> OrchestratorResult:
        raise NotImplementedError("Orchestrator implementation lands in PHASE 2")
