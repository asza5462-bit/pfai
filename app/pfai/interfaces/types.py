"""Shared Orchestrator request/result types (PHASE 1 contracts)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TimelineStatus:
    """User-visible progress step (maps to Command Chat timeline entries)."""

    status: str
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorRequest:
    """Normalized inbound task for the future Orchestrator layer.

    Existing `/chat/message` and `/coding/*` flows remain the public surface;
    adapters may construct this shape without changing those HTTP contracts.
    """

    goal: str
    session_id: str = ""
    user_id: str = ""
    mode: str = "general"  # general | coding_learn | coding_engineer | ops
    locale: str = "ar"
    context: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    require_owner_for_sensitive: bool = True


@dataclass
class OrchestratorResult:
    """Normalized outbound result from the Orchestrator layer."""

    ok: bool
    reply: str = ""
    timeline: list[TimelineStatus] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    needs_approval: bool = False
    approval_id: str | None = None
    plan_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
