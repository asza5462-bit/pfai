"""Self-heal scaffold (PHASE 1). Implementation in PHASE 8.

All fixes require Owner approval; never silent production promotion / fine-tune.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.self_check import SelfCheckReport, SelfHealProtocol

__all__ = ["SelfHealProtocol", "SelfHeal"]

PHASE = 8


class SelfHeal:
    """Placeholder — BackupManager / rollback adapters land in PHASE 8."""

    def propose_fix(self, report: SelfCheckReport) -> dict[str, Any]:
        raise NotImplementedError("SelfHeal proposal lands in PHASE 8")

    def apply_fix(self, proposal_id: str, *, approved: bool = False) -> dict[str, Any]:
        if not approved:
            return {"ok": False, "error": "owner approval required", "needs_approval": True}
        raise NotImplementedError("SelfHeal apply lands in PHASE 8")
