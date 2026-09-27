"""Runtime capability detection — re-exports PHASE 7 detector with PHASE 6 keys."""
from __future__ import annotations

from typing import Any

from .runtime_detector import TrainingRuntimeDetector, RuntimeAvailability, detect_runtime_capabilities

__all__ = [
    "TrainingRuntimeDetector",
    "RuntimeAvailability",
    "detect_runtime_capabilities",
]


def detect_training_runtime(**kwargs: Any) -> dict[str, Any]:
    """Alias used by control center APIs."""
    return detect_runtime_capabilities(**kwargs)
