"""Provider-independent model trainers and backend registry."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from .runtime import detect_runtime_capabilities
from .types import TrainingConfig, TrainingResult


class ModelTrainer(ABC):
    backend_id: str = "base"
    is_mock: bool = False

    @abstractmethod
    def compatibility(self, config: TrainingConfig) -> dict[str, Any]:
        ...

    @abstractmethod
    def train(
        self,
        *,
        job_id: str,
        dataset_rows: list[dict[str, Any]],
        output_dir: str,
        config: TrainingConfig,
        on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> TrainingResult:
        ...


class MockModelTrainer(ModelTrainer):
    """CI/test-only trainer. Never reports real_weight_update=True."""

    backend_id = "mock"
    is_mock = True

    def compatibility(self, config: TrainingConfig) -> dict[str, Any]:
        return {
            "ok": bool(config.allow_mock_backend),
            "backend": self.backend_id,
            "is_mock": True,
            "methods": ["mock"],
            "note": "Mock trainer for tests only — not real training.",
        }

    def train(
        self,
        *,
        job_id: str,
        dataset_rows: list[dict[str, Any]],
        output_dir: str,
        config: TrainingConfig,
        on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> TrainingResult:
        if not config.allow_mock_backend:
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="TRAINING_RUNTIME_UNAVAILABLE",
                backend=self.backend_id,
                error="mock backend disabled outside tests",
                is_mock=True,
                real_weight_update=False,
            )
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        init_cp = root / "checkpoint-0000"
        init_cp.mkdir(exist_ok=True)
        (init_cp / "meta.json").write_text(
            json.dumps({"job_id": job_id, "kind": "initial", "mock": True}, indent=2),
            encoding="utf-8",
        )
        if on_checkpoint:
            on_checkpoint({"path": str(init_cp), "kind": "initial", "step": 0})
        mid = root / "checkpoint-intermediate"
        mid.mkdir(exist_ok=True)
        (mid / "meta.json").write_text(
            json.dumps({"job_id": job_id, "kind": "intermediate", "mock": True}, indent=2),
            encoding="utf-8",
        )
        if on_checkpoint:
            on_checkpoint({"path": str(mid), "kind": "intermediate", "step": 1})
        final = root / "checkpoint-final"
        final.mkdir(exist_ok=True)
        artifact = {
            "job_id": job_id,
            "backend": self.backend_id,
            "is_mock": True,
            "real_weight_update": False,
            "examples": len(dataset_rows),
            "config": config.to_dict(),
            "created_at": time.time(),
        }
        (final / "adapter_manifest.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        if on_checkpoint:
            on_checkpoint({"path": str(final), "kind": "final", "step": 2})
        return TrainingResult(
            ok=True,
            job_id=job_id,
            status="COMPLETED",
            backend=self.backend_id,
            checkpoint_path=str(final),
            metrics={"examples": len(dataset_rows), "mock": True},
            is_mock=True,
            real_weight_update=False,
        )


class TransformersLoRATrainer(ModelTrainer):
    """Real LoRA/QLoRA trainer when torch/transformers/peft/trl are installed."""

    backend_id = "transformers_lora"
    is_mock = False

    def compatibility(self, config: TrainingConfig) -> dict[str, Any]:
        caps = detect_runtime_capabilities(probe_inference=False)
        method = (config.method or "lora").lower()
        ok = bool(caps.get("training_available")) and method in ("lora", "qlora", "full")
        if config.require_gpu and not caps.get("gpu_available"):
            ok = False
        return {
            "ok": ok,
            "backend": self.backend_id,
            "is_mock": False,
            "methods": caps.get("supported_training_methods") or [],
            "capabilities": caps,
            "status": "READY" if ok else "TRAINING_RUNTIME_UNAVAILABLE",
        }

    def train(
        self,
        *,
        job_id: str,
        dataset_rows: list[dict[str, Any]],
        output_dir: str,
        config: TrainingConfig,
        on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> TrainingResult:
        compat = self.compatibility(config)
        if not compat.get("ok"):
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="TRAINING_RUNTIME_UNAVAILABLE",
                backend=self.backend_id,
                error="TRAINING_RUNTIME_UNAVAILABLE",
                is_mock=False,
                real_weight_update=False,
                metrics={"compatibility": compat},
            )
        # Reuse existing SFTLoRATrainer implementation for actual training.
        from pfai.sft import SFTLoRATrainer

        trainer = SFTLoRATrainer(output_root=str(Path(output_dir).parent))
        init = Path(output_dir) / "checkpoint-0000"
        init.mkdir(parents=True, exist_ok=True)
        (init / "meta.json").write_text(
            json.dumps({"job_id": job_id, "kind": "initial"}, indent=2), encoding="utf-8"
        )
        if on_checkpoint:
            on_checkpoint({"path": str(init), "kind": "initial", "step": 0})

        rows = [
            {"instruction": r.get("instruction", ""), "response": r.get("response", "")}
            for r in dataset_rows
        ]
        started = time.time()
        max_runtime = int(config.max_runtime_seconds or 3600)
        result = trainer.train(
            job_id,
            dry_run=False,
            require_gpu=bool(config.require_gpu),
            model_id=config.base_model,
            rows=rows,
            config={
                "batch_size": config.batch_size,
                "epochs": config.epochs,
                "learning_rate": config.learning_rate,
                **(config.extra or {}),
            },
        )
        elapsed = time.time() - started
        if elapsed > max_runtime:
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="FAILED",
                backend=self.backend_id,
                error="max training duration exceeded",
                metrics={"elapsed": elapsed, "raw": result},
            )
        status = str(result.get("status") or "failed")
        if status == "completed":
            final = Path(result.get("checkpoint") or (Path(output_dir) / "final"))
            if on_checkpoint:
                on_checkpoint({"path": str(final), "kind": "final", "step": 1})
            return TrainingResult(
                ok=True,
                job_id=job_id,
                status="COMPLETED",
                backend=self.backend_id,
                checkpoint_path=str(final),
                metrics={"train_loss": result.get("train_loss"), "elapsed": elapsed},
                is_mock=False,
                real_weight_update=True,
            )
        if status == "blocked":
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="TRAINING_RUNTIME_UNAVAILABLE",
                backend=self.backend_id,
                error=str(result.get("reason") or "blocked"),
                metrics={"raw": result},
                real_weight_update=False,
            )
        return TrainingResult(
            ok=False,
            job_id=job_id,
            status="FAILED",
            backend=self.backend_id,
            error=str(result.get("reason") or status),
            metrics={"raw": result},
            real_weight_update=False,
        )


class TrainingBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, ModelTrainer] = {}

    def register(self, trainer: ModelTrainer) -> None:
        self._backends[trainer.backend_id] = trainer

    def get(self, backend_id: str) -> ModelTrainer | None:
        return self._backends.get(backend_id)

    def list_backends(self) -> list[str]:
        return sorted(self._backends.keys())

    def select(self, config: TrainingConfig) -> tuple[ModelTrainer | None, dict[str, Any]]:
        """Pick a compatible non-mock backend first; mock only if explicitly allowed."""
        caps = detect_runtime_capabilities(probe_inference=False)
        # Prefer real trainers
        for backend_id in ("transformers_lora",):
            trainer = self._backends.get(backend_id)
            if not trainer:
                continue
            compat = trainer.compatibility(config)
            if compat.get("ok"):
                return trainer, {"selected": backend_id, "compatibility": compat, "runtime": caps}
        if config.allow_mock_backend and "mock" in self._backends:
            trainer = self._backends["mock"]
            return trainer, {
                "selected": "mock",
                "compatibility": trainer.compatibility(config),
                "runtime": caps,
                "note": "Mock trainer selected for tests only",
            }
        return None, {
            "selected": None,
            "status": "TRAINING_RUNTIME_UNAVAILABLE",
            "runtime": caps,
        }

    def bootstrap_defaults(self) -> None:
        if "transformers_lora" not in self._backends:
            self.register(TransformersLoRATrainer())
        if "mock" not in self._backends:
            self.register(MockModelTrainer())
