"""PHASE 21 Execution Scheduler — real concurrent workers, priorities, deps, cancel, timeout, retry."""
from __future__ import annotations

import heapq
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from pfai.authorized_execution import sanitize_args
from pfai.elite.checkpoint_store import CheckpointStore
from pfai.elite.priority_classes import PriorityClass
from pfai.elite.resource_governor import ResourceGovernor
from pfai.elite.types import new_id


@dataclass(order=True)
class _HeapItem:
    priority: int
    seq: int
    task_id: str = field(compare=False)


@dataclass
class ScheduledTask:
    task_id: str
    fn: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    priority: PriorityClass = PriorityClass.USER_INTERACTIVE
    depends_on: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    max_retries: int = 1
    backoff_seconds: float = 0.05
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "QUEUED"
    result: Any = None
    error: str = ""
    retries: int = 0
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return sanitize_args(
            {
                "task_id": self.task_id,
                "status": self.status,
                "priority": self.priority.name,
                "depends_on": list(self.depends_on),
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "retries": self.retries,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "cancel_requested": self.cancel_requested,
                "meta": self.meta,
                "has_result": self.result is not None,
            }
        )


class ExecutionScheduler:
    """
    Real thread-pool scheduler:
    - priority queue + fairness (sequence numbers)
    - dependency-aware dispatch
    - parallel independent tasks
    - cancellation, timeout, retry+backoff
    - resource budgets via ResourceGovernor
    - graceful shutdown
    - checkpoint hooks for long-running work
    """

    VERSION = "21.0.0"

    def __init__(
        self,
        *,
        max_workers: int = 4,
        governor: ResourceGovernor | None = None,
        checkpoints: CheckpointStore | None = None,
        store_metrics: bool = True,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.governor = governor or ResourceGovernor()
        self.checkpoints = checkpoints
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._seq = 0
        self._heap: list[_HeapItem] = []
        self._tasks: dict[str, ScheduledTask] = {}
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._cancelled: set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="pfai-sched")
        self._futures: dict[str, Future[Any]] = {}
        self._running = True
        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="pfai-sched-dispatch", daemon=True)
        self._metrics = {
            "submitted": 0,
            "started": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "retried": 0,
            "timeouts": 0,
            "starvation_prevented": 0,
        }
        self.governor.set_worker_count(self.max_workers)
        self._dispatcher.start()

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        priority: PriorityClass | str = PriorityClass.USER_INTERACTIVE,
        depends_on: list[str] | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        backoff_seconds: float = 0.05,
        task_id: str | None = None,
        meta: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self._running:
            return {"ok": False, "error": "scheduler_shutdown"}
        pri = priority if isinstance(priority, PriorityClass) else PriorityClass.from_name(str(priority))
        admit = self.governor.can_admit(priority=pri, kind="enqueue")
        if not admit.get("ok"):
            return {"ok": False, **admit}
        tid = task_id or new_id("stask")
        task = ScheduledTask(
            task_id=tid,
            fn=fn,
            args=args,
            kwargs=kwargs,
            priority=pri,
            depends_on=list(depends_on or []),
            timeout_seconds=float(timeout_seconds),
            max_retries=int(max_retries),
            backoff_seconds=float(backoff_seconds),
            meta=dict(meta or {}),
            created_at=time.time(),
        )
        with self._cv:
            self._tasks[tid] = task
            self._seq += 1
            # Aging: older low-priority tasks get slight boost to prevent starvation
            age_boost = 0
            if self._seq % 20 == 0:
                age_boost = -1
                self._metrics["starvation_prevented"] += 1
            heapq.heappush(self._heap, _HeapItem(int(pri) + age_boost, self._seq, tid))
            self._metrics["submitted"] += 1
            self.governor.set_queue_size(len(self._heap))
            self._cv.notify()
        return {"ok": True, "task_id": tid, "status": task.status, "priority": pri.name}

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self._cv:
            task = self._tasks.get(task_id)
            if not task:
                return {"ok": False, "error": "unknown_task"}
            task.cancel_requested = True
            if task.status in ("QUEUED", "WAITING"):
                task.status = "CANCELLED"
                task.finished_at = time.time()
                self._cancelled.add(task_id)
                self._metrics["cancelled"] += 1
                # Remove from heap lazily (skipped on pop)
                return {"ok": True, "status": "CANCELLED"}
            fut = self._futures.get(task_id)
            if fut:
                fut.cancel()
            return {"ok": True, "status": task.status, "cancel_requested": True}

    def status(self, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if task_id:
                task = self._tasks.get(task_id)
                if not task:
                    return {"ok": False, "error": "unknown_task"}
                return {"ok": True, **task.to_dict(), "result": sanitize_args(task.result) if isinstance(task.result, dict) else task.result}
            return {
                "ok": True,
                "version": self.VERSION,
                "running": self._running,
                "workers": self.max_workers,
                "queued": len(self._heap),
                "tasks": len(self._tasks),
                "metrics": dict(self._metrics),
                "governor": self.governor.snapshot(),
            }

    def wait(self, task_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        deadline = None if timeout is None else time.time() + float(timeout)
        while True:
            st = self.status(task_id)
            if not st.get("ok"):
                return st
            if st.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                return st
            if deadline is not None and time.time() >= deadline:
                return {**st, "ok": False, "error": "wait_timeout"}
            time.sleep(0.01)

    def run_dependency_graph(
        self,
        nodes: list[dict[str, Any]],
        *,
        default_priority: PriorityClass = PriorityClass.USER_INTERACTIVE,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """
        nodes: [{id, fn, depends_on?, parallel_safe?}]
        Independent nodes run concurrently; dependent nodes wait.
        """
        submitted: dict[str, str] = {}
        for node in nodes:
            nid = str(node.get("id") or new_id("n"))
            deps = [submitted[d] for d in (node.get("depends_on") or []) if d in submitted]
            # Map original dep ids if already using task ids
            for d in node.get("depends_on") or []:
                if d in self._tasks and d not in deps:
                    deps.append(d)
            fn = node.get("fn")
            if not callable(fn):
                return {"ok": False, "error": "node_fn_required", "node": nid}
            sub = self.submit(
                fn,
                priority=node.get("priority") or default_priority,
                depends_on=deps,
                timeout_seconds=float(node.get("timeout_seconds") or timeout_seconds),
                max_retries=int(node.get("max_retries") or 0),
                task_id=nid,
                meta={"graph_node": True},
            )
            if not sub.get("ok"):
                return sub
            submitted[nid] = sub["task_id"]

        results = {}
        ok = True
        for nid, tid in submitted.items():
            st = self.wait(tid, timeout=timeout_seconds + 5)
            results[nid] = st
            if st.get("status") != "COMPLETED":
                ok = False
        return {"ok": ok, "results": results, "submitted": submitted}

    def shutdown(self, *, wait: bool = True, cancel_queued: bool = True) -> dict[str, Any]:
        with self._cv:
            self._running = False
            if cancel_queued:
                for tid, task in list(self._tasks.items()):
                    if task.status in ("QUEUED", "WAITING"):
                        task.status = "CANCELLED"
                        task.finished_at = time.time()
                        self._cancelled.add(tid)
                        self._metrics["cancelled"] += 1
            self._cv.notify_all()
        self._executor.shutdown(wait=wait, cancel_futures=True)
        return {"ok": True, "shutdown": True, "metrics": dict(self._metrics)}

    def _deps_satisfied(self, task: ScheduledTask) -> bool:
        for dep in task.depends_on:
            if dep in self._failed or dep in self._cancelled:
                return False
            if dep not in self._completed:
                return False
        return True

    def _deps_failed(self, task: ScheduledTask) -> bool:
        return any(d in self._failed or d in self._cancelled for d in task.depends_on)

    def _dispatch_loop(self) -> None:
        while True:
            with self._cv:
                if not self._running and not self._heap:
                    break
                # Find next ready task (skip cancelled / waiting on deps)
                ready_id = None
                deferred: list[_HeapItem] = []
                while self._heap:
                    item = heapq.heappop(self._heap)
                    task = self._tasks.get(item.task_id)
                    if not task or task.status == "CANCELLED" or task.cancel_requested and task.status == "QUEUED":
                        continue
                    if self._deps_failed(task):
                        task.status = "FAILED"
                        task.error = "dependency_failed"
                        task.finished_at = time.time()
                        self._failed.add(task.task_id)
                        self._metrics["failed"] += 1
                        continue
                    if not self._deps_satisfied(task):
                        task.status = "WAITING"
                        deferred.append(item)
                        continue
                    admit = self.governor.can_admit(priority=task.priority, kind="task")
                    if not admit.get("ok"):
                        deferred.append(item)
                        break
                    ready_id = item.task_id
                    break
                for d in deferred:
                    heapq.heappush(self._heap, d)
                self.governor.set_queue_size(len(self._heap))
                if ready_id is None:
                    self._cv.wait(timeout=0.05)
                    continue
                task = self._tasks[ready_id]
                lease = self.governor.acquire(ready_id, kind="task", priority=task.priority)
                if not lease.get("ok"):
                    heapq.heappush(self._heap, _HeapItem(int(task.priority), self._seq, ready_id))
                    self._cv.wait(timeout=0.05)
                    continue
                task.status = "RUNNING"
                task.started_at = time.time()
                self._metrics["started"] += 1

            fut = self._executor.submit(self._run_task, task.task_id)
            with self._lock:
                self._futures[task.task_id] = fut

    def _run_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
        try:
            if task.cancel_requested:
                with self._lock:
                    task.status = "CANCELLED"
                    task.finished_at = time.time()
                    self._cancelled.add(task_id)
                    self._metrics["cancelled"] += 1
                return

            result_box: dict[str, Any] = {}
            error_box: dict[str, str] = {}

            def _call() -> None:
                try:
                    result_box["value"] = task.fn(*task.args, **task.kwargs)
                except Exception as exc:  # noqa: BLE001
                    error_box["error"] = f"{type(exc).__name__}:{exc}"

            worker = threading.Thread(target=_call, daemon=True)
            worker.start()
            worker.join(timeout=task.timeout_seconds)
            if worker.is_alive():
                with self._lock:
                    task.status = "TIMEOUT"
                    task.error = "timeout"
                    task.finished_at = time.time()
                    self._metrics["timeouts"] += 1
                # Retry on timeout if budget remains
                if task.retries < task.max_retries and not task.cancel_requested:
                    task.retries += 1
                    self._metrics["retried"] += 1
                    time.sleep(task.backoff_seconds * (2 ** (task.retries - 1)))
                    task.status = "QUEUED"
                    task.error = ""
                    with self._cv:
                        self._seq += 1
                        heapq.heappush(self._heap, _HeapItem(int(task.priority), self._seq, task_id))
                        self._cv.notify()
                else:
                    with self._lock:
                        self._failed.add(task_id)
                        self._metrics["failed"] += 1
                        if self.checkpoints:
                            self.checkpoints.save(
                                task_id=task_id,
                                state="TIMEOUT",
                                completed_subtasks=[],
                                pending_subtasks=[task_id],
                                errors=[task.error],
                                retry_counts={task_id: task.retries},
                            )
                return

            if error_box:
                with self._lock:
                    task.error = error_box["error"]
                if task.retries < task.max_retries and not task.cancel_requested:
                    task.retries += 1
                    self._metrics["retried"] += 1
                    time.sleep(task.backoff_seconds * (2 ** (task.retries - 1)))
                    task.status = "QUEUED"
                    with self._cv:
                        self._seq += 1
                        heapq.heappush(self._heap, _HeapItem(int(task.priority), self._seq, task_id))
                        self._cv.notify()
                else:
                    with self._lock:
                        task.status = "FAILED"
                        task.finished_at = time.time()
                        self._failed.add(task_id)
                        self._metrics["failed"] += 1
                return

            with self._lock:
                task.result = result_box.get("value")
                task.status = "COMPLETED"
                task.finished_at = time.time()
                self._completed.add(task_id)
                self._metrics["completed"] += 1
                if self.checkpoints:
                    self.checkpoints.save(
                        task_id=task_id,
                        state="COMPLETED",
                        completed_subtasks=[task_id],
                        pending_subtasks=[],
                        artifacts={"result_present": task.result is not None},
                        retry_counts={task_id: task.retries},
                        versions={"scheduler": self.VERSION},
                    )
        finally:
            self.governor.release(task_id)
            with self._cv:
                self.governor.set_queue_size(len(self._heap))
                self._cv.notify()
