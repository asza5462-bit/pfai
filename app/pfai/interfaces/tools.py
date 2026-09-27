"""Tool permission levels for Orchestrator / ToolRouter unification."""
from __future__ import annotations

from enum import Enum


class ToolPermission(str, Enum):
    """Risk ladder for tools and skills.

    Existing ToolRouter `risk` / `requires_approval` map roughly as:
      read              → READ
      write (non-prod)  → LOW_RISK_WRITE
      sensitive ops     → HIGH_RISK_WRITE or PRODUCTION
      secrets / delete  → SECRETS / DATA_DELETE (always Owner-gated)
    """

    READ = "read"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    PRODUCTION = "production"
    SECRETS = "secrets"
    DATA_DELETE = "data_delete"

    def requires_owner_gate(self) -> bool:
        return self in {
            ToolPermission.HIGH_RISK_WRITE,
            ToolPermission.PRODUCTION,
            ToolPermission.SECRETS,
            ToolPermission.DATA_DELETE,
        }
