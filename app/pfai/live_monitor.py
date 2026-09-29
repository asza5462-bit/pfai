"""Live System Monitor — 24/7 supervisor for continuous learn + train + heal.

Keeps productive loops alive and audited. Never silent-promotes model weights.
Real work: ensure workers, tick curation, attempt LoRA when eligible, heal, develop.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.live_monitor")


class LiveSystemMonitor:
    """Strong live supervisor bound into evolution / chat / boot."""

    VERSION = "8.13.0"

    def __init__(
        self,
        *,
        continuous_ensure_fn: Optional[Callable[[], dict]] = None,
        continuous_tick_fn: Optional[Callable[[], dict]] = None,
        continuous_status_fn: Optional[Callable[[], dict]] = None,
        evolution_ensure_fn: Optional[Callable[[], dict]] = None,
        evolution_status_fn: Optional[Callable[[], dict]] = None,
        training_eligibility_fn: Optional[Callable[[], dict]] = None,
        training_start_fn: Optional[Callable[[], dict]] = None,
        training_status_fn: Optional[Callable[[], dict]] = None,
        heal_fn: Optional[Callable[[], dict]] = None,
        develop_fn: Optional[Callable[[], dict]] = None,
        sovereign_fn: Optional[Callable[[], dict]] = None,
        memory_heal_fn: Optional[Callable[[], dict]] = None,
        interval_seconds: int = 90,
    ) -> None:
        self.continuous_ensure_fn = continuous_ensure_fn
        self.continuous_tick_fn = continuous_tick_fn
        self.continuous_status_fn = continuous_status_fn
        self.evolution_ensure_fn = evolution_ensure_fn
        self.evolution_status_fn = evolution_status_fn
        self.training_eligibility_fn = training_eligibility_fn
        self.training_start_fn = training_start_fn
        self.training_status_fn = training_status_fn
        self.heal_fn = heal_fn
        self.develop_fn = develop_fn
        self.sovereign_fn = sovereign_fn
        self.memory_heal_fn = memory_heal_fn
        self.interval_seconds = max(30, int(interval_seconds))
        self._train_cooldown_seconds = 900  # at most one LoRA start / 15 min
        self._last_train_ts = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "running": False,
            "alive": False,
            "pulses": 0,
            "last_pulse": None,
            "last_error": None,
            "started_at": None,
            "actions": [],
            "weight_promotion": "never_auto",
        }

    def _alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _safe(self, label: str, fn: Optional[Callable[[], dict]]) -> dict[str, Any]:
        if not fn:
            return {"ok": False, "skipped": True, "reason": "no_fn", "label": label}
        t0 = time.time()
        try:
            out = fn() or {}
            if not isinstance(out, dict):
                out = {"ok": True, "value": out}
            out.setdefault("ok", True)
            out["_label"] = label
            out["_ms"] = int((time.time() - t0) * 1000)
            return out
        except Exception as exc:
            log.warning("live_monitor %s failed: %s", label, exc)
            return {"ok": False, "error": str(exc)[:240], "_label": label}

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._alive():
                return {**self.status(), "ok": True, "already": True}
            self._stop.clear()
            self._state["running"] = True
            self._state["started_at"] = time.time()
            self._state["last_error"] = None
            t = threading.Thread(target=self._loop, name="pfai-live-monitor", daemon=True)
            self._thread = t
            t.start()
            self._state["alive"] = True
            log.info("live monitor started interval=%ss", self.interval_seconds)
            return {**self.status(), "ok": True}

    def stop(self, reason: str = "operator") -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            self._state["running"] = False
            self._state["alive"] = False
            self._state["last_error"] = reason
        return {**self.status(), "ok": True, "stopped": True}

    def pulse(self, *, deep: bool = False, train_if_eligible: bool = True) -> dict[str, Any]:
        """One supervised heartbeat — ensure → tick → optional train → heal."""
        actions: list[dict[str, Any]] = []
        t0 = time.time()

        cont_ensure = self._safe("continuous_ensure", self.continuous_ensure_fn)
        actions.append(cont_ensure)
        evo_ensure = self._safe("evolution_ensure", self.evolution_ensure_fn)
        actions.append(evo_ensure)

        cont_tick = self._safe("continuous_tick", self.continuous_tick_fn)
        actions.append(cont_tick)

        train_info: dict[str, Any] = {"ok": True, "skipped": True, "reason": "not_requested"}
        if train_if_eligible and self.training_eligibility_fn and self.training_start_fn:
            elig = self._safe("training_eligibility", self.training_eligibility_fn)
            actions.append(elig)
            eligible = bool(
                elig.get("eligible")
                or (elig.get("eligibility") or {}).get("eligible")
                or (isinstance(elig.get("result"), dict) and elig["result"].get("eligible"))
            )
            # Nested shapes from tool wrappers
            if not eligible and isinstance(elig, dict):
                for key in ("result", "diag", "status"):
                    nested = elig.get(key)
                    if isinstance(nested, dict) and nested.get("eligible"):
                        eligible = True
                        break
            running = False
            if self.training_status_fn:
                st = self._safe("training_status", self.training_status_fn)
                actions.append(st)
                status = str(st.get("status") or (st.get("job") or {}).get("status") or "").upper()
                running = status in {"RUNNING", "QUEUED", "STARTING", "ACCEPTED"}
            cooldown_ok = (time.time() - self._last_train_ts) >= self._train_cooldown_seconds
            if eligible and not running and cooldown_ok:
                train_info = self._safe("smart_training_start", self.training_start_fn)
                train_info["triggered"] = True
                self._last_train_ts = time.time()
            elif running:
                train_info = {"ok": True, "skipped": True, "reason": "already_running"}
            elif eligible and not cooldown_ok:
                train_info = {"ok": True, "skipped": True, "reason": "train_cooldown"}
            else:
                train_info = {"ok": True, "skipped": True, "reason": "not_eligible", "eligible": False}
            actions.append({**train_info, "_label": "training_decision"})

        if deep:
            actions.append(self._safe("memory_heal", self.memory_heal_fn))
            actions.append(self._safe("heal", self.heal_fn))
            actions.append(self._safe("develop", self.develop_fn))
            actions.append(self._safe("sovereign", self.sovereign_fn))

        cont_st = self._safe("continuous_status", self.continuous_status_fn)
        evo_st = self._safe("evolution_status", self.evolution_status_fn)

        summary = {
            "ok": True,
            "version": self.VERSION,
            "deep": deep,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "continuous_alive": bool(
                (cont_st.get("worker_alive") if cont_st.get("ok") else False)
                or (cont_ensure.get("worker_alive"))
                or cont_ensure.get("ok")
            ),
            "evolution_alive": bool(
                (evo_st.get("alive") if evo_st.get("ok") else False) or evo_ensure.get("ok")
            ),
            "continuous_tick_ok": bool(cont_tick.get("ok")),
            "training": {
                "triggered": bool(train_info.get("triggered")),
                "skipped": train_info.get("skipped"),
                "reason": train_info.get("reason") or train_info.get("status"),
                "actual_training_executed": bool(
                    train_info.get("actual_training_executed")
                    or (train_info.get("cycle") or {}).get("actual_training_executed")
                ),
                "job_id": (train_info.get("job") or {}).get("id") or train_info.get("job_id"),
            },
            "actions_ok": sum(1 for a in actions if a.get("ok")),
            "actions_total": len(actions),
            "weight_promotion": "never_auto",
            "note": (
                "Live monitor keeps learn/train/heal loops alive 24/7. "
                "Weight activation stays owner-gated — never silent."
            ),
        }
        with self._lock:
            self._state["pulses"] += 1
            self._state["last_pulse"] = {"ts": time.time(), "summary": summary}
            self._state["actions"] = [
                {"label": a.get("_label"), "ok": a.get("ok"), "ms": a.get("_ms")}
                for a in actions[-12:]
            ]
            self._state["alive"] = self._alive() or self._state.get("running")
        return summary

    def _loop(self) -> None:
        # Immediate first pulse so 24/7 is visible
        try:
            self.pulse(deep=False, train_if_eligible=True)
        except Exception as exc:
            log.warning("live_monitor first pulse failed: %s", exc)
        deep_every = 8
        n = 0
        while not self._stop.is_set():
            self._stop.wait(self.interval_seconds)
            if self._stop.is_set():
                break
            n += 1
            try:
                self.pulse(deep=(n % deep_every == 0), train_if_eligible=True)
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)[:240]
                log.warning("live_monitor loop error: %s", exc)
            with self._lock:
                self._state["alive"] = self._alive()

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
        st["alive"] = self._alive()
        st["version"] = self.VERSION
        st["interval_seconds"] = self.interval_seconds
        st["weight_promotion"] = "never_auto"
        st["ok"] = True
        # Enrich with live continuous/evolution if available
        if self.continuous_status_fn:
            try:
                cs = self.continuous_status_fn() or {}
                st["continuous"] = {
                    "worker_alive": cs.get("worker_alive"),
                    "real_loop": cs.get("real_loop"),
                    "pending_examples": cs.get("pending_examples"),
                    "service": (cs.get("service") or {}).get("status"),
                }
            except Exception as exc:
                st["continuous"] = {"error": str(exc)[:120]}
        if self.evolution_status_fn:
            try:
                es = self.evolution_status_fn() or {}
                st["evolution"] = {
                    "alive": es.get("alive"),
                    "minute_ticks": es.get("minute_ticks"),
                    "hour_ticks": es.get("hour_ticks"),
                }
            except Exception as exc:
                st["evolution"] = {"error": str(exc)[:120]}
        return st

    def answer_status(self, *, language: str = "ar") -> str:
        """Natural-language status for chat (no JSON fog)."""
        st = self.status()
        en = (language or "").startswith("en")
        cont = st.get("continuous") or {}
        evo = st.get("evolution") or {}
        last = (st.get("last_pulse") or {}).get("summary") or {}
        train = last.get("training") or {}
        alive = bool(st.get("alive"))
        if en:
            parts = [
                f"Live monitor {'RUNNING 24/7' if alive else 'DOWN'} — pulses={st.get('pulses')}.",
                f"Continuous learn worker={'alive' if cont.get('worker_alive') else 'down'} "
                f"(pending={cont.get('pending_examples')}).",
                f"Evolution cadence={'alive' if evo.get('alive') else 'down'} "
                f"(minute_ticks={evo.get('minute_ticks')}).",
            ]
            if train.get("triggered"):
                parts.append("Last pulse started a real LoRA job when eligible.")
            parts.append("Weight promotion stays owner-gated — never silent.")
            return " ".join(parts)
        parts = [
            f"المراقب الحي {'يعمل 24/7' if alive else 'متوقف'} — النبضات={st.get('pulses')}.",
            f"عامل التعلّم المستمر={'حي' if cont.get('worker_alive') else 'متوقف'} "
            f"(معلّق={cont.get('pending_examples')}).",
            f"إيقاع التطوّر={'حي' if evo.get('alive') else 'متوقف'} "
            f"(دقائق={evo.get('minute_ticks')}).",
        ]
        if train.get("triggered"):
            parts.append("آخر نبضة شغّلت LoRA حقيقي عند الأهلية.")
        parts.append("ترقية الأوزان تبقى بموافقة المالك — بلا تفعيل صامت.")
        return " ".join(parts)
