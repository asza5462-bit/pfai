"""PHASE 21 Resource Governor — prevent runaway execution; training yields to interactive."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from pfai.elite.priority_classes import PriorityClass


@dataclass
class ResourceLimits:
    max_workers: int = 8
    max_concurrent_tools: int = 8
    max_concurrent_models: int = 4
    max_sandbox: int = 4
    max_training_jobs: int = 1
    max_queue_size: int = 256
    max_execution_time_seconds: float = 300.0
    # Soft CPU/memory trackers (process-local counters — not OS cgroup claims)
    max_active_tasks: int = 32

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceGovernor:
    VERSION = "21.0.0"

    def __init__(self, limits: ResourceLimits | None = None) -> None:
        self.limits = limits or ResourceLimits()
        self._lock = threading.RLock()
        self.active_tasks = 0
        self.concurrent_tools = 0
        self.concurrent_models = 0
        self.sandbox_usage = 0
        self.training_jobs = 0
        self.queue_size = 0
        self.worker_count = 0
        self._leases: dict[str, dict[str, Any]] = {}
        self.rejected = 0
        self.yielded_training = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "limits": self.limits.to_dict(),
                "active_tasks": self.active_tasks,
                "concurrent_tools": self.concurrent_tools,
                "concurrent_models": self.concurrent_models,
                "sandbox_usage": self.sandbox_usage,
                "training_jobs": self.training_jobs,
                "queue_size": self.queue_size,
                "worker_count": self.worker_count,
                "open_leases": len(self._leases),
                "rejected": self.rejected,
                "yielded_training": self.yielded_training,
                "note": "CPU/memory are lease counters, not fabricated OS telemetry",
            }

    def can_admit(self, *, priority: PriorityClass, kind: str = "task") -> dict[str, Any]:
        with self._lock:
            if self.queue_size >= self.limits.max_queue_size and kind == "enqueue":
                self.rejected += 1
                return {"ok": False, "error": "queue_full"}
            if self.active_tasks >= self.limits.max_active_tasks:
                # Training yields to interactive
                if priority.value <= PriorityClass.USER_COMPLEX.value and self.training_jobs > 0:
                    self.yielded_training += 1
                    return {"ok": True, "yield_training": True}
                self.rejected += 1
                return {"ok": False, "error": "active_tasks_exhausted"}
            if kind == "training" and self.training_jobs >= self.limits.max_training_jobs:
                self.rejected += 1
                return {"ok": False, "error": "training_slots_exhausted"}
            if kind == "tool" and self.concurrent_tools >= self.limits.max_concurrent_tools:
                self.rejected += 1
                return {"ok": False, "error": "tool_concurrency_exhausted"}
            if kind == "model" and self.concurrent_models >= self.limits.max_concurrent_models:
                self.rejected += 1
                return {"ok": False, "error": "model_concurrency_exhausted"}
            if kind == "sandbox" and self.sandbox_usage >= self.limits.max_sandbox:
                self.rejected += 1
                return {"ok": False, "error": "sandbox_exhausted"}
            return {"ok": True}

    def acquire(self, lease_id: str, *, kind: str = "task", priority: PriorityClass = PriorityClass.USER_INTERACTIVE) -> dict[str, Any]:
        admit = self.can_admit(priority=priority, kind=kind)
        if not admit.get("ok"):
            return admit
        with self._lock:
            if kind == "task":
                self.active_tasks += 1
            elif kind == "tool":
                self.concurrent_tools += 1
            elif kind == "model":
                self.concurrent_models += 1
            elif kind == "sandbox":
                self.sandbox_usage += 1
            elif kind == "training":
                self.training_jobs += 1
            self._leases[lease_id] = {"kind": kind, "priority": priority.name, "acquired_at": time.time()}
            return {"ok": True, "lease_id": lease_id, **admit}

    def release(self, lease_id: str) -> dict[str, Any]:
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            if not lease:
                return {"ok": False, "error": "unknown_lease"}
            kind = lease["kind"]
            if kind == "task":
                self.active_tasks = max(0, self.active_tasks - 1)
            elif kind == "tool":
                self.concurrent_tools = max(0, self.concurrent_tools - 1)
            elif kind == "model":
                self.concurrent_models = max(0, self.concurrent_models - 1)
            elif kind == "sandbox":
                self.sandbox_usage = max(0, self.sandbox_usage - 1)
            elif kind == "training":
                self.training_jobs = max(0, self.training_jobs - 1)
            return {"ok": True, "released": kind}

    def set_queue_size(self, n: int) -> None:
        with self._lock:
            self.queue_size = max(0, int(n))

    def set_worker_count(self, n: int) -> None:
        with self._lock:
            self.worker_count = max(0, int(n))
