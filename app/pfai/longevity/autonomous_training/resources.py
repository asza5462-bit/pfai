"""Resource estimation, admission, and checkpoint cleanup (never deletes LKG)."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from .runtime_detector import TrainingRuntimeDetector


class TrainingResourceManager:
    def __init__(self, detector: TrainingRuntimeDetector | None = None) -> None:
        self.detector = detector or TrainingRuntimeDetector()
        self.min_free_memory_gb = float(os.environ.get("TRAINING_MIN_FREE_MEMORY", "1"))
        self.min_free_disk_gb = float(os.environ.get("TRAINING_MIN_FREE_DISK", "1"))
        self.max_ram_gb = float(os.environ.get("TRAINING_MAX_RAM_GB", "8"))
        self.max_disk_gb = float(os.environ.get("TRAINING_MAX_DISK_GB", "20"))
        self.max_gpu_utilization = float(os.environ.get("TRAINING_MAX_GPU_UTILIZATION", "0.95"))
        self.max_runtime_seconds = int(os.environ.get("TRAINING_MAX_RUNTIME", "3600"))
        self.max_concurrent = int(
            os.environ.get("TRAINING_MAX_CONCURRENT_JOBS")
            or os.environ.get("TRAINING_MAX_RESOURCE_BUDGET")
            or "1"
        )
        self.allow_cpu_training = (os.environ.get("TRAINING_ALLOW_CPU") or "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.max_non_lkg_checkpoints = int(os.environ.get("TRAINING_MAX_NON_LKG_CHECKPOINTS", "20"))

    def estimate(self, *, dataset_rows: int, method: str = "lora") -> dict[str, Any]:
        bytes_per_example = 2048
        dataset_mb = max(1, (dataset_rows * bytes_per_example) // (1024 * 1024))
        method = (method or "lora").lower()
        mem_gb = 2.0 if method in ("lora", "qlora") else 8.0
        disk_gb = max(1.0, dataset_mb / 512.0 + (1.0 if method != "full" else 4.0))
        runtime_s = max(60, min(self.max_runtime_seconds, dataset_rows * (2 if method == "lora" else 5)))
        return {
            "dataset_rows": dataset_rows,
            "dataset_mb_est": dataset_mb,
            "expected_memory_gb": mem_gb,
            "expected_disk_gb": disk_gb,
            "expected_runtime_seconds": runtime_s,
            "method": method,
        }

    def admit(
        self,
        *,
        dataset_rows: int,
        method: str,
        running_jobs: int,
    ) -> dict[str, Any]:
        probe = self.detector.detect(probe_inference=False)
        est = self.estimate(dataset_rows=dataset_rows, method=method)
        reasons: list[str] = []
        if running_jobs >= self.max_concurrent:
            reasons.append("max_concurrent_jobs")
        if not probe.training_available:
            reasons.append("runtime_unavailable")
        if probe.ram_available_gb is not None and probe.ram_available_gb < self.min_free_memory_gb:
            reasons.append("insufficient_memory")
        if probe.ram_available_gb is not None and est["expected_memory_gb"] > self.max_ram_gb:
            reasons.append("exceeds_max_ram_budget")
        if probe.disk_free_gb is not None and probe.disk_free_gb < self.min_free_disk_gb:
            reasons.append("insufficient_disk")
        if est["expected_disk_gb"] > self.max_disk_gb:
            reasons.append("exceeds_max_disk_budget")
        method_l = (method or "lora").lower()
        if method_l == "qlora" and not (probe.cuda and probe.modules.get("bitsandbytes")):
            reasons.append("qlora_requires_cuda_and_bitsandbytes")
        if method_l == "full" and not probe.cuda:
            reasons.append("full_finetune_requires_cuda")
        if not probe.gpu_available and not self.allow_cpu_training:
            reasons.append("cpu_training_disabled")
        gpu_note = "gpu_unavailable" if not probe.gpu_available else "gpu_utilization_unmeasured"
        return {
            "ok": not reasons,
            "reasons": reasons,
            "estimate": est,
            "limits": {
                "min_free_memory_gb": self.min_free_memory_gb,
                "min_free_disk_gb": self.min_free_disk_gb,
                "max_ram_gb": self.max_ram_gb,
                "max_disk_gb": self.max_disk_gb,
                "max_runtime_seconds": self.max_runtime_seconds,
                "max_gpu_utilization": self.max_gpu_utilization,
                "max_concurrent": self.max_concurrent,
                "allow_cpu_training": self.allow_cpu_training,
                "gpu_available": bool(probe.gpu_available),
                "cuda": bool(probe.cuda),
            },
            "probe_summary": {
                "status": probe.status,
                "ram_available_gb": probe.ram_available_gb,
                "disk_free_gb": probe.disk_free_gb,
                "gpu_available": probe.gpu_available,
                "vram_gb": probe.vram_gb,
                "gpu_note": gpu_note,
            },
            "action": "reject" if reasons else "launch",
            "device": "cuda" if probe.gpu_available else "cpu",
        }

    def cleanup_old_checkpoints(
        self,
        artifacts_root: str | Path,
        *,
        protect_paths: set[str] | None = None,
    ) -> dict[str, Any]:
        """Remove oldest non-protected job artifact dirs. NEVER deletes LKG/active paths."""
        root = Path(artifacts_root)
        protect = {str(Path(p).resolve()) for p in (protect_paths or set()) if p}
        if not root.exists():
            return {"ok": True, "removed": [], "protected": list(protect), "note": "no_artifacts"}
        dirs = sorted(
            [p for p in root.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
        )
        removed: list[str] = []
        kept: list[str] = []
        # Keep newest max_non_lkg_checkpoints that are not protected; delete older non-protected
        candidates = []
        for d in dirs:
            resolved = str(d.resolve())
            if resolved in protect or any(resolved.startswith(p + os.sep) or resolved == p for p in protect):
                kept.append(resolved)
                continue
            candidates.append(d)
        # candidates sorted oldest-first; keep the newest N
        overflow = candidates[: max(0, len(candidates) - self.max_non_lkg_checkpoints)]
        for d in overflow:
            try:
                shutil.rmtree(d)
                removed.append(str(d))
            except Exception:
                continue
        return {
            "ok": True,
            "removed": removed,
            "kept_protected": kept,
            "remaining_candidates": len(candidates) - len(overflow),
            "at": time.time(),
        }
