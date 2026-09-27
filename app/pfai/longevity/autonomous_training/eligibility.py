"""Authoritative TrainingEligibilityEngine — all gates must pass.

Never allows min_examples alone to start autonomous training.
If dataset growth since last trained version is 0 → NO_NEW_DATASET_GROWTH.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .dataset_quality import DatasetQualityGate
from .resources import TrainingResourceManager
from .runtime import detect_runtime_capabilities
from .triggers import TrainingTriggerPolicy
from .types import JobState


# Job states considered "in flight" — block concurrent training.
ACTIVE_JOB_STATES = frozenset(
    {
        JobState.QUEUED.value,
        JobState.PREPARING.value,
        JobState.DATA_VALIDATION.value,
        JobState.TRAINING.value,
        JobState.RUNNING.value,
        JobState.CHECKPOINTING.value,
        JobState.EVALUATING.value,
        JobState.SHADOW.value,
        JobState.CANARY.value,
        JobState.ACTIVATING.value,
    }
)


class TrainingEligibilityEngine:
    """Single source of truth for whether autonomous/owner training may start."""

    def __init__(
        self,
        *,
        triggers: TrainingTriggerPolicy | None = None,
        dataset_quality: DatasetQualityGate | None = None,
        resources: TrainingResourceManager | None = None,
        list_jobs: Callable[[], list[dict[str, Any]]] | None = None,
        eval_available: Callable[[], bool] | None = None,
        backend_available: Callable[[], bool] | None = None,
    ) -> None:
        self.triggers = triggers or TrainingTriggerPolicy()
        self.dataset_quality = dataset_quality or DatasetQualityGate()
        self.resources = resources or TrainingResourceManager()
        self._list_jobs = list_jobs or (lambda: [])
        self._eval_available = eval_available or (lambda: True)
        self._backend_available = backend_available or (
            lambda: bool(detect_runtime_capabilities(probe_inference=False).get("training_available"))
        )

    def evaluate(
        self,
        *,
        accepted_rows: list[dict[str, Any]],
        dataset_growth: int,
        last_trained_dataset_id: str | None = None,
        owner_requested: bool = False,
        explicit_retrain: bool = False,
        regression_recovery: bool = False,
        performance_opportunity: bool = False,
        method: str = "lora",
        now: float | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        gates: dict[str, Any] = {}
        blockers: list[str] = []

        accepted_n = len(accepted_rows)
        growth = int(dataset_growth or 0)

        # 1. Sufficient accepted examples
        min_examples = self.triggers.min_examples
        gates["sufficient_accepted_examples"] = accepted_n >= min_examples
        if not gates["sufficient_accepted_examples"]:
            blockers.append("INSUFFICIENT_ACCEPTED_EXAMPLES")

        # 2. Meaningful growth since last trained dataset (mandatory for non-owner)
        gates["meaningful_dataset_growth"] = growth > 0 and growth >= self.triggers.min_new_examples
        gates["dataset_growth"] = growth
        gates["min_new_examples"] = self.triggers.min_new_examples
        if growth <= 0 and not (owner_requested or explicit_retrain or regression_recovery):
            blockers.append("NO_NEW_DATASET_GROWTH")

        # 3–5. Dataset quality (includes provenance, leakage, quality score)
        quality = self.dataset_quality.evaluate(accepted_rows)
        gates["dataset_quality_passed"] = bool(quality.get("ok"))
        gates["quality_status"] = quality.get("status")
        gates["provenance_ok"] = bool(quality.get("provenance_ok"))
        reasons = list(quality.get("reasons") or [])
        secret_pii_hit = any(
            r in ("DATASET_INVALID",) for r in reasons
        ) and not quality.get("ok")
        # Explicit secret/PII: scan sanitizer tags if present
        secret_violations = 0
        for row in accepted_rows:
            tags = (row.get("provenance") or {}).get("sanitizer_tags") or []
            if "secret_redacted" in tags and str(row.get("response") or "").count("[REDACTED]") >= 2:
                secret_violations += 1
        gates["no_secret_pii_violations"] = secret_violations == 0
        gates["provenance_requirements_satisfied"] = bool(quality.get("provenance_ok") or accepted_n == 0)
        if not gates["dataset_quality_passed"]:
            blockers.append(str(quality.get("status") or "DATASET_QUALITY_FAILED"))
        if not gates["no_secret_pii_violations"]:
            blockers.append("SECRET_OR_PII_VIOLATIONS")
        if accepted_n > 0 and not gates["provenance_requirements_satisfied"]:
            blockers.append("MISSING_PROVENANCE")

        # 6. Evaluation suite available
        eval_ok = bool(self._eval_available())
        gates["evaluation_suite_available"] = eval_ok
        if not eval_ok:
            blockers.append("EVALUATION_SUITE_UNAVAILABLE")

        # 7. Compatible training backend
        backend_ok = bool(self._backend_available())
        gates["compatible_training_backend"] = backend_ok
        if not backend_ok:
            blockers.append("TRAINING_BACKEND_UNAVAILABLE")

        # 8. Resource / time budget
        running = [
            j
            for j in (self._list_jobs() or [])
            if j.get("state") in ACTIVE_JOB_STATES
        ]
        admit = self.resources.admit(
            dataset_rows=accepted_n, method=method, running_jobs=len(running)
        )
        gates["resource_budget_available"] = bool(admit.get("ok"))
        gates["resource_admission"] = admit
        if not admit.get("ok"):
            blockers.append("RESOURCE_BUDGET_EXCEEDED")

        # 9. No conflicting active job
        gates["no_conflicting_training_job"] = len(running) == 0
        gates["active_jobs"] = [j.get("job_id") for j in running]
        if running:
            blockers.append("CONFLICTING_TRAINING_JOB")

        # 10. Trigger satisfied (schedule / growth / owner) — never min_examples alone
        trigger = self.triggers.evaluate(
            new_example_count=accepted_n,
            new_since_last_dataset=growth,
            owner_requested=owner_requested,
            explicit_retrain=explicit_retrain,
            regression_recovery=regression_recovery,
            performance_opportunity=performance_opportunity,
            now=now,
        )
        gates["trigger"] = trigger
        gates["trigger_satisfied"] = bool(trigger.get("should_train"))
        if not gates["trigger_satisfied"]:
            blockers.append(str(trigger.get("reason") or "TRIGGER_NOT_MET"))

        # Authoritative decision
        # Owner/explicit may bypass growth==0 but still need quality/backend/resources/no-conflict
        owner_path = bool(owner_requested or explicit_retrain)
        mandatory_ok = (
            gates["sufficient_accepted_examples"]
            and gates["dataset_quality_passed"]
            and gates["no_secret_pii_violations"]
            and gates["provenance_requirements_satisfied"]
            and gates["evaluation_suite_available"]
            and gates["compatible_training_backend"]
            and gates["resource_budget_available"]
            and gates["no_conflicting_training_job"]
            and gates["trigger_satisfied"]
        )
        if owner_path:
            eligible = mandatory_ok  # growth may be 0 for owner
            # Remove NO_NEW_DATASET_GROWTH from blockers for owner path reporting clarity
            blockers = [b for b in blockers if b != "NO_NEW_DATASET_GROWTH"]
        else:
            # Autonomous: also require meaningful growth
            eligible = mandatory_ok and gates["meaningful_dataset_growth"]
            if growth <= 0 and "NO_NEW_DATASET_GROWTH" not in blockers:
                blockers.append("NO_NEW_DATASET_GROWTH")

        # Deduplicate blockers preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for b in blockers:
            if b not in seen:
                seen.add(b)
                uniq.append(b)

        if eligible:
            primary_reason = "ELIGIBLE"
            status = "READY_FOR_TRAINING"
        elif growth <= 0 and not owner_path:
            primary_reason = "NO_NEW_DATASET_GROWTH"
            status = "TRAINING_BLOCKED"
        elif uniq:
            primary_reason = uniq[0]
            status = "TRAINING_BLOCKED"
        else:
            primary_reason = "TRIGGER_NOT_MET"
            status = "TRAINING_BLOCKED"

        return {
            "ok": True,
            "eligible": bool(eligible),
            "status": status,
            "reason": primary_reason,
            "blockers": uniq,
            "gates": gates,
            "accepted_examples": accepted_n,
            "dataset_growth": growth,
            "last_trained_dataset_id": last_trained_dataset_id,
            "owner_path": owner_path,
            "at": now,
            "note": (
                "Authoritative eligibility — min_examples alone never enables autonomous training; "
                "growth==0 → NO_NEW_DATASET_GROWTH."
            ),
        }
