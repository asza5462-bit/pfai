"""Unified Super Brain — one pulse, one mind, minimal lag.

Aggregates ops + learning + advanced self-develop + web readiness into a single
coherent snapshot (optional one safe action). Designed for chat speed:
parallel local reads, no stacked redundant tools, honest about network bounds.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.unified_brain")


def unified_brain_enabled() -> bool:
    v = os.environ.get("PFAI_UNIFIED_BRAIN", "").strip().lower()
    if v in {"0", "false", "off", "no"}:
        return False
    if v in {"1", "true", "on", "yes"}:
        return True
    # Default ON in public/open/production — Command Chat is the single brain
    from pfai.open_execution import open_chat_tools
    return open_chat_tools()


class UnifiedBrain:
    def __init__(
        self,
        *,
        health_fn: Callable[[], dict],
        continuous_fn: Callable[[], dict],
        advanced_fn: Callable[[], dict],
        autonomy_fn: Callable[[], dict],
        web_fn: Callable[[], dict],
        academy_fn: Callable[[], dict] | None = None,
        improve_fn: Callable[[], dict] | None = None,
        develop_fn: Callable[[], dict] | None = None,
    ) -> None:
        self.health_fn = health_fn
        self.continuous_fn = continuous_fn
        self.advanced_fn = advanced_fn
        self.autonomy_fn = autonomy_fn
        self.web_fn = web_fn
        self.academy_fn = academy_fn
        self.improve_fn = improve_fn
        self.develop_fn = develop_fn

    def _safe(self, name: str, fn: Callable[[], dict], timeout_s: float = 2.5) -> dict[str, Any]:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(fn)
                out = fut.result(timeout=max(0.2, float(timeout_s)))
            if not isinstance(out, dict):
                out = {"ok": True, "value": out}
            out.setdefault("ok", True)
            out["_ms"] = int((time.time() - t0) * 1000)
            out["_lane"] = name
            return out
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc)[:240],
                "_ms": int((time.time() - t0) * 1000),
                "_lane": name,
                "degraded": True,
            }

    def pulse(
        self,
        *,
        action: str = "status",
        message: str = "",
        include_action: bool = True,
    ) -> dict[str, Any]:
        """One-mind snapshot (+ optional single safe action). Never promotes weights."""
        t0 = time.time()
        action = (action or "status").strip().lower()
        lanes: dict[str, Callable[[], dict]] = {
            "health": self.health_fn,
            "continuous": self.continuous_fn,
            "advanced": self.advanced_fn,
            "autonomy": self.autonomy_fn,
            "web": self.web_fn,
        }
        if self.academy_fn:
            lanes["academy"] = self.academy_fn

        snap: dict[str, Any] = {}
        # Parallel local reads — hard cap concurrency
        with ThreadPoolExecutor(max_workers=min(6, len(lanes))) as pool:
            futs = {pool.submit(self._safe, name, fn): name for name, fn in lanes.items()}
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    snap[name] = fut.result()
                except Exception as exc:
                    snap[name] = {"ok": False, "error": str(exc), "degraded": True, "_lane": name}

        action_out: Optional[dict[str, Any]] = None
        if include_action and action in {"improve", "heal", "self_improve"} and self.improve_fn:
            action_out = self._safe("action_improve", self.improve_fn, timeout_s=12.0)
        elif include_action and action in {"develop", "build", "self_develop", "advanced"} and self.develop_fn:
            action_out = self._safe("action_develop", self.develop_fn, timeout_s=20.0)
        elif include_action and action in {"auto", "smart"}:
            # Prefer develop when advanced stage is ready, else improve
            stage = ((snap.get("advanced") or {}).get("maturity") or snap.get("advanced") or {}).get("stage")
            if stage in {"capable", "advanced", "sovereign_safe"} and self.develop_fn:
                action_out = self._safe("action_develop", self.develop_fn, timeout_s=20.0)
            elif self.improve_fn:
                action_out = self._safe("action_improve", self.improve_fn, timeout_s=12.0)

        errors = [k for k, v in snap.items() if isinstance(v, dict) and not v.get("ok")]
        elapsed = int((time.time() - t0) * 1000)
        return {
            "ok": len(errors) == 0 or len(errors) < len(snap),  # soft-ok if majority healthy
            "unified": True,
            "mind": "one_brain",
            "message": (message or "")[:240],
            "action": action,
            "snapshot": {
                "health": (snap.get("health") or {}).get("status") or (snap.get("health") or {}).get("ok"),
                "continuous_worker": (snap.get("continuous") or {}).get("worker_alive"),
                "advanced_stage": (
                    ((snap.get("advanced") or {}).get("maturity") or {}).get("stage")
                    or (snap.get("advanced") or {}).get("stage")
                ),
                "web": (snap.get("web") or {}).get("WEB_FABRIC_STATUS"),
                "academy_tracks": (snap.get("academy") or {}).get("tracks") or (snap.get("academy") or {}).get("count"),
            },
            "lanes": snap,
            "action_result": action_out,
            "degraded_lanes": errors,
            "elapsed_ms": elapsed,
            "weight_promotion": "never_auto",
            "latency_class": "local_parallel" if elapsed < 1500 else ("mixed" if elapsed < 8000 else "network_bound"),
            "note": (
                "Unified pulse: parallel local lanes. "
                "Network web/search still bounded by provider latency — never invented."
            ),
        }

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "unified_brain": True,
            "enabled": unified_brain_enabled(),
            "weight_promotion": "never_auto",
        }
