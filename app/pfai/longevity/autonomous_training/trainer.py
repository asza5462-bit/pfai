"""Real LoRA / QLoRA training backends — PHASE 8.

Executes an actual forward/backward/optimizer loop when dependencies and a
compatible model are available. Never marks mock results as real.
"""
from __future__ import annotations

import json
import os
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
                real_training=False,
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
            "real_training": False,
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
            real_training=False,
            real_weight_update=False,
            training_config=config.to_dict(),
        )


def _default_local_base_model() -> str:
    """Bundled open-weight base used when MODEL_PATH/NAME are unset or 'local'."""
    for candidate in (
        (os.environ.get("MODEL_PATH") or "").strip(),
        (os.environ.get("PFAI_LOCAL_MODEL_ID") or "").strip(),
        "data/models/distilgpt2",
        "data/models/tiny-random-gpt2",
    ):
        if candidate and candidate not in ("local", "none", "unset") and Path(candidate).exists():
            return candidate
    return "data/models/distilgpt2"


def _resolve_model_source(config: TrainingConfig) -> dict[str, Any]:
    """Resolve local path or hub id; never download without explicit approval."""
    path_env = (os.environ.get("MODEL_PATH") or "").strip()
    name = (config.base_model or os.environ.get("MODEL_NAME") or os.environ.get("PFAI_MODEL_NAME") or "").strip()
    revision = (
        (config.extra or {}).get("revision")
        or os.environ.get("MODEL_REVISION")
        or None
    )
    license_meta = (
        (config.extra or {}).get("license")
        or os.environ.get("MODEL_LICENSE")
        or "unverified"
    )
    provider = (
        os.environ.get("MODEL_PROVIDER")
        or os.environ.get("PFAI_MODEL_PROVIDER")
        or "local_open_weight"
    )
    download_ok = (os.environ.get("MODEL_DOWNLOAD_APPROVED") or "").lower() in ("1", "true", "yes")
    # Treat placeholder 'local' as "use bundled open-weight base"
    if not name or name in ("local", "none", "unset"):
        name = _default_local_base_model()
    local_candidate = path_env or (name if name and Path(name).exists() else "")
    if not local_candidate:
        fallback = _default_local_base_model()
        if Path(fallback).exists():
            local_candidate = fallback
    if local_candidate and Path(local_candidate).exists():
        return {
            "ok": True,
            "source": "local_path",
            "model_id": local_candidate,
            "revision": revision,
            "license": license_meta,
            "provider": provider,
            "download": False,
        }
    if not name or name in ("local", "none", "unset"):
        return {
            "ok": False,
            "reason": "NO_COMPATIBLE_MODEL",
            "detail": "MODEL_NAME/MODEL_PATH unset and bundled base missing",
            "license": license_meta,
            "provider": provider,
        }
    # Hub id — only if explicitly approved for this environment
    if not download_ok and not Path(name).exists():
        return {
            "ok": False,
            "reason": "NO_COMPATIBLE_MODEL",
            "detail": "remote model requires MODEL_DOWNLOAD_APPROVED=true or a local MODEL_PATH",
            "model_id": name,
            "license": license_meta,
            "provider": provider,
        }
    return {
        "ok": True,
        "source": "hub_id",
        "model_id": name,
        "revision": revision,
        "license": license_meta,
        "provider": provider,
        "download": True,
    }


def _infer_target_modules(model) -> list[str]:
    names = {n.split(".")[-1] for n, _ in model.named_modules()}
    if "c_attn" in names:
        return ["c_attn"]
    preferred = [m for m in ("q_proj", "v_proj", "k_proj", "o_proj") if m in names]
    if preferred:
        return preferred
    # last resort: linear layers commonly wrapped
    for candidate in ("query", "value", "c_proj"):
        if candidate in names:
            return [candidate]
    raise RuntimeError("NO_COMPATIBLE_LORA_TARGET_MODULES")


def _hardware_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {"device": "cpu", "cuda": False}
    try:
        import torch

        snap["cuda"] = bool(torch.cuda.is_available())
        snap["device"] = "cuda" if snap["cuda"] else "cpu"
        snap["torch"] = torch.__version__
        if snap["cuda"]:
            snap["gpu_name"] = torch.cuda.get_device_name(0)
            snap["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
    except Exception as exc:
        snap["error"] = type(exc).__name__
    try:
        import psutil

        vm = psutil.virtual_memory()
        snap["ram_gb"] = round(vm.total / (1024**3), 2)
        snap["ram_available_gb"] = round(vm.available / (1024**3), 2)
    except Exception:
        pass
    snap["cpu_count"] = os.cpu_count()
    return snap


class TransformersLoRATrainer(ModelTrainer):
    """Real LoRA/QLoRA trainer when torch/transformers/peft/datasets are installed."""

    backend_id = "transformers_lora"
    is_mock = False

    def compatibility(self, config: TrainingConfig) -> dict[str, Any]:
        caps = detect_runtime_capabilities(probe_inference=False)
        method = (config.method or "lora").lower()
        ok = bool(caps.get("training_available")) and method in ("lora", "qlora", "full")
        if config.require_gpu and not caps.get("gpu_available"):
            ok = False
        model = _resolve_model_source(config)
        if not model.get("ok"):
            ok = False
        return {
            "ok": ok,
            "backend": self.backend_id,
            "is_mock": False,
            "methods": caps.get("supported_training_methods") or caps.get("supported_methods") or [],
            "capabilities": caps,
            "model": model,
            "status": "READY" if ok else (
                model.get("reason") if not model.get("ok") else "TRAINING_RUNTIME_UNAVAILABLE"
            ),
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
        started = time.time()
        hardware = _hardware_snapshot()
        runtime_caps = detect_runtime_capabilities(probe_inference=False)
        compat = self.compatibility(config)
        model_src = compat.get("model") or _resolve_model_source(config)

        base_fields = dict(
            job_id=job_id,
            backend=self.backend_id,
            is_mock=False,
            real_training=False,
            real_weight_update=False,
            runtime_status=runtime_caps.get("runtime_availability") or runtime_caps.get("status"),
            base_model=str(model_src.get("model_id") or config.base_model),
            model_revision=str(model_src.get("revision") or "") or None,
            training_config=config.to_dict(),
            hardware=hardware,
            start_time=started,
        )

        if not compat.get("ok"):
            reason = model_src.get("reason") if not model_src.get("ok") else "TRAINING_RUNTIME_UNAVAILABLE"
            return TrainingResult(
                ok=False,
                status=str(reason),
                error=str(model_src.get("detail") or reason),
                end_time=time.time(),
                metrics={"compatibility": compat},
                **base_fields,
            )

        if not dataset_rows:
            return TrainingResult(
                ok=False,
                status="FAILED",
                error="empty_dataset",
                end_time=time.time(),
                **base_fields,
            )

        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        init = root / "checkpoint-0000"
        init.mkdir(parents=True, exist_ok=True)
        (init / "meta.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "kind": "initial",
                    "base_model": model_src.get("model_id"),
                    "revision": model_src.get("revision"),
                    "license": model_src.get("license"),
                    "provider": model_src.get("provider"),
                    "real_training": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if on_checkpoint:
            on_checkpoint({"path": str(init), "kind": "initial", "step": 0})

        try:
            result = self._run_lora_loop(
                job_id=job_id,
                dataset_rows=dataset_rows,
                output_dir=root,
                config=config,
                model_src=model_src,
                on_checkpoint=on_checkpoint,
                started=started,
                hardware=hardware,
                runtime_status=base_fields["runtime_status"],
            )
            return result
        except Exception as exc:
            return TrainingResult(
                ok=False,
                status="FAILED",
                error=f"{type(exc).__name__}:{exc}",
                end_time=time.time(),
                metrics={"exception": type(exc).__name__},
                **base_fields,
            )

    def _run_lora_loop(
        self,
        *,
        job_id: str,
        dataset_rows: list[dict[str, Any]],
        output_dir: Path,
        config: TrainingConfig,
        model_src: dict[str, Any],
        on_checkpoint: Callable[[dict[str, Any]], None] | None,
        started: float,
        hardware: dict[str, Any],
        runtime_status: str | None,
    ) -> TrainingResult:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
            set_seed,
        )

        extra = dict(config.extra or {})
        max_steps = int(extra.get("max_steps") or os.environ.get("TRAINING_MAX_STEPS") or 5)
        max_seq = int(extra.get("max_seq_length") or os.environ.get("MODEL_CONTEXT_LENGTH") or 64)
        seed = int(extra.get("seed") or os.environ.get("TRAINING_SEED") or 42)
        set_seed(seed)

        model_id = str(model_src["model_id"])
        revision = model_src.get("revision") or None
        load_kw: dict[str, Any] = {}
        if revision:
            load_kw["revision"] = revision

        method = (config.method or "lora").lower()
        use_qlora = method == "qlora"
        if use_qlora:
            # QLoRA needs bitsandbytes + CUDA in typical setups; refuse honestly on CPU.
            try:
                import bitsandbytes  # noqa: F401
            except Exception:
                return TrainingResult(
                    ok=False,
                    job_id=job_id,
                    status="FAILED",
                    backend=self.backend_id,
                    error="qlora_requires_bitsandbytes",
                    is_mock=False,
                    real_training=False,
                    real_weight_update=False,
                    runtime_status=runtime_status,
                    base_model=model_id,
                    model_revision=revision,
                    training_config=config.to_dict(),
                    hardware=hardware,
                    start_time=started,
                    end_time=time.time(),
                )
            if not torch.cuda.is_available():
                return TrainingResult(
                    ok=False,
                    job_id=job_id,
                    status="FAILED",
                    backend=self.backend_id,
                    error="qlora_requires_cuda",
                    is_mock=False,
                    real_training=False,
                    real_weight_update=False,
                    runtime_status=runtime_status,
                    base_model=model_id,
                    model_revision=revision,
                    training_config=config.to_dict(),
                    hardware=hardware,
                    start_time=started,
                    end_time=time.time(),
                )

        tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True, **load_kw)
        model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = tokenizer.pad_token_id

        target_modules = extra.get("target_modules") or _infer_target_modules(model)
        lora = LoraConfig(
            r=int(extra.get("lora_r") or 4),
            lora_alpha=int(extra.get("lora_alpha") or 8),
            lora_dropout=float(extra.get("lora_dropout") or 0.05),
            target_modules=list(target_modules),
            bias="none",
            task_type=TaskType.CAUSAL_LM,
            fan_in_fan_out=("c_attn" in target_modules),
        )
        model = get_peft_model(model, lora)
        model.train()

        texts = [
            f"### Instruction:\n{str(r.get('instruction') or '').strip()}\n### Response:\n{str(r.get('response') or '').strip()}"
            for r in dataset_rows
            if str(r.get("instruction") or "").strip() and str(r.get("response") or "").strip()
        ]
        if not texts:
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="FAILED",
                backend=self.backend_id,
                error="no_valid_instruction_response_rows",
                is_mock=False,
                real_training=False,
                real_weight_update=False,
                runtime_status=runtime_status,
                base_model=model_id,
                model_revision=revision,
                training_config=config.to_dict(),
                hardware=hardware,
                start_time=started,
                end_time=time.time(),
            )

        def _tokenize(batch):
            return tokenizer(
                batch["text"],
                truncation=True,
                padding="max_length",
                max_length=max_seq,
            )

        ds = Dataset.from_dict({"text": texts}).map(_tokenize, batched=True, remove_columns=["text"])
        ds = ds.map(lambda x: {"labels": x["input_ids"]})
        ds.set_format(type="torch", columns=["input_ids", "attention_mask", "labels"])

        work = output_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        epochs = float(config.epochs or 1.0)
        # Bound epochs via max_steps — first verified run stays intentionally small.
        train_args = TrainingArguments(
            output_dir=str(work),
            per_device_train_batch_size=max(1, int(config.batch_size or 1)),
            num_train_epochs=epochs,
            max_steps=max_steps,
            learning_rate=float(config.learning_rate or 5e-4),
            logging_steps=1,
            save_strategy="steps",
            save_steps=max(1, int(config.checkpoint_every_steps or max_steps)),
            save_total_limit=int(extra.get("max_checkpoint_count") or os.environ.get("TRAINING_MAX_CHECKPOINTS") or 3),
            report_to=[],
            seed=seed,
            fp16=False,
            bf16=False,
            dataloader_pin_memory=False,
            remove_unused_columns=False,
            disable_tqdm=True,
        )
        collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
        trainer = Trainer(
            model=model,
            args=train_args,
            train_dataset=ds,
            data_collator=collator,
            tokenizer=tokenizer,
        )

        max_runtime = int(config.max_runtime_seconds or 600)
        train_out = trainer.train()
        elapsed = time.time() - started
        if elapsed > max_runtime:
            return TrainingResult(
                ok=False,
                job_id=job_id,
                status="FAILED",
                backend=self.backend_id,
                error="max training duration exceeded",
                metrics={"elapsed": elapsed, "train_loss": getattr(train_out, "training_loss", None)},
                is_mock=False,
                real_training=True,
                real_weight_update=False,
                runtime_status=runtime_status,
                base_model=model_id,
                model_revision=revision,
                training_config=config.to_dict(),
                hardware=hardware,
                start_time=started,
                end_time=time.time(),
            )

        final = output_dir / "checkpoint-final"
        final.mkdir(parents=True, exist_ok=True)
        trainer.save_model(str(final))
        tokenizer.save_pretrained(str(final))

        # Prefer safetensors adapter files when PEFT wrote them.
        adapter_files = list(final.glob("*.safetensors")) + list(final.glob("adapter_model.bin"))
        manifest = {
            "job_id": job_id,
            "backend": self.backend_id,
            "real_training": True,
            "real_weight_update": True,
            "is_mock": False,
            "base_model": model_id,
            "model_revision": revision,
            "license": model_src.get("license"),
            "provider": model_src.get("provider"),
            "model_source": model_src.get("source"),
            "method": method,
            "target_modules": list(target_modules),
            "max_steps": max_steps,
            "max_seq_length": max_seq,
            "seed": seed,
            "examples": len(texts),
            "train_loss": getattr(train_out, "training_loss", None),
            "global_step": getattr(train_out, "global_step", None),
            "adapter_files": [p.name for p in adapter_files],
            "hardware": hardware,
            "created_at": time.time(),
            "training_config": config.to_dict(),
        }
        (final / "adapter_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (final / "training_metrics.json").write_text(
            json.dumps(
                {
                    "train_loss": getattr(train_out, "training_loss", None),
                    "global_step": getattr(train_out, "global_step", None),
                    "metrics": getattr(train_out, "metrics", None),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        # Validate adapters reload
        reload_ok = False
        reload_error = None
        try:
            from peft import PeftModel

            base = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
            _ = PeftModel.from_pretrained(base, str(final))
            reload_ok = True
        except Exception as exc:
            reload_error = f"{type(exc).__name__}:{exc}"

        if on_checkpoint:
            on_checkpoint(
                {
                    "path": str(final),
                    "kind": "final",
                    "step": int(getattr(train_out, "global_step", max_steps) or max_steps),
                    "train_loss": getattr(train_out, "training_loss", None),
                    "reload_ok": reload_ok,
                }
            )

        end = time.time()
        ok = bool(adapter_files) and reload_ok
        return TrainingResult(
            ok=ok,
            job_id=job_id,
            status="COMPLETED" if ok else "FAILED",
            backend=self.backend_id,
            checkpoint_path=str(final),
            metrics={
                "train_loss": getattr(train_out, "training_loss", None),
                "global_step": getattr(train_out, "global_step", None),
                "examples": len(texts),
                "elapsed": end - started,
                "adapter_files": [p.name for p in adapter_files],
                "reload_ok": reload_ok,
                "reload_error": reload_error,
                "license": model_src.get("license"),
                "model_source": model_src.get("source"),
            },
            error=None if ok else (reload_error or "checkpoint_incomplete"),
            is_mock=False,
            real_training=True,
            real_weight_update=bool(ok),
            runtime_status=runtime_status,
            base_model=model_id,
            model_revision=revision,
            training_config=config.to_dict(),
            hardware=hardware,
            start_time=started,
            end_time=end,
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
        preferred = (os.environ.get("TRAINING_BACKEND") or "transformers_lora").strip()
        order = [preferred, "transformers_lora"]
        seen: set[str] = set()
        for backend_id in order:
            if backend_id in seen or backend_id == "mock":
                continue
            seen.add(backend_id)
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
        # Surface model vs runtime reason
        real = self._backends.get("transformers_lora")
        compat = real.compatibility(config) if real else {}
        status = "TRAINING_RUNTIME_UNAVAILABLE"
        if compat.get("model") and not compat["model"].get("ok"):
            status = "NO_COMPATIBLE_MODEL"
        elif not caps.get("training_available"):
            status = "TRAINING_RUNTIME_UNAVAILABLE"
        return None, {
            "selected": None,
            "status": status,
            "compatibility": compat,
            "runtime": caps,
        }

    def bootstrap_defaults(self) -> None:
        if "transformers_lora" not in self._backends:
            self.register(TransformersLoRATrainer())
        if "mock" not in self._backends:
            self.register(MockModelTrainer())


# Explicit production aliases
RealLoRATrainingBackend = TransformersLoRATrainer
RealQLoRATrainingBackend = TransformersLoRATrainer  # method selected via TrainingConfig.method
