"""Smart real training controller — start actual LoRA cycles when ready.

Honest:
- Never claims training executed unless the trainer really ran.
- Never silent-activates weights (activate_if_pass defaults False).
- Surfaces blockers clearly (backend / budget / growth).
- Supports async start so free-tier HTTP timeouts cannot kill long LoRA runs.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.smart_training")


class SmartTrainingController:
    VERSION = "8.10.0"

    def __init__(
        self,
        *,
        eligibility_fn: Callable[[], dict],
        run_cycle_fn: Callable[..., dict],
        continuous_tick_fn: Optional[Callable[[], dict]] = None,
        experience_push_fn: Optional[Callable[[], dict]] = None,
    ) -> None:
        self.eligibility_fn = eligibility_fn
        self.run_cycle_fn = run_cycle_fn
        self.continuous_tick_fn = continuous_tick_fn
        self.experience_push_fn = experience_push_fn
        self._runs = 0
        self._last: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._bg_lock = threading.Lock()
        self._bg_thread: threading.Thread | None = None
        self._bg_running = False
        self._bg_started_at: float | None = None

    def diagnose(self) -> dict[str, Any]:
        elig = self.eligibility_fn() or {}
        blockers = list(elig.get("blockers") or elig.get("reasons") or [])
        reason = elig.get("reason") or (blockers[0] if blockers else None)
        return {
            "ok": True,
            "eligible": bool(elig.get("eligible")),
            "reason": reason,
            "blockers": blockers,
            "gates": elig.get("gates") or {},
            "status": elig.get("status"),
            "can_start_from_chat": True,
            "write_path": True,
            "read_only": False,
            "auto_promote": False,
            "async_running": self._bg_running,
            "version": self.VERSION,
            "note": (
                "Training is a write path from chat. "
                "Activation stays explicit (activate_if_pass)."
            ),
        }

    def prepare(self) -> dict[str, Any]:
        """Grow/curate experience before a weight cycle when possible."""
        out: dict[str, Any] = {"ok": True, "steps": []}
        if self.experience_push_fn:
            try:
                pushed = self.experience_push_fn() or {}
                out["steps"].append({"step": "experience", "ok": True, **{k: pushed.get(k) for k in ("pushed", "accepted")}})
            except Exception as exc:
                out["steps"].append({"step": "experience", "ok": False, "error": str(exc)[:160]})
        if self.continuous_tick_fn:
            try:
                tick = self.continuous_tick_fn() or {}
                out["steps"].append({"step": "continuous_tick", "ok": bool(tick.get("ok"))})
            except Exception as exc:
                out["steps"].append({"step": "continuous_tick", "ok": False, "error": str(exc)[:160]})
        return out

    def _execute(
        self,
        *,
        owner_requested: bool,
        activate_if_pass: bool,
        force_prepare: bool,
    ) -> dict[str, Any]:
        t0 = time.time()
        prep = self.prepare() if force_prepare else {"ok": True, "skipped": True}
        diag = self.diagnose()
        try:
            result = self.run_cycle_fn(
                owner_requested=bool(owner_requested),
                activate_if_pass=bool(activate_if_pass),
            ) or {}
        except Exception as exc:
            result = {
                "ok": False,
                "status": "ERROR",
                "error": str(exc)[:240],
                "actual_training_executed": False,
                "model_activated": False,
            }
        executed = bool(
            result.get("actual_training_executed")
            or result.get("real_training_executed")
            or result.get("trained")
        )
        with self._lock:
            self._runs += 1
            out = {
                "ok": bool(result.get("ok")) or executed,
                "write_path": True,
                "read_only": False,
                "can_start_from_chat": True,
                "prepared": prep,
                "diagnosis_before": {
                    "eligible": diag.get("eligible"),
                    "reason": diag.get("reason"),
                    "blockers": diag.get("blockers"),
                },
                "cycle": {
                    "status": result.get("status"),
                    "reason": result.get("reason") or result.get("error"),
                    "job_id": (result.get("job") or {}).get("job_id") if isinstance(result.get("job"), dict) else result.get("job_id"),
                    "actual_training_executed": executed,
                    "model_activated": bool(result.get("model_activated")),
                    "activate_if_pass": bool(activate_if_pass),
                },
                "raw_status": result.get("status"),
                "elapsed_ms": int((time.time() - t0) * 1000),
                "runs": self._runs,
                "auto_promote": False,
                "weight_promotion": "never_auto" if not activate_if_pass else "explicit_activate_if_pass",
                "async": False,
                "honesty": (
                    "actual_training_executed is true only when the real trainer ran. "
                    "Missing torch/transformers ⇒ TRAINING_BACKEND_UNAVAILABLE (not faked)."
                ),
                "version": self.VERSION,
            }
            self._last = out
        log.info(
            "smart_training start executed=%s status=%s reason=%s",
            executed,
            out["cycle"].get("status"),
            out["cycle"].get("reason"),
        )
        return out

    def start(
        self,
        *,
        owner_requested: bool = True,
        activate_if_pass: bool = False,
        force_prepare: bool = True,
        async_mode: bool | None = None,
    ) -> dict[str, Any]:
        """Start a real LoRA cycle. Default async on production so HTTP cannot kill the run."""
        if async_mode is None:
            async_mode = (os.environ.get("PFAI_TRAINING_ASYNC") or "1").strip().lower() in {
                "1", "true", "on", "yes",
            }
        if not async_mode:
            return self._execute(
                owner_requested=owner_requested,
                activate_if_pass=activate_if_pass,
                force_prepare=force_prepare,
            )
        return self.start_async(
            owner_requested=owner_requested,
            activate_if_pass=activate_if_pass,
            force_prepare=force_prepare,
        )

    def start_async(
        self,
        *,
        owner_requested: bool = True,
        activate_if_pass: bool = False,
        force_prepare: bool = True,
    ) -> dict[str, Any]:
        """Accept a training request and run the real cycle on a daemon thread."""
        if self._bg_running or (self._bg_thread and self._bg_thread.is_alive()):
            return {
                "ok": False,
                "write_path": True,
                "read_only": False,
                "can_start_from_chat": True,
                "async": True,
                "async_accepted": False,
                "async_running": True,
                "status": "ALREADY_RUNNING",
                "cycle": {
                    "status": "ALREADY_RUNNING",
                    "reason": "A real training cycle is already running",
                    "job_id": (self._last.get("cycle") or {}).get("job_id"),
                    "actual_training_executed": False,
                    "model_activated": False,
                    "activate_if_pass": bool(activate_if_pass),
                },
                "auto_promote": False,
                "version": self.VERSION,
                "note": "Poll smart_training_status — do not claim execution until finished.",
            }
        if not self._bg_lock.acquire(blocking=False):
            return {
                "ok": False,
                "write_path": True,
                "read_only": False,
                "async": True,
                "async_accepted": False,
                "async_running": True,
                "status": "ALREADY_RUNNING",
                "cycle": {
                    "status": "ALREADY_RUNNING",
                    "actual_training_executed": False,
                    "model_activated": False,
                    "activate_if_pass": bool(activate_if_pass),
                },
                "auto_promote": False,
                "version": self.VERSION,
            }

        prep = self.prepare() if force_prepare else {"ok": True, "skipped": True}
        diag = self.diagnose()
        self._bg_running = True
        self._bg_started_at = time.time()

        def _worker() -> None:
            try:
                self._execute(
                    owner_requested=owner_requested,
                    activate_if_pass=activate_if_pass,
                    force_prepare=False,  # already prepared
                )
            finally:
                self._bg_running = False
                try:
                    self._bg_lock.release()
                except RuntimeError:
                    pass

        t = threading.Thread(target=_worker, name="pfai-smart-training", daemon=True)
        self._bg_thread = t
        t.start()
        return {
            "ok": True,
            "write_path": True,
            "read_only": False,
            "can_start_from_chat": True,
            "async": True,
            "async_accepted": True,
            "async_running": True,
            "status": "STARTED_ASYNC",
            "prepared": prep,
            "diagnosis_before": {
                "eligible": diag.get("eligible"),
                "reason": diag.get("reason"),
                "blockers": diag.get("blockers"),
            },
            "cycle": {
                "status": "STARTED_ASYNC",
                "reason": "Real LoRA cycle accepted — running in background",
                "job_id": None,
                "actual_training_executed": False,  # honest: not finished yet
                "model_activated": False,
                "activate_if_pass": bool(activate_if_pass),
            },
            "auto_promote": False,
            "weight_promotion": "never_auto" if not activate_if_pass else "explicit_activate_if_pass",
            "started_at": self._bg_started_at,
            "version": self.VERSION,
            "honesty": (
                "async_accepted means the real trainer was scheduled. "
                "actual_training_executed becomes true only after the background cycle finishes — "
                "poll smart_training_status."
            ),
            "note": "Poll smart_training_status /platform/training/status for completion.",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            last = dict(self._last or {})
        return {
            "ok": True,
            "version": self.VERSION,
            "runs": self._runs,
            "async_running": bool(self._bg_running),
            "async_started_at": self._bg_started_at,
            "last": {
                k: last.get(k)
                for k in ("ok", "cycle", "diagnosis_before", "elapsed_ms", "async", "status")
            },
            "read_only": False,
            "write_path": True,
            "can_start_from_chat": True,
            "auto_promote": False,
            "env_allow_cpu": (os.environ.get("TRAINING_ALLOW_CPU") or "true"),
            "env_async": (os.environ.get("PFAI_TRAINING_ASYNC") or "1"),
        }
