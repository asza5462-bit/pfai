"""PHASE 7 — honest training/inference runtime capability detection."""
from __future__ import annotations

import os
import shutil
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RuntimeAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    ERROR = "ERROR"


@dataclass
class RuntimeProbeResult:
    status: str
    python_ok: bool = True
    modules: dict[str, bool] = field(default_factory=dict)
    cuda: bool = False
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
    endpoint: str = ""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    def _try_import(name: str) -> tuple[bool, str | None]:
        try:
            __import__(name)
            return True, None
        except Exception as exc:
            return False, f"{name}:{type(exc).__name__}"

    def detect(self, *, probe_inference: bool = True) -> RuntimeProbeResult:
        errors: list[str] = []
        notes: list[str] = []
        modules: dict[str, bool] = {}
        for name in ("torch", "transformers", "peft", "trl", "datasets", "accelerate", "bitsandbytes"):
            ok, err = self._try_import(name)
            modules[name] = ok
            if err and name in ("torch", "transformers", "peft", "trl", "datasets"):
                errors.append(err)

        cuda = False
        gpu_name = None
        vram_gb = None
        if modules.get("torch"):
            try:
                import torch

                cuda = bool(torch.cuda.is_available())
                if cuda:
                    try:
                        gpu_name = torch.cuda.get_device_name(0)
                        vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
                    except Exception as exc:
                        errors.append(f"cuda_props:{type(exc).__name__}")
            except Exception as exc:
                modules["torch"] = False
                errors.append(f"torch_runtime:{type(exc).__name__}")

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

        core = all(modules.get(m) for m in ("torch", "transformers", "peft", "trl", "datasets"))
        partial = modules.get("torch") and modules.get("transformers") and not core
        training_available = bool(core)
        methods: list[str] = []
        formats: list[str] = []
        if training_available:
            methods.extend(["lora", "qlora"])
            formats.extend(["hf_causal_lm", "safetensors", "pytorch_bin"])
            if cuda:
                methods.append("full")
            if modules.get("bitsandbytes"):
                notes.append("bitsandbytes_present_for_qlora")
            else:
                notes.append("qlora_may_require_bitsandbytes")

        if training_available:
            status = RuntimeAvailability.AVAILABLE.value
        elif partial:
            status = RuntimeAvailability.PARTIALLY_AVAILABLE.value
        elif errors and modules.get("torch") is False and any("torch_runtime" in e for e in errors):
            status = RuntimeAvailability.ERROR.value
        else:
            status = RuntimeAvailability.UNAVAILABLE.value

        return RuntimeProbeResult(
            status=status,
            python_ok=True,
            modules=modules,
            cuda=cuda,
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
            endpoint=self.endpoint,
            errors=errors,
            notes=notes,
        )


# Back-compat wrapper used by PHASE 6 callers
def detect_runtime_capabilities(
    *,
    endpoint: str | None = None,
    probe_inference: bool = True,
) -> dict[str, Any]:
    result = TrainingRuntimeDetector(endpoint=endpoint).detect(probe_inference=probe_inference)
    d = result.to_dict()
    # Preserve PHASE 6 key names
    d["status"] = (
        "READY"
        if result.status == RuntimeAvailability.AVAILABLE.value
        else (
            "TRAINING_RUNTIME_UNAVAILABLE"
            if result.status in (RuntimeAvailability.UNAVAILABLE.value, RuntimeAvailability.PARTIALLY_AVAILABLE.value)
            else result.status
        )
    )
    d["runtime_availability"] = result.status
    return d
