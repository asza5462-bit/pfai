"""Self-heal scaffold — bounded, reversible, owner-gated (implementation later)."""
from __future__ import annotations

from pfai.interfaces.self_check import (
    HealProposal,
    HealResult,
    SelfCheckReport,
    SelfHealProtocol,
)

__all__ = ["SelfHealProtocol", "SelfHeal", "HealProposal", "HealResult"]

PHASE = 8


class SelfHeal:
    """Placeholder — BackupManager / rollback adapters land in a later phase."""

    def propose_fix(self, report: SelfCheckReport) -> HealProposal:
        raise NotImplementedError("SelfHeal proposal lands in a later phase")

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> HealResult:
        if not approved:
            return HealResult(
                ok=False,
                proposal_id=proposal_id,
                message="owner approval required",
                meta={"needs_approval": True},
            )
        raise NotImplementedError("SelfHeal apply lands in a later phase")

    def test_fix(self, proposal_id: str) -> HealResult:
        raise NotImplementedError("SelfHeal test lands in a later phase")

    def rollback_fix(self, proposal_id: str) -> HealResult:
        raise NotImplementedError("SelfHeal rollback lands in a later phase")
