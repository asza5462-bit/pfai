"""Training trigger evaluation."""
from __future__ import annotations

import os
import time
from typing import Any

from .types import TriggerKind


class TrainingTriggerPolicy:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        min_examples: int | None = None,
        schedule_seconds: int | None = None,
        max_runtime: int | None = None,
        max_resource_budget: int | None = None,
    ) -> None:
        env_enabled = (os.environ.get("TRAINING_ENABLED") or "true").lower() in ("1", "true", "yes")
        self.enabled = env_enabled if enabled is None else bool(enabled)
        self.min_examples = int(
            min_examples
            if min_examples is not None
            else os.environ.get("TRAINING_MIN_EXAMPLES", "5")
        )
        self.schedule_seconds = int(
            schedule_seconds
            if schedule_seconds is not None
            else os.environ.get("TRAINING_SCHEDULE", "86400")
        )
        self.max_runtime = int(
            max_runtime
            if max_runtime is not None
            else os.environ.get("TRAINING_MAX_RUNTIME", "3600")
        )
        self.max_resource_budget = int(
            max_resource_budget
            if max_resource_budget is not None
            else os.environ.get("TRAINING_MAX_RESOURCE_BUDGET", "1")
        )
        self._last_scheduled_at = 0.0

    def evaluate(
        self,
        *,
        new_example_count: int,
        owner_requested: bool = False,
        explicit_retrain: bool = False,
        regression_recovery: bool = False,
        performance_opportunity: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"should_train": False, "reason": "TRAINING_DISABLED", "triggers": []}
        now = time.time() if now is None else now
        triggers: list[str] = []
        if owner_requested:
            triggers.append(TriggerKind.OWNER_REQUESTED.value)
        if explicit_retrain:
            triggers.append(TriggerKind.EXPLICIT_RETRAIN.value)
        if regression_recovery:
            triggers.append(TriggerKind.REGRESSION_RECOVERY.value)
        if performance_opportunity:
            triggers.append(TriggerKind.PERFORMANCE_OPPORTUNITY.value)
        if new_example_count >= self.min_examples:
            triggers.append(TriggerKind.MIN_EXAMPLES.value)
        if self._last_scheduled_at and (now - self._last_scheduled_at) >= self.schedule_seconds:
            triggers.append(TriggerKind.SCHEDULED.value)
        elif not self._last_scheduled_at:
            # first schedule window opens after interval from init unless other triggers fire
            self._last_scheduled_at = now
        should = bool(triggers)
        return {
            "should_train": should,
            "triggers": triggers,
            "min_examples": self.min_examples,
            "new_example_count": new_example_count,
            "max_runtime": self.max_runtime,
            "max_resource_budget": self.max_resource_budget,
        }

    def mark_scheduled(self, now: float | None = None) -> None:
        self._last_scheduled_at = time.time() if now is None else now
