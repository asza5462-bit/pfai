"""AutonomousTrainingOrchestrator — resumable train→eval→activate→rollback loop."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .audit import TrainingAuditLog
from .checkpoints import CheckpointStore
from .collector import ExperienceCollector, collect_from_learning_pipeline
from .dataset import DatasetBuilder, DatasetVersionRegistry
from .evaluation_gate import EvaluationGate
from .isolation import TrainingSafetyIsolation
from .model_registry import ModelRegistry
from .rollback import ModelRollbackManager
from .runtime import detect_runtime_capabilities
from .trainer import TrainingBackendRegistry
from .triggers import TrainingTriggerPolicy
from .types import JobState, ModelStatus, TrainingConfig, TrainingResult
from .validator import TrainingExampleValidator


class AutonomousTrainingOrchestrator:
    """Full continuous improvement loop with honest runtime reporting."""

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
        self.rollback_mgr = ModelRollbackManager(self.models, audit_fn=self.audit.record)
        self.isolation = TrainingSafetyIsolation()
        self.triggers = TrainingTriggerPolicy()
        self._lock = threading.RLock()
        env_mock = (os.environ.get("TRAINING_ALLOW_MOCK") or "").lower() in ("1", "true", "yes")
        self.allow_mock_backend = env_mock if allow_mock_backend is None else bool(allow_mock_backend)
        self._ensure_default_sources()
        self._state = self._load_state()

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

    def runtime_status(self) -> dict[str, Any]:
        caps = detect_runtime_capabilities()
        return {
            "training_enabled": self.triggers.enabled,
            "allow_mock_backend": self.allow_mock_backend,
            "capabilities": caps,
            "status": caps.get("status"),
            "backends": self.backends.list_backends(),
            "active_model": self.models.active(),
            "orchestrator": dict(self._state),
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

    def build_dataset_from_sources(self, *, sources: list[str] | None = None) -> dict[str, Any]:
        rows = self.collector.collect(sources=sources)
        built = self.builder.build(rows)
        if built["accepted"] < 1:
            return {"ok": False, "error": "INSUFFICIENT_DATA", "built": built}
        parent = None
        versions = self.datasets.list_versions(limit=1)
        if versions:
            parent = versions[0]["dataset_id"]
        manifest = self.datasets.create_version(
            built,
            parent_dataset=parent,
            meta={"sources": sources or list(self.collector._sources.keys())},
        )
        self.audit.record("dataset_created", dataset_id=manifest["dataset_id"], counts=manifest.get("validation_results"))
        self._state["last_dataset_id"] = manifest["dataset_id"]
        self._save_state()
        return {"ok": True, "manifest": manifest, "accepted": built["accepted"], "rejected": built["rejected"]}

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
        guard = self.isolation.guard_training_request(request)
        if not guard["ok"]:
            self.audit.record("isolation_block", violations=guard["violations"])
            return {"ok": False, "error": "AUTHORITY_ISOLATION_VIOLATION", "violations": guard["violations"]}

        cfg = config or TrainingConfig(
            max_runtime_seconds=self.triggers.max_runtime,
            allow_mock_backend=self.allow_mock_backend,
            base_model=os.environ.get("MODEL_NAME") or os.environ.get("PFAI_MODEL_NAME") or "local",
        )
        cfg.allow_mock_backend = bool(cfg.allow_mock_backend or self.allow_mock_backend)

        # Collect / reuse dataset
        if force_dataset:
            manifest = self.datasets.get(force_dataset)
            if not manifest:
                return {"ok": False, "error": "dataset_not_found"}
            dataset_id = force_dataset
            accepted = int(manifest.get("train_count") or 0) + int(manifest.get("validation_count") or 0)
        else:
            built = self.build_dataset_from_sources()
            if not built.get("ok"):
                self.audit.record("insufficient_data", detail=built)
                return {"ok": False, "status": "INSUFFICIENT_DATA", **built}
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

        # Concurrent job budget
        running = [j for j in self.list_jobs(limit=20) if j.get("state") == JobState.RUNNING.value]
        if len(running) >= self.triggers.max_resource_budget:
            job["state"] = JobState.REJECTED.value
            job["error"] = "max concurrent training jobs exceeded"
            self._write_job(job)
            return {"ok": False, "status": JobState.REJECTED.value, "job": job}

        trainer, selection = self.backends.select(cfg)
        if trainer is None:
            job["state"] = JobState.TRAINING_RUNTIME_UNAVAILABLE.value
            job["error"] = "TRAINING_RUNTIME_UNAVAILABLE"
            job["selection"] = selection
            self._write_job(job)
            self.audit.record("runtime_unavailable", job_id=job_id, selection=selection)
            self._state["phase"] = "runtime_unavailable"
            self._save_state()
            return {
                "ok": False,
                "status": "TRAINING_RUNTIME_UNAVAILABLE",
                "job": job,
                "selection": selection,
                "actual_training_executed": False,
            }

        train_rows = self.datasets.load_split(dataset_id, "train")
        if len(train_rows) > cfg.max_dataset_size:
            train_rows = train_rows[: cfg.max_dataset_size]

        job["state"] = JobState.RUNNING.value
        job["backend"] = trainer.backend_id
        job["selection"] = selection
        self._write_job(job)
        self._state["phase"] = "training"
        self._state["last_job_id"] = job_id
        self._save_state()

        out_dir = str(self.root / "artifacts" / job_id)

        def _on_cp(meta: dict[str, Any]) -> None:
            rec = self.checkpoints.record(job_id, meta)
            job["checkpoints"].append(rec)
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
            self._write_job(job)
            self.audit.record("training_failed", job_id=job_id, error=type(exc).__name__)
            return {"ok": False, "status": JobState.FAILED.value, "job": job, "actual_training_executed": False}

        if time.time() - started > cfg.max_runtime_seconds:
            job["state"] = JobState.FAILED.value
            job["error"] = "timeout"
            self._write_job(job)
            return {"ok": False, "status": "FAILED", "error": "timeout", "job": job}

        job["result"] = result.to_dict()
        job["is_mock"] = result.is_mock
        job["real_weight_update"] = result.real_weight_update

        if not result.ok:
            job["state"] = result.status
            job["error"] = result.error
            self._write_job(job)
            self.audit.record("training_not_completed", job_id=job_id, result=result.to_dict())
            return {
                "ok": False,
                "status": result.status,
                "job": job,
                "actual_training_executed": bool(result.real_weight_update),
            }

        # Register candidate model
        model = self.models.register(
            base_model=cfg.base_model,
            dataset_version=dataset_id,
            training_config=cfg.to_dict(),
            checkpoint_ref=result.checkpoint_path,
            status=ModelStatus.VALIDATING,
            meta={"job_id": job_id, "backend": result.backend, "is_mock": result.is_mock},
        )
        job["model_id"] = model["model_id"]
        self._write_job(job)

        # Evaluate
        self._state["phase"] = "evaluating"
        self._save_state()
        # Mock trainings can pass gates in tests but must be labeled; production auto-activate
        # only when real_weight_update OR explicit allow_mock_backend with owner_requested.
        eval_report = self.gates.evaluate_candidate(
            candidate_id=model["model_id"],
            candidate_bonus=0.05 if result.ok else 0.0,
        )
        job["evaluation"] = eval_report
        shadow = self.gates.shadow_compare(eval_report, {"overall_candidate": eval_report.get("overall_active", 0.5)})
        job["shadow"] = shadow
        self._write_job(job)
        self.audit.record(
            "evaluation_complete",
            job_id=job_id,
            model_id=model["model_id"],
            decision=eval_report.get("decision"),
            shadow=shadow.get("decision"),
        )

        if not eval_report.get("ok") or shadow.get("decision") == "STOP_ACTIVATION":
            self.models.update_status(model["model_id"], ModelStatus.REJECTED, evaluation=eval_report)
            job["state"] = JobState.REJECTED.value
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
            }

        self.models.update_status(model["model_id"], ModelStatus.VALIDATED, evaluation=eval_report)

        # Activation policy: real training always eligible; mock only when allow_mock_backend
        can_activate = activate_if_pass and (
            result.real_weight_update or (result.is_mock and cfg.allow_mock_backend)
        )
        activation = None
        if can_activate:
            activation = self.models.activate(model["model_id"])
            job["activation"] = activation
            self.audit.record(
                "model_activated",
                job_id=job_id,
                model_id=model["model_id"],
                dataset_id=dataset_id,
                is_mock=result.is_mock,
                real_weight_update=result.real_weight_update,
            )
            job["state"] = JobState.COMPLETED.value
        else:
            job["state"] = JobState.COMPLETED.value
            job["activation"] = {
                "ok": False,
                "reason": "validated_but_not_activated",
                "is_mock": result.is_mock,
            }

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
            "actual_training_executed": bool(result.real_weight_update),
            "is_mock": result.is_mock,
        }

    def resume_job(self, job_id: str) -> dict[str, Any]:
        job = self._read_job(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found"}
        state = job.get("state")
        if state in (JobState.COMPLETED.value, JobState.REJECTED.value, JobState.FAILED.value):
            return {"ok": True, "resumed": False, "job": job}
        # Re-queue incomplete jobs conservatively
        return self.run_cycle(
            owner_requested=True,
            force_dataset=job.get("dataset_id"),
            config=TrainingConfig(**{k: v for k, v in (job.get("config") or {}).items() if k in TrainingConfig.__dataclass_fields__}),
        )

    def monitor_and_maybe_rollback(self, *, force_regression: bool = False) -> dict[str, Any]:
        active = self.models.active()
        if not active:
            return {"ok": True, "action": "none", "reason": "no_active_model"}
        # Lightweight monitor using evaluation gate smoke
        report = self.gates.evaluate_candidate(candidate_id=active["model_id"], candidate_bonus=-0.5 if force_regression else 0.0)
        if force_regression or not report.get("ok"):
            rb = self.rollback_mgr.rollback(reason="post_activation_regression")
            return {"ok": rb.get("ok"), "action": "rollback", "monitor": report, "rollback": rb}
        return {"ok": True, "action": "healthy", "monitor": report}
