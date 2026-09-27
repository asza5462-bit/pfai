"""Resource estimation and admission control for training jobs."""
from __future__ import annotations

import os
from typing import Any

from .runtime_detector import TrainingRuntimeDetector


class TrainingResourceManager:
    def __init__(self, detector: TrainingRuntimeDetector | None = None) -> None:
        self.detector = detector or TrainingRuntimeDetector()
        self.min_free_memory_gb = float(os.environ.get("TRAINING_MIN_FREE_MEMORY", "1"))
        self.min_free_disk_gb = float(os.environ.get("TRAINING_MIN_FREE_DISK", "1"))
        self.max_gpu_utilization = float(os.environ.get("TRAINING_MAX_GPU_UTILIZATION", "0.95"))
        self.max_concurrent = int(
            os.environ.get("TRAINING_MAX_CONCURRENT_JOBS")
            or os.environ.get("TRAINING_MAX_RESOURCE_BUDGET")
            or "1"
        )

    def estimate(self, *, dataset_rows: int, method: str = "lora") -> dict[str, Any]:
        # Conservative heuristic estimates (not guarantees).
        bytes_per_example = 2048
        dataset_mb = max(1, (dataset_rows * bytes_per_example) // (1024 * 1024))
        method = (method or "lora").lower()
        mem_gb = 2.0 if method in ("lora", "qlora") else 8.0
        disk_gb = max(1.0, dataset_mb / 512.0 + (1.0 if method != "full" else 4.0))
        runtime_s = max(60, min(3600, dataset_rows * (2 if method == "lora" else 5)))
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
        if probe.disk_free_gb is not None and probe.disk_free_gb < self.min_free_disk_gb:
            reasons.append("insufficient_disk")
        # GPU util: only reject if explicitly over configured threshold when CUDA present
        # (without nvidia-smi we cannot measure util — note honesty).
        gpu_note = "gpu_utilization_unmeasured"
        return {
            "ok": not reasons,
            "reasons": reasons,
            "estimate": est,
            "limits": {
                "min_free_memory_gb": self.min_free_memory_gb,
                "min_free_disk_gb": self.min_free_disk_gb,
                "max_gpu_utilization": self.max_gpu_utilization,
                "max_concurrent": self.max_concurrent,
            },
            "probe_summary": {
                "status": probe.status,
                "ram_available_gb": probe.ram_available_gb,
                "disk_free_gb": probe.disk_free_gb,
                "gpu_available": probe.gpu_available,
                "gpu_note": gpu_note,
            },
            "action": "reject" if reasons else "launch",
        }
