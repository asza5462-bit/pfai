"""Self-heal re-export — implementation lives in self_check.py (PHASE 2)."""
from __future__ import annotations

from pfai.self_check import HealProposal, HealResult, SelfHeal

__all__ = ["SelfHeal", "HealProposal", "HealResult", "SelfHealProtocol"]

PHASE = 8

from pfai.interfaces.self_check import SelfHealProtocol  # noqa: E402
