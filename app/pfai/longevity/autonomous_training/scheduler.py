"""Durable autonomous training scheduler — never per-chat; restart-safe."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .eligibility import ACTIVE_JOB_STATES, TrainingEligibilityEngine
from .types import JobState


class DurableTrainingScheduler:
    """Persists schedule/eligibility state across process restarts.

    Triggers: dataset growth, scheduled interval, owner-approved manual.
    Never starts training from a chat message.
    """

    def __init__(
        self,
        root: str,
        *,
        eligibility: TrainingEligibilityEngine | None = None,
        list_jobs: Callable[[], list[dict[str, Any]]] | None = None,
        schedule_seconds: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "scheduler_state.json"
        self._lock = threading.RLock()
        self.eligibility = eligibility
        self._list_jobs = list_jobs or (lambda: [])
        self._state = self._load()
        if schedule_seconds is not None:
            self._state["schedule_seconds"] = int(schedule_seconds)

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "last_tick_at": 0.0,
            "last_decision": {},
            "last_job_id": None,
            "last_trained_dataset_id": None,
            "last_trained_accepted": 0,
            "schedule_seconds": 86400,
            "ticks": 0,
            "updated_at": time.time(),
        }

    def _save(self) -> None:
        self._state["updated_at"] = time.time()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = [
                j.get("job_id")
                for j in (self._list_jobs() or [])
                if j.get("state") in ACTIVE_JOB_STATES
            ]
            return {
                "ok": True,
                "last_tick_at": self._state.get("last_tick_at"),
                "last_decision": dict(self._state.get("last_decision") or {}),
                "last_job_id": self._state.get("last_job_id"),
                "last_trained_dataset_id": self._state.get("last_trained_dataset_id"),
                "last_trained_accepted": self._state.get("last_trained_accepted"),
                "schedule_seconds": self._state.get("schedule_seconds"),
                "ticks": self._state.get("ticks"),
                "active_jobs": running,
                "concurrent_blocked": bool(running),
                "per_chat_training": False,
                "durable": True,
            }

    def mark_trained(self, *, dataset_id: str, accepted: int, job_id: str | None = None) -> None:
        with self._lock:
            self._state["last_trained_dataset_id"] = dataset_id
            self._state["last_trained_accepted"] = int(accepted)
            if job_id:
                self._state["last_job_id"] = job_id
            self._save()

    def growth_since_last_trained(self, current_accepted: int) -> int:
        baseline = int(self._state.get("last_trained_accepted") or 0)
        return max(0, int(current_accepted) - baseline)

    def has_conflicting_job(self) -> bool:
        return any(j.get("state") in ACTIVE_JOB_STATES for j in (self._list_jobs() or []))

    def record_tick_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state["last_tick_at"] = time.time()
            self._state["last_decision"] = {
                k: decision.get(k)
                for k in (
                    "eligible",
                    "reason",
                    "status",
                    "dataset_growth",
                    "blockers",
                    "trained",
                    "job_id",
                )
            }
            self._state["ticks"] = int(self._state.get("ticks") or 0) + 1
            if decision.get("job_id"):
                self._state["last_job_id"] = decision.get("job_id")
            self._save()
            return self.status()

    def decide(
        self,
        *,
        accepted_rows: list[dict[str, Any]],
        owner_requested: bool = False,
        explicit_retrain: bool = False,
        regression_recovery: bool = False,
        method: str = "lora",
    ) -> dict[str, Any]:
        """Evaluate eligibility using growth since last *trained* dataset."""
        if self.eligibility is None:
            return {
                "eligible": False,
                "reason": "ELIGIBILITY_ENGINE_MISSING",
                "status": "TRAINING_BLOCKED",
            }
        if self.has_conflicting_job() and not owner_requested:
            return {
                "eligible": False,
                "reason": "CONFLICTING_TRAINING_JOB",
                "status": "TRAINING_BLOCKED",
                "blockers": ["CONFLICTING_TRAINING_JOB"],
            }
        growth = self.growth_since_last_trained(len(accepted_rows))
        decision = self.eligibility.evaluate(
            accepted_rows=accepted_rows,
            dataset_growth=growth,
            last_trained_dataset_id=self._state.get("last_trained_dataset_id"),
            owner_requested=owner_requested,
            explicit_retrain=explicit_retrain,
            regression_recovery=regression_recovery,
            method=method,
        )
        return decision


def normalize_job_lifecycle_state(state: str) -> str:
    """Map internal job states onto the Phase 10 lifecycle vocabulary."""
    s = (state or "").upper()
    if s in (
        JobState.TRAINING.value,
        JobState.RUNNING.value,
        JobState.PREPARING.value,
        JobState.DATA_VALIDATION.value,
        JobState.CHECKPOINTING.value,
        JobState.ACTIVATING.value,
    ):
        return "RUNNING"
    if s == JobState.EVALUATING.value:
        return "EVALUATING"
    if s in (JobState.CANARY.value, JobState.SHADOW.value):
        return "CANARY"
    if s in (JobState.COMPLETED.value, JobState.ACTIVE.value):
        return "ACCEPTED"
    if s == JobState.REJECTED.value:
        return "REJECTED"
    if s == JobState.ROLLED_BACK.value:
        return "ROLLED_BACK"
    if s == JobState.FAILED.value:
        return "FAILED"
    if s == JobState.CANCELLED.value:
        return "CANCELLED"
    if s == JobState.QUEUED.value:
        return "QUEUED"
    return s or "UNKNOWN"
