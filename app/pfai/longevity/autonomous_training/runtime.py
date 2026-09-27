"""Runtime capability detection for inference and training backends."""
from __future__ import annotations

import os
import shutil
import urllib.request
from typing import Any


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def detect_runtime_capabilities(
    *,
    endpoint: str | None = None,
    probe_inference: bool = True,
) -> dict[str, Any]:
    """Honest capability report — never claims connected without verification."""
    endpoint = (
        endpoint
        or os.environ.get("MODEL_ENDPOINT")
        or os.environ.get("PFAI_MODEL_ENDPOINT")
        or "http://127.0.0.1:11434/v1"
    ).rstrip("/")

    torch_ok = _has_module("torch")
    transformers_ok = _has_module("transformers")
    peft_ok = _has_module("peft")
    trl_ok = _has_module("trl")
    datasets_ok = _has_module("datasets")
    cuda = False
    vram_gb = None
    ram_gb = None
    if torch_ok:
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
            if cuda:
                try:
                    vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
                except Exception:
                    vram_gb = None
        except Exception:
            cuda = False
    try:
        import psutil  # optional

        ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
    except Exception:
        ram_gb = None

    inference_connected = False
    inference_error = None
    if probe_inference and endpoint:
        try:
            req = urllib.request.Request(f"{endpoint}/models", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                _ = resp.read(256)
            inference_connected = True
        except Exception as exc:
            inference_error = type(exc).__name__

    training_stack_ready = all([torch_ok, transformers_ok, peft_ok, trl_ok, datasets_ok])
    training_available = training_stack_ready  # GPU optional unless require_gpu

    methods = []
    if training_stack_ready:
        methods.extend(["lora", "qlora"])
        if cuda:
            methods.append("full")
    # Mock is never listed as a production-capable method.

    status = "READY" if training_available else "TRAINING_RUNTIME_UNAVAILABLE"
    if training_available and not inference_connected:
        note = "Training stack importable; inference endpoint not connected."
    elif not training_available:
        note = "Adapter implemented, training runtime not connected."
    else:
        note = "Training and inference runtimes available."

    return {
        "status": status,
        "inference_available": inference_connected,
        "training_available": training_available,
        "gpu_available": cuda,
        "cpu_available": True,
        "vram_gb": vram_gb,
        "ram_gb": ram_gb,
        "modules": {
            "torch": torch_ok,
            "transformers": transformers_ok,
            "peft": peft_ok,
            "trl": trl_ok,
            "datasets": datasets_ok,
        },
        "supported_training_methods": methods,
        "endpoint": endpoint,
        "quantization_support": peft_ok,
        "ollama_cli": bool(shutil.which("ollama")),
        "inference_error": inference_error,
        "note": note,
    }
