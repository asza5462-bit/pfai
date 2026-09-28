"""PHASE 21 priority classes — interactive work must not starve behind training."""
from __future__ import annotations

from enum import IntEnum


class PriorityClass(IntEnum):
    OWNER_CRITICAL = 0
    USER_INTERACTIVE = 10
    USER_COMPLEX = 20
    AGENT_BACKGROUND = 30
    LEARNING = 40
    TRAINING = 50
    MAINTENANCE = 60

    @classmethod
    def from_name(cls, name: str) -> "PriorityClass":
        key = (name or "USER_INTERACTIVE").upper().strip()
        try:
            return cls[key]
        except KeyError:
            return cls.USER_INTERACTIVE


# Lower number = higher priority
PRIORITY_ORDER = sorted(PriorityClass, key=lambda p: int(p))
