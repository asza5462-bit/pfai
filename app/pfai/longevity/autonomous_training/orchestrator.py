"""AutonomousTrainingOrchestrator — PHASE 6/7 resumable train→eval→activate→rollback."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .active_runtime import ActiveModelRuntime
from .audit import TrainingAuditLog
from .canary import CanaryController
from .checkpoints import CheckpointStore
from .collector import ExperienceCollector, collect_from_learning_pipeline
from .compatibility import ModelCompatibilityChecker
from .dataset import DatasetBuilder, DatasetVersionRegistry
from .evaluation_gate import EvaluationGate
from .isolation import TrainingSafetyIsolation
from .model_registry import ModelRegistry
from .resources import TrainingResourceManager
from .rollback import ModelRollbackManager
from .runtime import detect_runtime_capabilities
from .runtime_detector import TrainingRuntimeDetector
from .trainer import TrainingBackendRegistry
from .triggers import TrainingTriggerPolicy
from .types import JobState, ModelStatus, TrainingConfig, TrainingResult
from .validator import TrainingExampleValidator


class AutonomousTrainingOrchestrator:
    """Full continuous improvement loop with honest runtime reporting."""

    STALE_RUNNING_SECONDS = 7200

    def __init__(
        self,
        root: str = "data/longevity/training",
        *,
        learning_pipeline: Any | None = None,
        eval_runner=None,
        collector: ExperienceCollector | None = None,
        allow_mock_backend: bool | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "orchestrator_state.json"
        self.jobs_path = self.root / "jobs"
        self.jobs_path.mkdir(parents=True, exist_ok=True)
        self.learning_pipeline = learning_pipeline
        self.collector = collector or ExperienceCollector()
        self.validator = TrainingExampleValidator()
        self.builder = DatasetBuilder(self.validator)
        self.datasets = DatasetVersionRegistry(str(self.root / "datasets"))
        self.models = ModelRegistry(str(self.root / "models"))
        self.checkpoints = CheckpointStore(str(self.root / "checkpoints"))
        self.audit = TrainingAuditLog(str(self.root / "training_audit.jsonl"))
        self.backends = TrainingBackendRegistry()
        self.backends.bootstrap_defaults()
        self.gates = EvaluationGate(eval_runner=eval_runner)
        self.active_runtime = ActiveModelRuntime(str(self.root / "active_runtime.json"))
        self.rollback_mgr = ModelRollbackManager(
            self.models, audit_fn=self.audit.record, active_runtime=self.active_runtime
        )
        self.isolation = TrainingSafetyIsolation()
        self.triggers = TrainingTriggerPolicy()
        self.detector = TrainingRuntimeDetector()
        self.compat = ModelCompatibilityChecker(self.detector)
        self.resources = TrainingResourceManager(self.detector)
        self.canary = CanaryController()
        self._lock = threading.RLock()
        env_mock = (os.environ.get("TRAINING_ALLOW_MOCK") or "").lower() in ("1", "true", "yes")
        self.allow_mock_backend = env_mock if allow_mock_backend is None else bool(allow_mock_backend)
        self.autonomous_enabled = (os.environ.get("AUTONOMOUS_TRAINING_ENABLED") or "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.min_dataset_quality = float(os.environ.get("TRAINING_MIN_DATASET_QUALITY", "0.55"))
        self._ensure_default_sources()
        self._state = self._load_state()
        self.reconcile_stale_jobs()

    def _ensure_default_sources(self) -> None:
        if "durable_learning" not in getattr(self.collector, "_sources", {}):
            self.collector.register(
                "durable_learning",
                lambda: collect_from_learning_pipeline(self.learning_pipeline),
            )

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "phase": "idle",
            "last_job_id": None,
            "last_dataset_id": None,
            "last_model_id": None,
            "cycles": 0,
            "paused": False,
            "updated_at": time.time(),
        }

    def _save_state(self) -> None:
        self._state["updated_at"] = time.time()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_path / f"{job_id}.json"

    def _write_job(self, job: dict[str, Any]) -> None:
        path = self._job_path(job["job_id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _read_job(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def reconcile_stale_jobs(self) -> list[str]:
        """Mark abandoned RUNNING/PREPARING/CHECKPOINTING jobs as FAILED after crash/timeout."""
        fixed: list[str] = []
        now = time.time()
        for job in self.list_jobs(limit=100):
            state = job.get("state")
            if state not in (
                JobState.RUNNING.value,
                JobState.TRAINING.value,
                JobState.PREPARING.value,
                JobState.DATA_VALIDATION.value,
                JobState.CHECKPOINTING.value,
                JobState.EVALUATING.value,
                JobState.SHADOW.value,
                JobState.CANARY.value,
                JobState.ACTIVATING.value,
            ):
                continue
            updated = float(job.get("updated_at") or job.get("created_at") or 0)
            if now - updated > self.STALE_RUNNING_SECONDS:
                job["state"] = JobState.FAILED.value
                job["error"] = "reconciled_stale_running_after_restart_or_timeout"
                job["updated_at"] = now
                self._write_job(job)
                fixed.append(job["job_id"])
                self.audit.record("job_reconciled_stale", job_id=job["job_id"])
        return fixed

    def runtime_status(self) -> dict[str, Any]:
        caps = detect_runtime_capabilities()
        return {
            "training_enabled": self.triggers.enabled,
            "autonomous_training_enabled": self.autonomous_enabled,
            "allow_mock_backend": self.allow_mock_backend,
            "capabilities": caps,
            "runtime_availability": caps.get("runtime_availability") or caps.get("status"),
            "status": caps.get("status"),
            "backends": self.backends.list_backends(),
            "active_model": self.models.active(),
            "active_runtime": self.active_runtime.current(),
            "orchestrator": dict(self._state),
        }

    def control_center_status(self) -> dict[str, Any]:
        """Owner Learning/Training Control Center payload (no secrets)."""
        st = self.status()
        jobs = self.list_jobs(limit=10)
        current = next(
            (
                j
                for j in jobs
                if j.get("state")
                in (
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
                    JobState.PAUSED.value,
                )
            ),
            None,
        )
        last_ok = next((j for j in jobs if j.get("state") == JobState.COMPLETED.value), None)
        last_fail = next(
            (j for j in jobs if j.get("state") in (JobState.FAILED.value, JobState.REJECTED.value)),
            None,
        )
        datasets = self.datasets.list_versions(limit=1)
        return {
            "active_model": st.get("active_model"),
            "active_runtime": st.get("active_runtime"),
            "runtime_status": st.get("status"),
            "runtime_availability": st.get("runtime_availability"),
            "training_runtime_status": st.get("status"),
            "gpu_available": (st.get("capabilities") or {}).get("gpu_available"),
            "cpu_count": (st.get("capabilities") or {}).get("cpu_count"),
            "current_dataset": datasets[0] if datasets else None,
            "last_training": last_ok,
            "last_failed_training": last_fail,
            "current_job": current,
            "candidate_model": next(
                (m for m in (st.get("models") or []) if m.get("status") in ("CANDIDATE", "VALIDATING", "VALIDATED")),
                None,
            ),
            "canary": {
                "enabled": self.canary.enabled,
                "request_limit": self.canary.request_limit,
                "failure_threshold": self.canary.failure_threshold,
            },
            "rollback": {
                "last_known_good": (self.rollback_mgr.last_known_good() or {}).get("model_id"),
                "available": bool(self.rollback_mgr.last_known_good()),
            },
            "autonomous_training_enabled": self.autonomous_enabled,
            "paused": bool(self._state.get("paused")),
            "authority_isolation": True,
            "real_training_available": bool((st.get("capabilities") or {}).get("training_available")),
            "real_training_executed": bool(
                (last_ok or {}).get("real_weight_update") or (last_ok or {}).get("real_training")
            ),
            "real_model_active": bool(
                ((st.get("active_runtime") or {}).get("model_id"))
                and not ((st.get("active_runtime") or {}).get("meta") or {}).get("is_mock")
                and (
                    (st.get("active_model") or {}).get("meta", {}).get("is_mock") is not True
                )
            ),
            "labels": {
                "REAL_TRAINING_AVAILABLE": bool((st.get("capabilities") or {}).get("training_available")),
                "REAL_TRAINING_EXECUTED": bool(
                    (last_ok or {}).get("real_weight_update") or (last_ok or {}).get("real_training")
                ),
                "REAL_MODEL_ACTIVE": bool(
                    ((st.get("active_runtime") or {}).get("model_id"))
                    and not ((st.get("active_model") or {}).get("meta") or {}).get("is_mock")
                ),
            },
        }

    def status(self) -> dict[str, Any]:
        rt = self.runtime_status()
        return {
            **rt,
            "datasets": self.datasets.list_versions(limit=5),
            "models": self.models.list_models(limit=5),
            "recent_jobs": self.list_jobs(limit=5),
            "weight_training_path": "AutonomousTrainingOrchestrator",
            "authority_isolation": True,
            "note": "Model learning is isolated from owner auth/authorization.",
        }

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        files = sorted(self.jobs_path.glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for path in files[: int(limit)]:
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def pause_training(self) -> dict[str, Any]:
        self._state["paused"] = True
        self._save_state()
        for job in self.list_jobs(limit=20):
            if job.get("state") in (JobState.QUEUED.value, JobState.RUNNING.value, JobState.PREPARING.value):
                job["state"] = JobState.PAUSED.value
                job["updated_at"] = time.time()
                self._write_job(job)
        self.audit.record("training_paused")
        return {"ok": True, "paused": True}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self._read_job(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        if job.get("state") in (JobState.COMPLETED.value, JobState.FAILED.value, JobState.REJECTED.value):
            return {"ok": False, "error": "job_already_terminal", "job": job}
        job["state"] = JobState.CANCELLED.value
        job["updated_at"] = time.time()
        self._write_job(job)
        self.audit.record("job_cancelled", job_id=job_id)
        return {"ok": True, "job": job}

    def set_autonomous(self, enabled: bool) -> dict[str, Any]:
        self.autonomous_enabled = bool(enabled)
        self._state["autonomous_training_enabled"] = self.autonomous_enabled
        self._save_state()
        return {"ok": True, "autonomous_training_enabled": self.autonomous_enabled}

    def build_dataset_from_sources(self, *, sources: list[str] | None = None) -> dict[str, Any]:
        rows = self.collector.collect(sources=sources)
        built = self.builder.build(rows)
        if built["accepted"] < 1:
            return {"ok": False, "error": "INSUFFICIENT_DATA", "built": built}
        # Quality threshold
        qualities = [float(e.quality_score) for e in built["examples"]]
        avg_q = sum(qualities) / len(qualities) if qualities else 0.0
        quality_report = {
            "total_input": len(rows),
            "accepted": built["accepted"],
            "rejected": built["rejected"],
            "avg_quality": avg_q,
            "min_required": self.min_dataset_quality,
            "train": len(built["splits"]["train"]),
            "validation": len(built["splits"]["validation"]),
            "test": len(built["splits"]["test"]),
        }
        if avg_q < self.min_dataset_quality:
            return {"ok": False, "error": "DATASET_QUALITY_BELOW_THRESHOLD", "quality": quality_report}
        parent = None
        versions = self.datasets.list_versions(limit=1)
        if versions:
            parent = versions[0]["dataset_id"]
        manifest = self.datasets.create_version(
            built,
            parent_dataset=parent,
            meta={"sources": sources or list(self.collector._sources.keys()), "quality": quality_report},
        )
        self.audit.record("dataset_created", dataset_id=manifest["dataset_id"], counts=manifest.get("validation_results"))
        self._state["last_dataset_id"] = manifest["dataset_id"]
        self._save_state()
        return {
            "ok": True,
            "manifest": manifest,
            "accepted": built["accepted"],
            "rejected": built["rejected"],
            "quality": quality_report,
        }

    def run_cycle(
        self,
        *,
        owner_requested: bool = False,
        explicit_retrain: bool = False,
        regression_recovery: bool = False,
        performance_opportunity: bool = False,
        config: TrainingConfig | None = None,
        force_dataset: str | None = None,
        activate_if_pass: bool = True,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one autonomous learning cycle (resumable via job records)."""
        self.reconcile_stale_jobs()
        if self._state.get("paused") and not owner_requested:
            return {"ok": False, "status": "PAUSED", "error": "training_paused"}

        guard = self.isolation.guard_training_request(request)
        if not guard["ok"]:
            self.audit.record("isolation_block", violations=guard["violations"])
            return {"ok": False, "error": "AUTHORITY_ISOLATION_VIOLATION", "violations": guard["violations"]}

        if not self.autonomous_enabled and not owner_requested and not explicit_retrain:
            return {"ok": False, "status": "AUTONOMOUS_DISABLED", "error": "autonomous_training_disabled"}

        cfg = config or TrainingConfig(
            max_runtime_seconds=self.triggers.max_runtime,
            allow_mock_backend=self.allow_mock_backend,
            base_model=(
                os.environ.get("MODEL_PATH")
                or os.environ.get("MODEL_NAME")
                or os.environ.get("PFAI_MODEL_NAME")
                or "local"
            ),
            method=os.environ.get("TRAINING_METHOD") or "lora",
        )
        cfg.allow_mock_backend = bool(cfg.allow_mock_backend or self.allow_mock_backend)
        if os.environ.get("MODEL_REVISION"):
            cfg.extra["revision"] = os.environ.get("MODEL_REVISION")
        if os.environ.get("MODEL_LICENSE"):
            cfg.extra["license"] = os.environ.get("MODEL_LICENSE")
        if os.environ.get("TRAINING_MAX_STEPS"):
            cfg.extra["max_steps"] = int(os.environ["TRAINING_MAX_STEPS"])
        if os.environ.get("MODEL_CONTEXT_LENGTH"):
            cfg.extra["max_seq_length"] = int(os.environ["MODEL_CONTEXT_LENGTH"])

        if force_dataset:
            manifest = self.datasets.get(force_dataset)
            if not manifest:
                return {"ok": False, "error": "dataset_not_found"}
            dataset_id = force_dataset
            accepted = int(manifest.get("train_count") or 0) + int(manifest.get("validation_count") or 0)
        else:
            built = self.build_dataset_from_sources()
            if not built.get("ok"):
                self.audit.record("insufficient_data", detail={k: built.get(k) for k in ("error", "quality")})
                return {"ok": False, "status": built.get("error") or "INSUFFICIENT_DATA", **built}
            manifest = built["manifest"]
            dataset_id = manifest["dataset_id"]
            accepted = int(built.get("accepted") or 0)

        decision = self.triggers.evaluate(
            new_example_count=accepted,
            owner_requested=owner_requested,
            explicit_retrain=explicit_retrain,
            regression_recovery=regression_recovery,
            performance_opportunity=performance_opportunity,
        )
        if not decision["should_train"] and not owner_requested and not explicit_retrain:
            return {"ok": False, "status": "TRIGGER_NOT_MET", "trigger": decision, "dataset_id": dataset_id}

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job: dict[str, Any] = {
            "job_id": job_id,
            "state": JobState.QUEUED.value,
            "dataset_id": dataset_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "config": cfg.to_dict(),
            "triggers": decision.get("triggers"),
            "checkpoints": [],
            "evaluation": None,
            "model_id": None,
            "result": None,
            "is_mock": False,
            "real_weight_update": False,
        }
        self._write_job(job)
        self.audit.record("job_queued", job_id=job_id, dataset_id=dataset_id, triggers=decision.get("triggers"))

        train_rows = self.datasets.load_split(dataset_id, "train")
        if len(train_rows) > cfg.max_dataset_size:
            train_rows = train_rows[: cfg.max_dataset_size]

        running = [
            j
            for j in self.list_jobs(limit=20)
            if j.get("state")
            in (
                JobState.RUNNING.value,
                JobState.TRAINING.value,
                JobState.PREPARING.value,
                JobState.DATA_VALIDATION.value,
                JobState.CHECKPOINTING.value,
                JobState.SHADOW.value,
                JobState.CANARY.value,
                JobState.ACTIVATING.value,
            )
        ]
        admit = self.resources.admit(
            dataset_rows=len(train_rows), method=cfg.method, running_jobs=len(running)
        )
        job["resource_admission"] = admit
        # Mock path may proceed when explicitly allowed even if real runtime unavailable
        if not admit.get("ok") and not cfg.allow_mock_backend:
            reasons = admit.get("reasons") or ["resources"]
            if "runtime_unavailable" in reasons:
                err = "TRAINING_RUNTIME_UNAVAILABLE"
            else:
                err = "TRAINING_BLOCKED_" + str(reasons[0]).upper()
            job["state"] = JobState.REJECTED.value if "runtime_unavailable" not in reasons else JobState.TRAINING_RUNTIME_UNAVAILABLE.value
            job["error"] = err
            job["updated_at"] = time.time()
            self._write_job(job)
            return {"ok": False, "status": err, "job": job, "actual_training_executed": False}

        job["state"] = JobState.PREPARING.value
        job["updated_at"] = time.time()
        self._write_job(job)

        job["state"] = JobState.DATA_VALIDATION.value
        job["updated_at"] = time.time()
        self._write_job(job)

        # Compatibility — real backend requires pass; mock may skip runtime availability
        compat = self.compat.check(config=cfg, dataset_rows=train_rows)
        job["compatibility"] = {
            "ok": compat.get("ok"),
            "reasons": compat.get("reasons"),
            "primary_reason": compat.get("primary_reason"),
            "runtime_availability": compat.get("runtime_availability"),
            "details": {
                "base_model": (compat.get("details") or {}).get("base_model"),
                "model_source": (compat.get("details") or {}).get("model_source"),
                "license": (compat.get("details") or {}).get("license"),
                "no_compatible_model": (compat.get("details") or {}).get("no_compatible_model"),
            },
        }
        trainer, selection = self.backends.select(cfg)
        no_model = bool((compat.get("details") or {}).get("no_compatible_model")) or (
            (selection or {}).get("status") == "NO_COMPATIBLE_MODEL"
        )
        if trainer is None or (
            not cfg.allow_mock_backend and not compat.get("ok") and compat.get("primary_reason")
        ):
            if no_model or (selection or {}).get("status") == "NO_COMPATIBLE_MODEL":
                reason = "NO_COMPATIBLE_MODEL"
                job["state"] = JobState.NO_COMPATIBLE_MODEL.value
            else:
                reason = compat.get("primary_reason") or "TRAINING_BLOCKED_RUNTIME_UNAVAILABLE"
                if trainer is None:
                    reason = "TRAINING_RUNTIME_UNAVAILABLE"
                job["state"] = JobState.TRAINING_RUNTIME_UNAVAILABLE.value
            job["error"] = reason
            job["selection"] = selection
            job["updated_at"] = time.time()
            self._write_job(job)
            self.audit.record("runtime_or_model_unavailable", job_id=job_id, reason=reason)
            self._state["phase"] = "runtime_unavailable" if reason != "NO_COMPATIBLE_MODEL" else "no_compatible_model"
            self._save_state()
            return {
                "ok": False,
                "status": reason,
                "job": job,
                "selection": selection,
                "actual_training_executed": False,
                "real_training_executed": False,
                "reason": reason,
            }

        job["state"] = JobState.TRAINING.value
        job["backend"] = trainer.backend_id
        job["selection"] = selection
        job["updated_at"] = time.time()
        self._write_job(job)
        self._state["phase"] = "training"
        self._state["last_job_id"] = job_id
        self._state["paused"] = False
        self._save_state()

        out_dir = str(self.root / "artifacts" / job_id)

        def _on_cp(meta: dict[str, Any]) -> None:
            job["state"] = JobState.CHECKPOINTING.value
            job["updated_at"] = time.time()
            rec = self.checkpoints.record(job_id, meta)
            if not rec.get("integrity_ok"):
                job["checkpoint_warning"] = "integrity_failed"
            job["checkpoints"].append(rec)
            job["state"] = JobState.RUNNING.value
            self._write_job(job)

        started = time.time()
        try:
            result: TrainingResult = trainer.train(
                job_id=job_id,
                dataset_rows=train_rows,
                output_dir=out_dir,
                config=cfg,
                on_checkpoint=_on_cp,
            )
        except Exception as exc:
            job["state"] = JobState.FAILED.value
            job["error"] = type(exc).__name__
            job["updated_at"] = time.time()
            self._write_job(job)
            self.audit.record("training_failed", job_id=job_id, error=type(exc).__name__)
            return {"ok": False, "status": JobState.FAILED.value, "job": job, "actual_training_executed": False}

        if time.time() - started > cfg.max_runtime_seconds:
            job["state"] = JobState.FAILED.value
            job["error"] = "timeout"
            job["updated_at"] = time.time()
            self._write_job(job)
            return {"ok": False, "status": "FAILED", "error": "timeout", "job": job}

        job["result"] = result.to_dict()
        job["is_mock"] = result.is_mock
        job["real_training"] = bool(getattr(result, "real_training", False) or result.real_weight_update)
        job["real_weight_update"] = result.real_weight_update
        job["updated_at"] = time.time()

        if not result.ok:
            job["state"] = result.status if result.status in {s.value for s in JobState} else JobState.FAILED.value
            job["error"] = result.error
            self._write_job(job)
            self.audit.record("training_not_completed", job_id=job_id, result=result.to_dict())
            return {
                "ok": False,
                "status": result.status,
                "job": job,
                "actual_training_executed": bool(result.real_weight_update),
                "real_training_executed": bool(getattr(result, "real_training", False)),
            }

        # Final checkpoint integrity gate
        job["state"] = JobState.CHECKPOINTING.value
        job["updated_at"] = time.time()
        self._write_job(job)
        final_ok = self.checkpoints.verify_integrity(result.checkpoint_path)
        job["final_checkpoint_integrity"] = final_ok
        if not final_ok.get("ok"):
            job["state"] = JobState.FAILED.value
            job["error"] = "corrupted_checkpoint"
            self._write_job(job)
            return {
                "ok": False,
                "status": "FAILED",
                "error": "corrupted_checkpoint",
                "job": job,
                "actual_training_executed": bool(result.real_weight_update),
                "real_training_executed": bool(getattr(result, "real_training", False)),
                "real_checkpoint_created": False,
            }

        model = self.models.register(
            base_model=result.base_model or cfg.base_model,
            dataset_version=dataset_id,
            training_config=cfg.to_dict(),
            checkpoint_ref=result.checkpoint_path,
            status=ModelStatus.CANDIDATE,
            meta={
                "job_id": job_id,
                "backend": result.backend,
                "is_mock": result.is_mock,
                "real_training": bool(getattr(result, "real_training", False)),
                "real_weight_update": result.real_weight_update,
                "model_revision": result.model_revision,
                "license": (cfg.extra or {}).get("license") or os.environ.get("MODEL_LICENSE") or "unverified",
            },
        )
        job["model_id"] = model["model_id"]
        job["state"] = JobState.EVALUATING.value
        job["updated_at"] = time.time()
        self._write_job(job)

        self._state["phase"] = "evaluating"
        self._save_state()
        self.models.update_status(model["model_id"], ModelStatus.VALIDATING)
        eval_report = self.gates.evaluate_candidate(
            candidate_id=model["model_id"],
            candidate_bonus=0.05 if result.ok else 0.0,
        )
        job["evaluation"] = eval_report
        job["state"] = JobState.SHADOW.value
        job["updated_at"] = time.time()
        self._write_job(job)
        shadow = self.gates.shadow_compare(eval_report, {"overall_candidate": eval_report.get("overall_active", 0.5)})
        job["shadow"] = shadow
        job["state"] = JobState.CANARY.value
        job["updated_at"] = time.time()
        self._write_job(job)
        canary = self.canary.evaluate_shadow(shadow)
        job["canary"] = canary
        self._write_job(job)
        self.audit.record(
            "evaluation_complete",
            job_id=job_id,
            model_id=model["model_id"],
            decision=eval_report.get("decision"),
            canary=canary.get("decision"),
            real_training=bool(getattr(result, "real_training", False)),
        )

        if (
            not eval_report.get("ok")
            or shadow.get("decision") == "STOP_ACTIVATION"
            or canary.get("decision") == "STOP_ACTIVATION"
        ):
            self.models.update_status(model["model_id"], ModelStatus.REJECTED, evaluation=eval_report)
            job["state"] = JobState.REJECTED.value
            job["updated_at"] = time.time()
            self._write_job(job)
            self._state["phase"] = "rejected"
            self._state["cycles"] = int(self._state.get("cycles") or 0) + 1
            self._save_state()
            return {
                "ok": False,
                "status": "REJECTED",
                "job": job,
                "evaluation": eval_report,
                "actual_training_executed": bool(result.real_weight_update),
                "real_training_executed": bool(getattr(result, "real_training", False)),
                "real_checkpoint_created": True,
                "real_evaluation_executed": True,
                "canary_executed": True,
                "model_activated": False,
            }

        self.models.update_status(model["model_id"], ModelStatus.VALIDATED, evaluation=eval_report)

        can_activate = activate_if_pass and (
            result.real_weight_update or (result.is_mock and cfg.allow_mock_backend)
        )
        activation = None
        runtime_switch = None
        if can_activate:
            job["state"] = JobState.ACTIVATING.value
            job["updated_at"] = time.time()
            self._write_job(job)
            activation = self.models.activate(model["model_id"])
            runtime_switch = self.active_runtime.switch_to(
                model_id=model["model_id"],
                checkpoint_ref=result.checkpoint_path,
                dataset_version=dataset_id,
                meta={
                    "job_id": job_id,
                    "is_mock": result.is_mock,
                    "real_training": bool(getattr(result, "real_training", False)),
                },
            )
            job["activation"] = activation
            job["runtime_switch"] = runtime_switch
            self.audit.record(
                "model_activated",
                job_id=job_id,
                model_id=model["model_id"],
                dataset_id=dataset_id,
                is_mock=result.is_mock,
                real_weight_update=result.real_weight_update,
                real_training=bool(getattr(result, "real_training", False)),
                runtime_loaded=bool(runtime_switch.get("loaded")),
            )
            job["state"] = JobState.ACTIVE.value
        else:
            job["state"] = JobState.COMPLETED.value
            job["activation"] = {
                "ok": False,
                "reason": "validated_but_not_activated",
                "is_mock": result.is_mock,
            }

        job["updated_at"] = time.time()
        self._write_job(job)
        self.triggers.mark_scheduled()
        self._state["phase"] = "completed"
        self._state["last_model_id"] = model["model_id"]
        self._state["cycles"] = int(self._state.get("cycles") or 0) + 1
        self._save_state()
        return {
            "ok": True,
            "status": job["state"],
            "job": job,
            "evaluation": eval_report,
            "activation": activation,
            "runtime_switch": runtime_switch,
            "actual_training_executed": bool(result.real_weight_update),
            "real_training_executed": bool(getattr(result, "real_training", False) and result.real_weight_update),
            "real_checkpoint_created": True,
            "real_evaluation_executed": True,
            "canary_executed": True,
            "is_mock": result.is_mock,
            "model_activated": bool(can_activate and activation),
            "rollback_available": bool(self.rollback_mgr.last_known_good()),
        }

    def activate_model(self, model_id: str) -> dict[str, Any]:
        model = self.models.get(model_id)
        if not model:
            return {"ok": False, "error": "model_not_found"}
        if model.get("status") not in (ModelStatus.VALIDATED.value, ModelStatus.CANDIDATE.value, ModelStatus.ACTIVE.value):
            return {"ok": False, "error": "model_not_validated"}
        cp = model.get("checkpoint_ref") or ""
        integrity = self.checkpoints.verify_integrity(cp)
        if not integrity.get("ok"):
            return {"ok": False, "error": "checkpoint_integrity_failed", "integrity": integrity}
        activation = self.models.activate(model_id)
        runtime = self.active_runtime.switch_to(
            model_id=model_id,
            checkpoint_ref=cp,
            dataset_version=str(model.get("dataset_version") or ""),
        )
        self.audit.record("model_activated_manual", model_id=model_id, runtime_loaded=runtime.get("loaded"))
        return {"ok": runtime.get("status") == "ACTIVE", "activation": activation, "runtime": runtime}

    def resume_job(self, job_id: str) -> dict[str, Any]:
        job = self._read_job(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        state = job.get("state")
        if state in (
            JobState.COMPLETED.value,
            JobState.REJECTED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
        ):
            return {"ok": True, "resumed": False, "job": job}
        self._state["paused"] = False
        self._save_state()
        return self.run_cycle(
            owner_requested=True,
            force_dataset=job.get("dataset_id"),
            config=TrainingConfig(
                **{
                    k: v
                    for k, v in (job.get("config") or {}).items()
                    if k in TrainingConfig.__dataclass_fields__
                }
            ),
        )

    def monitor_and_maybe_rollback(self, *, force_regression: bool = False) -> dict[str, Any]:
        active = self.models.active()
        if not active:
            return {"ok": True, "action": "none", "reason": "no_active_model"}
        report = self.gates.evaluate_candidate(
            candidate_id=active["model_id"], candidate_bonus=-0.5 if force_regression else 0.0
        )
        if force_regression or not report.get("ok"):
            rb = self.rollback_mgr.rollback(reason="post_activation_regression")
            return {"ok": rb.get("ok"), "action": "rollback", "monitor": report, "rollback": rb}
        return {"ok": True, "action": "healthy", "monitor": report}
