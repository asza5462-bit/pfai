"""Self-check scaffold (PHASE 1). Implementation in PHASE 7."""
from __future__ import annotations

from pfai.interfaces.self_check import SelfCheckProtocol, SelfCheckReport

__all__ = ["SelfCheckProtocol", "SelfCheckReport", "SelfCheck"]

PHASE = 7


class SelfCheck:
    """Placeholder — health/tests inventory lands in PHASE 7."""

    def run_checks(self) -> SelfCheckReport:
        raise NotImplementedError("SelfCheck implementation lands in PHASE 7")
