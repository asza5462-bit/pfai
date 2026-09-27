"""Authoritative TrainingEligibilityEngine — all gates must pass.

Never allows min_examples alone to start autonomous training.
If dataset growth since last trained version is 0 → NO_REAL_DATASET_GROWTH
(alias: NO_NEW_DATASET_GROWTH for compatibility).
"""
from __future__ import annotations

import time
from pathlib import Path
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

# Canonical zero-growth blocker (aliases kept in response).
ZERO_GROWTH_REASON = "NO_REAL_DATASET_GROWTH"
ZERO_GROWTH_ALIASES = ("NO_REAL_DATASET_GROWTH", "NO_NEW_DATASET_GROWTH")


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
        base_model_available: Callable[[], bool] | None = None,
        checkpoint_storage_available: Callable[[], bool] | None = None,
        checkpoint_root: str | None = None,
    ) -> None:
        self.triggers = triggers or TrainingTriggerPolicy()
        self.dataset_quality = dataset_quality or DatasetQualityGate()
        self.resources = resources or TrainingResourceManager()
        self._list_jobs = list_jobs or (lambda: [])
        self._eval_available = eval_available or (lambda: True)
        self._backend_available = backend_available or (
            lambda: bool(detect_runtime_capabilities(probe_inference=False).get("training_available"))
        )
        self._base_model_available = base_model_available
        self._checkpoint_storage_available = checkpoint_storage_available
        self._checkpoint_root = checkpoint_root

    def evaluate(
        self,
        *,
        accepted_rows: list[dict[str, Any]],
        dataset_growth: int,
        last_trained_dataset_id: str | None = None,
        accepted_count_override: int | None = None,
        owner_requested: bool = False,
        explicit_retrain: bool = False,
        regression_recovery: bool = False,
        performance_opportunity: bool = False,
        method: str = "lora",
        now: float | None = None,
        extra_probes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        gates: dict[str, Any] = {}
        blockers: list[str] = []
        probes = dict(extra_probes or {})

        accepted_n = int(
            accepted_count_override
            if accepted_count_override is not None
            else len(accepted_rows)
        )
        growth = int(dataset_growth or 0)
        owner_path = bool(owner_requested or explicit_retrain)

        # 1. Sufficient accepted examples
        min_examples = self.triggers.min_examples
        gates["minimum_accepted_examples"] = {
            "passed": accepted_n >= min_examples,
            "accepted": accepted_n,
            "required": min_examples,
        }
        gates["sufficient_accepted_examples"] = gates["minimum_accepted_examples"]["passed"]
        if not gates["sufficient_accepted_examples"]:
            blockers.append("INSUFFICIENT_ACCEPTED_EXAMPLES")

        # 2. Meaningful growth since last trained dataset (mandatory for non-owner)
        gates["dataset_growth"] = {
            "passed": growth > 0 and growth >= self.triggers.min_new_examples,
            "growth": growth,
            "required": self.triggers.min_new_examples,
            "last_trained_dataset_id": last_trained_dataset_id,
        }
        gates["meaningful_dataset_growth"] = gates["dataset_growth"]["passed"]
        if growth <= 0 and not (owner_path or regression_recovery):
            blockers.append(ZERO_GROWTH_REASON)

        # 3–5. Dataset quality (includes provenance, leakage, quality score)
        if accepted_rows:
            quality = self.dataset_quality.evaluate(accepted_rows)
        elif accepted_n > 0:
            quality = {
                "ok": True,
                "status": "DATASET_READY_COUNT_ONLY",
                "provenance_ok": True,
                "reasons": [],
                "note": "Rows not loaded; count override used for quantity gate only.",
            }
        else:
            quality = self.dataset_quality.evaluate([])
        gates["dataset_integrity"] = {
            "passed": bool(quality.get("ok")),
            "status": quality.get("status"),
            "reasons": list(quality.get("reasons") or []),
        }
        gates["dataset_quality_passed"] = bool(quality.get("ok"))
        gates["quality_status"] = quality.get("status")
        gates["provenance_ok"] = bool(quality.get("provenance_ok"))

        secret_violations = 0
        for row in accepted_rows:
            tags = (row.get("provenance") or {}).get("sanitizer_tags") or []
            if "secret_redacted" in tags and str(row.get("response") or "").count("[REDACTED]") >= 2:
                secret_violations += 1
        gates["no_secret_pii_violations"] = {
            "passed": secret_violations == 0,
            "violations": secret_violations,
        }
        gates["provenance_requirements_satisfied"] = {
            "passed": bool(quality.get("provenance_ok") or accepted_n == 0),
        }
        if not gates["dataset_quality_passed"]:
            blockers.append(str(quality.get("status") or "DATASET_QUALITY_FAILED"))
        if not gates["no_secret_pii_violations"]["passed"]:
            blockers.append("SECRET_OR_PII_VIOLATIONS")
        if accepted_n > 0 and not gates["provenance_requirements_satisfied"]["passed"]:
            blockers.append("MISSING_PROVENANCE")

        # 6. Evaluation suite available
        eval_ok = bool(self._eval_available())
        gates["evaluation_suite_available"] = {"passed": eval_ok}
        if not eval_ok:
            blockers.append("EVALUATION_SUITE_UNAVAILABLE")

        # 7. Compatible training backend / trainer
        backend_ok = bool(self._backend_available())
        gates["trainer_availability"] = {
            "passed": backend_ok,
            "detail": probes.get("trainer") or {},
        }
        gates["compatible_training_backend"] = backend_ok
        if not backend_ok:
            blockers.append("TRAINING_BACKEND_UNAVAILABLE")

        # 7b. Base model available
        if self._base_model_available is not None:
            base_ok = bool(self._base_model_available())
        else:
            base_ok = bool(probes.get("base_model_available", True))
        gates["base_model_availability"] = {
            "passed": base_ok,
            "detail": probes.get("base_model") or {},
        }
        if not base_ok:
            blockers.append("BASE_MODEL_UNAVAILABLE")

        # 7c. Checkpoint storage
        if self._checkpoint_storage_available is not None:
            ckpt_ok = bool(self._checkpoint_storage_available())
        elif self._checkpoint_root:
            try:
                root = Path(self._checkpoint_root)
                root.mkdir(parents=True, exist_ok=True)
                ckpt_ok = root.exists() and root.is_dir()
            except Exception:
                ckpt_ok = False
        else:
            ckpt_ok = bool(probes.get("checkpoint_storage_available", True))
        gates["checkpoint_storage_availability"] = {"passed": ckpt_ok}
        if not ckpt_ok:
            blockers.append("CHECKPOINT_STORAGE_UNAVAILABLE")

        # 8. Resource / time budget
        running = [
            j
            for j in (self._list_jobs() or [])
            if j.get("state") in ACTIVE_JOB_STATES
        ]
        admit = self.resources.admit(
            dataset_rows=accepted_n, method=method, running_jobs=len(running)
        )
        gates["resource_availability"] = {
            "passed": bool(admit.get("ok")),
            "admission": admit,
        }
        gates["resource_budget_available"] = bool(admit.get("ok"))
        gates["resource_admission"] = admit
        if not admit.get("ok"):
            blockers.append("RESOURCE_BUDGET_EXCEEDED")

        # 9. No conflicting active job
        gates["concurrent_job_lock"] = {
            "passed": len(running) == 0,
            "active_jobs": [j.get("job_id") for j in running],
        }
        gates["no_conflicting_training_job"] = len(running) == 0
        gates["active_jobs"] = [j.get("job_id") for j in running]
        if running:
            blockers.append("CONFLICTING_TRAINING_JOB")

        # 10. Trigger (schedule / growth / owner) — never min_examples alone
        trigger = self.triggers.evaluate(
            new_example_count=accepted_n,
            new_since_last_dataset=growth,
            owner_requested=owner_requested,
            explicit_retrain=explicit_retrain,
            regression_recovery=regression_recovery,
            performance_opportunity=performance_opportunity,
            now=now,
        )
        just = list(trigger.get("justification") or [])
        trigs = list(trigger.get("triggers") or [])
        gates["schedule_condition"] = {
            "passed": ("scheduled" in just) or ("scheduled" in trigs) or ("SCHEDULED" in trigs),
            "schedule_seconds": self.triggers.schedule_seconds,
            "detail": trigger,
        }
        gates["owner_manual_justification"] = {
            "passed": bool(owner_path),
            "owner_requested": owner_requested,
            "explicit_retrain": explicit_retrain,
        }
        gates["trigger"] = trigger
        gates["trigger_satisfied"] = bool(trigger.get("should_train"))
        if not gates["trigger_satisfied"]:
            blockers.append(str(trigger.get("reason") or "TRIGGER_NOT_MET"))

        mandatory_ok = (
            gates["sufficient_accepted_examples"]
            and gates["dataset_quality_passed"]
            and bool(gates["no_secret_pii_violations"].get("passed"))
            and bool(gates["provenance_requirements_satisfied"].get("passed"))
            and bool(gates["evaluation_suite_available"].get("passed"))
            and gates["compatible_training_backend"]
            and base_ok
            and ckpt_ok
            and gates["resource_budget_available"]
            and gates["no_conflicting_training_job"]
            and gates["trigger_satisfied"]
        )
        if owner_path:
            eligible = mandatory_ok
            blockers = [b for b in blockers if b not in ZERO_GROWTH_ALIASES]
        else:
            eligible = mandatory_ok and gates["meaningful_dataset_growth"]
            if growth <= 0 and ZERO_GROWTH_REASON not in blockers:
                blockers.append(ZERO_GROWTH_REASON)

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
            primary_reason = ZERO_GROWTH_REASON
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
            "reasons": list(uniq),
            "blockers": uniq,
            "gates": gates,
            "accepted_examples": accepted_n,
            "dataset_growth": growth,
            "last_trained_dataset_id": last_trained_dataset_id,
            "owner_path": owner_path,
            "at": now,
            "note": (
                "Authoritative eligibility — min_examples alone never enables autonomous training; "
                "growth==0 → NO_REAL_DATASET_GROWTH."
            ),
        }
