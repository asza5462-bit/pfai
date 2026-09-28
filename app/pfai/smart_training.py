"""Smart real training controller — start actual LoRA cycles when ready.

Honest:
- Never claims training executed unless the trainer really ran.
- Never silent-activates weights (activate_if_pass defaults False).
- Surfaces blockers clearly (backend / budget / growth).
"""
from __future__ import annotations

import logging
import os
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

    def start(
        self,
        *,
        owner_requested: bool = True,
        activate_if_pass: bool = False,
        force_prepare: bool = True,
    ) -> dict[str, Any]:
        t0 = time.time()
        prep = self.prepare() if force_prepare else {"ok": True, "skipped": True}
        diag = self.diagnose()
        # Owner-requested path still goes to the trainer — orchestrator decides.
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

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "version": self.VERSION,
            "runs": self._runs,
            "last": {
                k: (self._last or {}).get(k)
                for k in ("ok", "cycle", "diagnosis_before", "elapsed_ms")
            },
            "read_only": False,
            "write_path": True,
            "can_start_from_chat": True,
            "auto_promote": False,
            "env_allow_cpu": (os.environ.get("TRAINING_ALLOW_CPU") or "true"),
        }
