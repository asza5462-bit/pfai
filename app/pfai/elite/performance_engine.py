"""PHASE 21 Performance & Reliability Engine — facade over scheduler, budgets, cache, latency, governor."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from pfai.authorized_execution import sanitize_args
from pfai.elite.adaptive_budgets import AdaptiveBudgetSelector
from pfai.elite.checkpoint_store import CheckpointStore
from pfai.elite.execution_scheduler import ExecutionScheduler
from pfai.elite.failure_recovery_v21 import BoundedRecoveryPolicy
from pfai.elite.latency_pipeline import LatencyPipeline
from pfai.elite.performance_model_router import PerformanceModelRouter
from pfai.elite.priority_classes import PriorityClass
from pfai.elite.resource_governor import ResourceGovernor
from pfai.elite.result_cache import ResultCache
from pfai.elite.task_decomposer import TaskDecomposer
from pfai.elite.types import new_id


class PerformanceReliabilityEngine:
    VERSION = "21.0.0"

    def __init__(
        self,
        orchestrator: Any = None,
        *,
        root: str = "data/longevity/elite/phase21",
        max_workers: int = 4,
    ) -> None:
        self.orch = orchestrator
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.governor = ResourceGovernor()
        self.cache = ResultCache()
        self.checkpoints = CheckpointStore(root=str(self.root / "checkpoints"))
        self.scheduler = ExecutionScheduler(
            max_workers=max_workers,
            governor=self.governor,
            checkpoints=self.checkpoints,
        )
        self.budgets = AdaptiveBudgetSelector()
        self.decomposer = TaskDecomposer()
        self.recovery = BoundedRecoveryPolicy(max_retries=2)
        self.model_router = PerformanceModelRouter(
            getattr(orchestrator, "model_router", None) if orchestrator else None
        )
        self.metrics_path = self.root / "metrics.jsonl"
        self._task_index: dict[str, dict[str, Any]] = {}

    def _metric(self, name: str, value: float, **fields: Any) -> None:
        row = {"ts": time.time(), "metric": name, "value": float(value), **sanitize_args(fields)}
        with self.metrics_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def submit_task(
        self,
        message: str,
        *,
        priority: str = "USER_INTERACTIVE",
        actor: str = "",
        approved: bool = False,
        context: dict[str, Any] | None = None,
        fn: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        for k in ("role", "admin", "is_admin", "owner_flag", "authorization", "privileges"):
            ctx.pop(k, None)
        lat = LatencyPipeline()
        lat.mark("routing_started")
        plan = self.decomposer.decompose(message, context=ctx)
        lat.mark("routing_completed", capabilities=plan.get("capabilities"))
        lat.mark("planning_started")
        budget_sel = self.budgets.select(
            message,
            capabilities=plan.get("capabilities"),
            context=ctx,
            forced_tier=ctx.get("budget_tier"),
        )
        lat.mark("planning_completed", tier=budget_sel.get("tier"), decomposed=plan.get("decomposed"))

        model_info = self.model_router.route(
            message,
            capabilities=plan.get("capabilities"),
            tier=str(budget_sel.get("tier") or "NORMAL"),
            prefer_lightweight=bool((budget_sel.get("profile") or {}).get("prefer_lightweight_model")),
            escalate=bool((plan.get("complexity") or {}).get("needs_model_escalation")),
        )

        task_id = new_id("p21")
        profile = budget_sel.get("profile") or {}
        timeout = float((profile.get("budgets") or {}).get("max_execution_time_seconds") or 60.0)

        def _default_run() -> dict[str, Any]:
            # Execute via agent engine when complex; else lightweight answer path
            if self.orch is None:
                return {"ok": True, "answer": f"Scheduled: {message[:120]}", "plan": plan}
            complexity = plan.get("complexity") or {}
            if complexity.get("decompose") or ctx.get("force_agent_engine"):
                from pfai.elite.agent_execution_engine import AgentExecutionEngine

                return AgentExecutionEngine(self.orch).run(
                    message, approved=approved, actor=actor, context=ctx
                )
            from pfai.elite.unified_ai_core import UnifiedAICore

            return UnifiedAICore(self.orch).handle(
                message, approved=approved, actor=actor, context=ctx
            )

        run_fn = fn or _default_run
        lat.mark("execution_started")
        sub = self.scheduler.submit(
            run_fn,
            priority=PriorityClass.from_name(priority),
            timeout_seconds=min(timeout, 120.0),
            max_retries=int((profile.get("budgets") or {}).get("max_retries") or 1),
            task_id=task_id,
            meta={
                "message_preview": (message or "")[:200],
                "tier": budget_sel.get("tier"),
                "actor": actor,
                "approved": bool(approved),
            },
        )
        if not sub.get("ok"):
            return {**sub, "latency": lat.summary(), "PHASE_22_ALLOWED": False}

        self.checkpoints.save(
            task_id=task_id,
            state="QUEUED",
            completed_subtasks=[],
            pending_subtasks=[s.get("step_id") for s in (plan.get("steps") or [])],
            dependencies=[],
            versions={"engine": self.VERSION, "model": str(model_info.get("provider_id") or "")},
            meta={"tier": budget_sel.get("tier"), "plan_id": plan.get("plan_id")},
        )
        self._task_index[task_id] = {
            "plan": plan,
            "budget": budget_sel.get("profile"),
            "model": {k: model_info.get(k) for k in ("ok", "available", "role", "provider_id", "error") if k in model_info},
            "latency": lat,
            "priority": priority,
        }
        return {
            "ok": True,
            "task_id": task_id,
            "status": "QUEUED",
            "priority": priority,
            "tier": budget_sel.get("tier"),
            "plan": plan,
            "model": self._task_index[task_id]["model"],
            "latency": lat.summary(),
            "phase": 21,
            "PHASE_22_ALLOWED": False,
        }

    def task_status(self, task_id: str) -> dict[str, Any]:
        st = self.scheduler.status(task_id)
        meta = self._task_index.get(task_id) or {}
        ckpt = self.checkpoints.load(task_id)
        out = {**st, "checkpoint": ckpt, "tier": (meta.get("budget") or {}).get("name"), "phase": 21}
        if meta.get("latency"):
            out["latency"] = meta["latency"].summary()
        return out

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return {**self.scheduler.cancel(task_id), "phase": 21}

    def task_progress(self, task_id: str) -> dict[str, Any]:
        st = self.task_status(task_id)
        status = st.get("status")
        mapping = {
            "QUEUED": 5,
            "WAITING": 15,
            "RUNNING": 50,
            "COMPLETED": 100,
            "FAILED": 100,
            "CANCELLED": 100,
            "TIMEOUT": 100,
        }
        return {
            "ok": True,
            "task_id": task_id,
            "status": status,
            "progress_percent": mapping.get(status, 0),
            "fabricated": False,
            "checkpoint_id": (st.get("checkpoint") or {}).get("checkpoint_id"),
        }

    def resume_task(self, task_id: str) -> dict[str, Any]:
        plan = self.checkpoints.resume_plan(task_id)
        return {**plan, "phase": 21}

    def parallel_tools(
        self,
        calls: list[dict[str, Any]],
        *,
        execute_fn: Callable[[dict[str, Any]], Any],
        priority: str = "USER_INTERACTIVE",
    ) -> dict[str, Any]:
        """Run independent tool calls concurrently; dependent ones sequentially via scheduler graph."""
        lat = LatencyPipeline()
        lat.mark("tool_started", count=len(calls))
        nodes = []
        for i, call in enumerate(calls):
            cid = str(call.get("id") or f"tool-{i}")
            deps = list(call.get("depends_on") or [])
            nodes.append(
                {
                    "id": cid,
                    "depends_on": deps,
                    "fn": (lambda c=call: execute_fn(c)),
                    "priority": PriorityClass.from_name(priority),
                    "timeout_seconds": float(call.get("timeout_seconds") or 20.0),
                }
            )
        t0 = time.time()
        out = self.scheduler.run_dependency_graph(nodes, timeout_seconds=30.0)
        elapsed = time.time() - t0
        lat.mark("tool_completed", elapsed=elapsed)
        # Parallel speedup estimate only when >=2 independent nodes completed
        independent = [c for c in calls if not c.get("depends_on")]
        speedup = None
        source = "not_available"
        if out.get("ok") and len(independent) >= 2:
            # Measured wall time vs sum of per-node times if available
            per = []
            for nid, st in (out.get("results") or {}).items():
                if st.get("started_at") and st.get("finished_at"):
                    per.append(float(st["finished_at"]) - float(st["started_at"]))
            if per and elapsed > 0:
                sequential_est = sum(per)
                speedup = sequential_est / elapsed if elapsed else None
                source = "measured"
        self._metric("parallel_tools_latency", elapsed, count=len(calls))
        return {
            "ok": out.get("ok"),
            "results": out.get("results"),
            "wall_latency": elapsed,
            "parallel_speedup": speedup,
            "parallel_speedup_source": source,
            "latency": lat.summary(),
            "authorization_bypassed": False,
        }

    def cache_get_or_put(
        self,
        *,
        namespace: str,
        payload: dict[str, Any],
        producer: Callable[[], dict[str, Any]],
        model_version: str = "",
        skill_version: str = "",
        ttl_seconds: float = 60.0,
    ) -> dict[str, Any]:
        key = self.cache.make_key(
            namespace=namespace,
            payload=payload,
            model_version=model_version,
            skill_version=skill_version,
        )
        hit = self.cache.get(key)
        if hit is not None:
            return {"ok": True, "cache": "hit", "value": hit, "stale": False}
        value = producer()
        put = self.cache.put(key, value if isinstance(value, dict) else {"result": value}, ttl_seconds=ttl_seconds)
        return {"ok": True, "cache": "miss", "value": value, "put": put}

    def scheduler_status(self) -> dict[str, Any]:
        return {
            **self.scheduler.status(),
            "cache": self.cache.stats(),
            "governor": self.governor.snapshot(),
            "phase": 21,
            "PHASE_22_ALLOWED": False,
            "version": self.VERSION,
        }

    def shutdown(self) -> dict[str, Any]:
        return self.scheduler.shutdown(wait=True, cancel_queued=True)
