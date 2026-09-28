"""Pre-flight model/dataset/runtime compatibility checks (PHASE 7)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .runtime_detector import RuntimeAvailability, TrainingRuntimeDetector
from .types import TrainingConfig


class CompatibilityBlockReason:
    RUNTIME_UNAVAILABLE = "TRAINING_BLOCKED_RUNTIME_UNAVAILABLE"
    INSUFFICIENT_MEMORY = "TRAINING_BLOCKED_INSUFFICIENT_MEMORY"
    INSUFFICIENT_DISK = "TRAINING_BLOCKED_INSUFFICIENT_DISK"
    MODEL_INCOMPATIBLE = "TRAINING_BLOCKED_MODEL_INCOMPATIBLE"
    DATASET_INVALID = "TRAINING_BLOCKED_DATASET_INVALID"
    METHOD_UNSUPPORTED = "TRAINING_BLOCKED_METHOD_UNSUPPORTED"
    DEPENDENCY_MISSING = "TRAINING_BLOCKED_DEPENDENCY_MISSING"


class ModelCompatibilityChecker:
    def __init__(self, detector: TrainingRuntimeDetector | None = None) -> None:
        self.detector = detector or TrainingRuntimeDetector()

    def check(
        self,
        *,
        config: TrainingConfig,
        dataset_rows: list[dict[str, Any]] | None = None,
        model_path: str | None = None,
        min_free_memory_gb: float | None = None,
        min_free_disk_gb: float | None = None,
    ) -> dict[str, Any]:
        probe = self.detector.detect(probe_inference=False)
        reasons: list[str] = []
        details: dict[str, Any] = {"probe": probe.to_dict()}

        min_mem = float(
            min_free_memory_gb
            if min_free_memory_gb is not None
            else os.environ.get("TRAINING_MIN_FREE_MEMORY", "1")
        )
        min_disk = float(
            min_free_disk_gb
            if min_free_disk_gb is not None
            else os.environ.get("TRAINING_MIN_FREE_DISK", "1")
        )

        if not probe.training_available:
            reasons.append(CompatibilityBlockReason.RUNTIME_UNAVAILABLE)
            if probe.status == RuntimeAvailability.PARTIALLY_AVAILABLE.value:
                reasons.append(CompatibilityBlockReason.DEPENDENCY_MISSING)

        method = (config.method or "lora").lower()
        if probe.training_available and method not in (probe.supported_methods or ["lora", "qlora"]):
            # full only with cuda
            if method == "full" and not probe.cuda:
                reasons.append(CompatibilityBlockReason.METHOD_UNSUPPORTED)
            elif method not in ("lora", "qlora", "full"):
                reasons.append(CompatibilityBlockReason.METHOD_UNSUPPORTED)

        if probe.ram_available_gb is not None and probe.ram_available_gb < min_mem:
            reasons.append(CompatibilityBlockReason.INSUFFICIENT_MEMORY)
        if probe.disk_free_gb is not None and probe.disk_free_gb < min_disk:
            reasons.append(CompatibilityBlockReason.INSUFFICIENT_DISK)

        # Model existence / format — fall back to bundled base only for empty/placeholder
        path_env = (os.environ.get("MODEL_PATH") or "").strip()
        base = model_path or path_env or config.base_model or os.environ.get("MODEL_NAME") or ""
        if not base or base in ("local", "none", "unset"):
            for fallback in (
                path_env,
                (os.environ.get("PFAI_LOCAL_MODEL_ID") or "").strip(),
                "data/models/distilgpt2",
                "data/models/tiny-random-gpt2",
            ):
                if fallback and fallback not in ("local", "none", "unset") and Path(fallback).exists():
                    base = fallback
                    break
        details["base_model"] = base
        details["model_revision"] = os.environ.get("MODEL_REVISION") or config.extra.get("revision")
        details["model_provider"] = os.environ.get("MODEL_PROVIDER") or os.environ.get("PFAI_MODEL_PROVIDER") or "local_open_weight"
        license_meta = {
            "declared_license": (config.extra or {}).get("license") or os.environ.get("MODEL_LICENSE") or "unverified",
            "source": os.environ.get("MODEL_LICENSE_SOURCE") or "operator_declared",
            "note": "License must be verified by operator; PFAI does not claim unrestricted use.",
        }
        details["license"] = license_meta
        download_ok = (os.environ.get("MODEL_DOWNLOAD_APPROVED") or "").lower() in ("1", "true", "yes")

        if not base or base in ("local", "none", "unset"):
            reasons.append(CompatibilityBlockReason.MODEL_INCOMPATIBLE)
            details["no_compatible_model"] = True
        else:
            local = Path(base)
            if local.exists():
                # local checkpoint/dir
                has_cfg = (local / "config.json").exists() or any(local.glob("*.safetensors")) or any(
                    local.glob("pytorch_model*.bin")
                )
                if local.is_dir() and not has_cfg and not any(local.iterdir()):
                    reasons.append(CompatibilityBlockReason.MODEL_INCOMPATIBLE)
                details["model_source"] = "local_path"
                details["format_ok"] = bool(has_cfg or local.is_file())
            else:
                details["model_source"] = "id_or_remote"
                details["loaded"] = False
                if not download_ok:
                    reasons.append(CompatibilityBlockReason.MODEL_INCOMPATIBLE)
                    details["no_compatible_model"] = True
                    details["format_ok"] = False
                    details["download_blocked"] = True
                    details["note"] = "Set MODEL_DOWNLOAD_APPROVED=true or provide MODEL_PATH"
                else:
                    details["format_ok"] = True  # deferred to trainer download/load
                    details["download_approved"] = True

        rows = dataset_rows or []
        if not rows:
            reasons.append(CompatibilityBlockReason.DATASET_INVALID)
        else:
            bad = 0
            for r in rows[:50]:
                if not str(r.get("instruction") or "").strip() or not str(r.get("response") or "").strip():
                    bad += 1
            if bad:
                reasons.append(CompatibilityBlockReason.DATASET_INVALID)
            details["dataset_sample_checked"] = min(50, len(rows))
            details["dataset_size"] = len(rows)

        ok = not reasons
        return {
            "ok": ok,
            "blocked": not ok,
            "reasons": reasons,
            "primary_reason": reasons[0] if reasons else None,
            "details": details,
            "runtime_availability": probe.status,
            "training_available": probe.training_available,
        }
