"""Orchestrator coordination contract — implemented in PHASE 2."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import OrchestratorRequest, OrchestratorResult


@runtime_checkable
class OrchestratorProtocol(Protocol):
    """Coordinates Memory, Knowledge, Planner, ModelRouter, Tools, Skills, Eval.

    Must not bypass Owner Gate for sensitive tools.
    Must not auto-promote models or run production fine-tuning.
    """

    def handle(self, request: OrchestratorRequest) -> OrchestratorResult:
        ...
