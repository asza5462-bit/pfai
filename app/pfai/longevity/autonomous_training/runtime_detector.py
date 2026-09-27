"""PHASE 7/8 — honest training/inference runtime capability detection."""
from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RuntimeAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    PARTIALLY_AVAILABLE = "PARTIAL"  # alias for older callers
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    ERROR = "ERROR"


@dataclass
class RuntimeProbeResult:
    status: str
    python_ok: bool = True
    python_version: str = ""
    modules: dict[str, bool] = field(default_factory=dict)
    module_versions: dict[str, str | None] = field(default_factory=dict)
    cuda: bool = False
    cuda_version: str | None = None
    gpu_available: bool = False
    gpu_name: str | None = None
    vram_gb: float | None = None
    cpu_count: int | None = None
    ram_gb: float | None = None
    ram_available_gb: float | None = None
    disk_free_gb: float | None = None
    inference_available: bool = False
    training_available: bool = False
    supported_methods: list[str] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)
    setup_path: dict[str, Any] = field(default_factory=dict)
    endpoint: str = ""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_TRAINING_MODULES = ("torch", "transformers", "peft", "trl", "datasets", "accelerate", "safetensors")


class TrainingRuntimeDetector:
    """Probe actual imports/hardware — never trust config alone."""

    def __init__(self, *, endpoint: str | None = None) -> None:
        self.endpoint = (
            endpoint
            or os.environ.get("MODEL_ENDPOINT")
            or os.environ.get("PFAI_MODEL_ENDPOINT")
            or "http://127.0.0.1:11434/v1"
        ).rstrip("/")

    @staticmethod
    def _try_import(name: str) -> tuple[bool, str | None, str | None]:
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", None)
            return True, None, ver
        except Exception as exc:
            return False, f"{name}:{type(exc).__name__}", None

    def detect(self, *, probe_inference: bool = True) -> RuntimeProbeResult:
        errors: list[str] = []
        notes: list[str] = []
        reasons: list[str] = []
        modules: dict[str, bool] = {}
        versions: dict[str, str | None] = {}
        for name in (*CORE_TRAINING_MODULES, "bitsandbytes", "psutil"):
            ok, err, ver = self._try_import(name)
            modules[name] = ok
            versions[name] = ver
            if err and name in CORE_TRAINING_MODULES:
                errors.append(err)
                reasons.append(f"missing_module:{name}")

        cuda = False
        cuda_version = None
        gpu_name = None
        vram_gb = None
        if modules.get("torch"):
            try:
                import torch

                cuda = bool(torch.cuda.is_available())
                cuda_version = getattr(torch.version, "cuda", None)
                if cuda:
                    try:
                        gpu_name = torch.cuda.get_device_name(0)
                        vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
                    except Exception as exc:
                        errors.append(f"cuda_props:{type(exc).__name__}")
                else:
                    notes.append("torch_cpu_only")
            except Exception as excel:
                modules["torch"] = False
                errors.append(f"torch_runtime:{type(excel).__name__}")
                reasons.append("torch_runtime_error")

        cpu_count = os.cpu_count()
        ram_gb = None
        ram_available_gb = None
        try:
            import psutil

            vm = psutil.virtual_memory()
            ram_gb = round(vm.total / (1024**3), 2)
            ram_available_gb = round(vm.available / (1024**3), 2)
        except Exception:
            notes.append("psutil_unavailable")

        disk_free_gb = None
        try:
            usage = shutil.disk_usage(str(Path("data").resolve() if Path("data").exists() else Path(".")))
            disk_free_gb = round(usage.free / (1024**3), 2)
        except Exception as exc:
            errors.append(f"disk:{type(exc).__name__}")

        inference_available = False
        if probe_inference and self.endpoint:
            try:
                req = urllib.request.Request(f"{self.endpoint}/models", method="GET")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    _ = resp.read(256)
                inference_available = True
            except Exception as exc:
                notes.append(f"inference_probe:{type(exc).__name__}")

        core_ok = all(modules.get(m) for m in ("torch", "transformers", "peft", "datasets", "safetensors"))
        # trl/accelerate nice-to-have for some paths; PEFT+Trainer works without trl
        partial = modules.get("torch") and modules.get("transformers") and not core_ok
        training_available = bool(core_ok)
        if training_available and not modules.get("trl"):
            notes.append("trl_optional_peft_trainer_path_used")
        if training_available and not modules.get("accelerate"):
            notes.append("accelerate_missing_may_limit_distributed")

        methods: list[str] = []
        formats: list[str] = []
        if training_available:
            methods.append("lora")
            formats.extend(["hf_causal_lm", "safetensors", "pytorch_bin"])
            if cuda and modules.get("bitsandbytes"):
                methods.append("qlora")
                notes.append("qlora_available")
            else:
                notes.append("qlora_unavailable_needs_cuda_and_bitsandbytes")
            if cuda:
                methods.append("full")

        missing = [m for m in CORE_TRAINING_MODULES if not modules.get(m)]
        setup_path = {
            "command": f"{sys.executable} -m pfai.longevity.autonomous_training.setup_runtime",
            "requirements_file": "app/requirements-training.txt",
            "missing_modules": missing,
            "notes": [
                "Install only when enabling real LoRA training.",
                "Does not require AWS or Anthropic/OpenAI credentials.",
                "Set MODEL_NAME or MODEL_PATH and MODEL_DOWNLOAD_APPROVED=true for hub models.",
            ],
        }

        if training_available:
            status = RuntimeAvailability.AVAILABLE.value
        elif partial:
            status = RuntimeAvailability.PARTIAL.value
            reasons.append("partial_dependencies")
        elif errors and modules.get("torch") is False and any("torch_runtime" in e for e in errors):
            status = RuntimeAvailability.ERROR.value
        else:
            status = RuntimeAvailability.UNAVAILABLE.value
            if not reasons:
                reasons.append("training_dependencies_missing")

        return RuntimeProbeResult(
            status=status,
            python_ok=True,
            python_version=sys.version.split()[0],
            modules=modules,
            module_versions=versions,
            cuda=cuda,
            cuda_version=cuda_version,
            gpu_available=cuda,
            gpu_name=gpu_name,
            vram_gb=vram_gb,
            cpu_count=cpu_count,
            ram_gb=ram_gb,
            ram_available_gb=ram_available_gb,
            disk_free_gb=disk_free_gb,
            inference_available=inference_available,
            training_available=training_available,
            supported_methods=methods,
            supported_formats=formats,
            setup_path=setup_path,
            endpoint=self.endpoint,
            errors=errors,
            notes=notes,
            reasons=reasons,
        )


def detect_runtime_capabilities(
    *,
    endpoint: str | None = None,
    probe_inference: bool = True,
) -> dict[str, Any]:
    result = TrainingRuntimeDetector(endpoint=endpoint).detect(probe_inference=probe_inference)
    d = result.to_dict()
    # Preserve PHASE 6 key names while keeping honest runtime_availability
    d["status"] = (
        "READY"
        if result.status == RuntimeAvailability.AVAILABLE.value
        else (
            "TRAINING_RUNTIME_UNAVAILABLE"
            if result.status in (RuntimeAvailability.UNAVAILABLE.value, RuntimeAvailability.PARTIAL.value)
            else result.status
        )
    )
    d["runtime_availability"] = result.status
    d["supported_training_methods"] = result.supported_methods
    return d
