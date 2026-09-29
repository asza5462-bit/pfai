"""Unified Train+Learn loop — one 24/7 mind for continuous learning + real LoRA.

Pipeline (never hangs the HTTP thread):
  1) ensure continuous worker alive
  2) tick continuous curation (real learn cycle) — debounced
  3) push curated rows → experience / dataset growth
  4) if eligible and not already training → start REAL LoRA async
  5) report honest status (executed only when trainer finished)

Hard bounds:
- never silent weight promotion
- overlapping cycles return last snapshot (no pile-up / hang)
- each step has a hard timeout
- optional self-heartbeat so the loop stays alive even if evolution pauses
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.unified_train_learn")


class UnifiedTrainLearnLoop:
    VERSION = "8.15.0"

    def __init__(
        self,
        *,
        continuous_ensure_fn: Optional[Callable[[], dict]] = None,
        continuous_tick_fn: Optional[Callable[[], dict]] = None,
        continuous_status_fn: Optional[Callable[[], dict]] = None,
        experience_push_fn: Optional[Callable[[], dict]] = None,
        training_diagnose_fn: Optional[Callable[[], dict]] = None,
        training_start_fn: Optional[Callable[[], dict]] = None,
        training_status_fn: Optional[Callable[[], dict]] = None,
        train_cooldown_seconds: int = 900,
        tick_timeout_seconds: float = 30.0,
        min_tick_interval_seconds: float = 40.0,
        heartbeat_seconds: float = 90.0,
        heartbeat_train_every: int = 8,
    ) -> None:
        self.continuous_ensure_fn = continuous_ensure_fn
        self.continuous_tick_fn = continuous_tick_fn
        self.continuous_status_fn = continuous_status_fn
        self.experience_push_fn = experience_push_fn
        self.training_diagnose_fn = training_diagnose_fn
        self.training_start_fn = training_start_fn
        self.training_status_fn = training_status_fn
        self.train_cooldown_seconds = max(120, int(train_cooldown_seconds))
        self.tick_timeout_seconds = max(10.0, float(tick_timeout_seconds))
        self.min_tick_interval_seconds = max(5.0, float(min_tick_interval_seconds))
        self.heartbeat_seconds = max(20.0, float(heartbeat_seconds))
        self.heartbeat_train_every = max(0, int(heartbeat_train_every))
        self._lock = threading.RLock()
        self._cycle_lock = threading.Lock()
        self._last_train_ts = 0.0
        self._last_tick_ts = 0.0
        self._cycles = 0
        self._hb_beats = 0
        self._last: dict[str, Any] = {}
        self._errors: list[str] = []
        self._hb_thread: threading.Thread | None = None
        self._hb_stop = threading.Event()
        self._hb_alive = False

    def _safe(self, label: str, fn: Optional[Callable[[], dict]], *, timeout: float | None = None) -> dict[str, Any]:
        if not fn:
            return {"ok": False, "skipped": True, "reason": "no_fn", "label": label}
        box: dict[str, Any] = {}

        def _run() -> None:
            t0 = time.time()
            try:
                out = fn() or {}
                if not isinstance(out, dict):
                    out = {"ok": True, "value": out}
                out.setdefault("ok", True)
                out["_label"] = label
                out["_ms"] = int((time.time() - t0) * 1000)
                box["out"] = out
            except Exception as exc:
                box["out"] = {"ok": False, "error": str(exc)[:240], "_label": label}

        if timeout and timeout > 0:
            th = threading.Thread(target=_run, name=f"utl-{label}", daemon=True)
            th.start()
            th.join(timeout=timeout)
            if th.is_alive():
                log.warning("unified_train_learn %s timed out after %ss", label, timeout)
                return {
                    "ok": False,
                    "error": f"timeout_{timeout}s",
                    "_label": label,
                    "timed_out": True,
                }
            return box.get("out") or {"ok": False, "error": "no_result", "_label": label}
        _run()
        return box.get("out") or {"ok": False, "error": "no_result", "_label": label}

    def _training_busy(self) -> bool:
        if not self.training_status_fn:
            return False
        st = self._safe("training_status", self.training_status_fn, timeout=4)
        # Trust live async flag only — never treat stale last.status=STARTED_ASYNC as busy
        if st.get("async_running"):
            return True
        status = str(st.get("status") or "").upper()
        return status in {"RUNNING", "QUEUED", "STARTING"}

    def cycle(
        self,
        *,
        force_train: bool = False,
        train_if_eligible: bool = True,
        skip_tick: bool = False,
    ) -> dict[str, Any]:
        """One smooth unified learn→train heartbeat. Never blocks forever."""
        # Overlap guard: never pile cycles (chat + minute + hour)
        if not self._cycle_lock.acquire(blocking=False):
            with self._lock:
                last = dict(self._last or {})
            return {
                "ok": True,
                "skipped": True,
                "reason": "cycle_in_progress",
                "version": self.VERSION,
                "unified": True,
                "weight_promotion": "never_auto",
                "learn": (last.get("learn") or {}),
                "train": {**(last.get("train") or {}), "skipped": True, "reason": "cycle_in_progress"},
                "experience": (last.get("experience") or {}),
                "elapsed_ms": 0,
                "note": "Previous unified cycle still running — returned last snapshot.",
            }
        try:
            return self._cycle_body(
                force_train=force_train,
                train_if_eligible=train_if_eligible,
                skip_tick=skip_tick,
            )
        finally:
            try:
                self._cycle_lock.release()
            except RuntimeError:
                pass

    def _cycle_body(self, *, force_train: bool, train_if_eligible: bool, skip_tick: bool = False) -> dict[str, Any]:
        t0 = time.time()
        steps: list[dict[str, Any]] = []

        # If LoRA already holds the CPU, return a light snapshot (keeps chat snappy)
        busy_early = self._training_busy()
        if busy_early and not force_train:
            ensure = self._safe("continuous_ensure", self.continuous_ensure_fn, timeout=8)
            cont_st = self._safe("continuous_status", self.continuous_status_fn, timeout=4)
            train_st = self._safe("training_status", self.training_status_fn, timeout=4)
            summary = {
                "ok": True,
                "version": self.VERSION,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "learn": {
                    "worker_alive": bool(cont_st.get("worker_alive") or ensure.get("worker_alive")),
                    "tick_ok": True,
                    "tick_debounced": True,
                    "pending_examples": cont_st.get("pending_examples"),
                    "real_loop": cont_st.get("real_loop"),
                },
                "experience": {"pushed": 0, "accepted": 0, "skipped": True},
                "train": {
                    "eligible": True,
                    "triggered": False,
                    "skipped": True,
                    "reason": "already_running",
                    "async_accepted": False,
                    "async_running": True,
                    "actual_training_executed": bool(
                        ((train_st.get("last") or {}).get("cycle") or {}).get("actual_training_executed")
                    ),
                    "status": train_st.get("status") or "RUNNING",
                },
                "steps_ok": 1,
                "steps_total": 1,
                "heartbeat_alive": self._hb_alive,
                "weight_promotion": "never_auto",
                "unified": True,
                "light": True,
                "note": "LoRA already running — light status only (no pile-up).",
            }
            with self._lock:
                self._cycles += 1
                self._last = summary
            return summary

        ensure = self._safe("continuous_ensure", self.continuous_ensure_fn, timeout=12)
        steps.append(ensure)

        # Debounce / skip continuous tick — worker already loops; avoid boot hangs
        now = time.time()
        tick_due = (
            not skip_tick
            and (force_train or (now - self._last_tick_ts) >= self.min_tick_interval_seconds)
        )
        if tick_due:
            tick = self._safe(
                "continuous_tick",
                self.continuous_tick_fn,
                timeout=self.tick_timeout_seconds,
            )
            if tick.get("ok") and not tick.get("timed_out"):
                self._last_tick_ts = time.time()
        else:
            tick = {
                "ok": True,
                "skipped": True,
                "reason": "tick_skipped" if skip_tick else "tick_debounce",
                "_label": "continuous_tick",
                "debounced": not skip_tick,
            }
        steps.append(tick)

        if skip_tick:
            push = {"ok": True, "pushed": 0, "accepted": 0, "skipped": True, "_label": "experience_push"}
        else:
            push = self._safe("experience_push", self.experience_push_fn, timeout=12)
        steps.append(push)

        diag = self._safe("training_diagnose", self.training_diagnose_fn, timeout=10)
        steps.append(diag)
        eligible = bool(diag.get("eligible"))

        train_out: dict[str, Any] = {"ok": True, "skipped": True, "reason": "not_requested"}
        busy = busy_early or self._training_busy()
        cooldown_ok = (time.time() - self._last_train_ts) >= self.train_cooldown_seconds

        if train_if_eligible or force_train:
            if busy:
                train_out = {"ok": True, "skipped": True, "reason": "already_running", "busy": True}
            elif (eligible or force_train) and (cooldown_ok or force_train):
                train_out = self._safe("training_start", self.training_start_fn, timeout=20)
                status = str(train_out.get("status") or "").upper()
                accepted = bool(
                    train_out.get("ok")
                    or train_out.get("async_accepted")
                    or status in {"STARTED_ASYNC", "ALREADY_RUNNING", "RUNNING"}
                )
                if accepted:
                    self._last_train_ts = time.time()
                    train_out["triggered"] = status != "ALREADY_RUNNING"
                    train_out["ok"] = True
                    if status == "ALREADY_RUNNING":
                        train_out["skipped"] = True
                        train_out["reason"] = "already_running"
                train_out.setdefault("triggered", False)
            elif eligible and not cooldown_ok:
                train_out = {"ok": True, "skipped": True, "reason": "train_cooldown", "eligible": True}
            else:
                train_out = {
                    "ok": True,
                    "skipped": True,
                    "reason": diag.get("reason") or "not_eligible",
                    "eligible": False,
                    "blockers": diag.get("blockers") or [],
                }
        steps.append({**train_out, "_label": "training_decision"})

        cont_st = self._safe("continuous_status", self.continuous_status_fn, timeout=6)
        train_st = self._safe("training_status", self.training_status_fn, timeout=6)

        summary = {
            "ok": True,
            "version": self.VERSION,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "learn": {
                "worker_alive": bool(cont_st.get("worker_alive") or ensure.get("worker_alive")),
                "tick_ok": bool(tick.get("ok")) and not tick.get("timed_out"),
                "tick_debounced": bool(tick.get("debounced")),
                "pending_examples": cont_st.get("pending_examples"),
                "real_loop": cont_st.get("real_loop"),
            },
            "experience": {
                "pushed": push.get("pushed"),
                "accepted": push.get("accepted"),
            },
            "train": {
                "eligible": eligible,
                "triggered": bool(train_out.get("triggered")),
                "skipped": train_out.get("skipped"),
                "reason": train_out.get("reason") or (train_out.get("cycle") or {}).get("reason"),
                "async_accepted": bool(train_out.get("async_accepted")),
                "async_running": bool(train_st.get("async_running") or busy),
                "actual_training_executed": bool(
                    train_out.get("actual_training_executed")
                    or (train_out.get("cycle") or {}).get("actual_training_executed")
                    or ((train_st.get("last") or {}).get("cycle") or {}).get("actual_training_executed")
                ),
                "status": (train_out.get("cycle") or {}).get("status") or train_out.get("status") or train_st.get("status"),
            },
            "steps_ok": sum(1 for s in steps if s.get("ok") or s.get("skipped")),
            "steps_total": len(steps),
            "heartbeat_alive": self._hb_alive,
            "weight_promotion": "never_auto",
            "unified": True,
            "note": (
                "Unified 24/7 learn→grow→train. LoRA starts async when eligible. "
                "Weight activation stays owner-gated."
            ),
        }
        with self._lock:
            self._cycles += 1
            self._last = summary
            if any(s.get("timed_out") or (not s.get("ok") and not s.get("skipped")) for s in steps):
                err = next(
                    (s.get("error") for s in steps if s.get("error")),
                    None,
                )
                if err:
                    self._errors = (self._errors + [str(err)[:160]])[-8:]
        return summary

    def start(self) -> dict[str, Any]:
        """Start dedicated 24/7 heartbeat (daemon). Idempotent."""
        with self._lock:
            if self._hb_thread and self._hb_thread.is_alive():
                self._hb_alive = True
                return {"ok": True, "alive": True, "already": True, "version": self.VERSION}
            self._hb_stop.clear()

            def _loop() -> None:
                self._hb_alive = True
                log.info(
                    "unified_train_learn heartbeat started every %ss train_every=%s",
                    self.heartbeat_seconds,
                    self.heartbeat_train_every,
                )
                # Let boot settle; first pulse is light (no tick — avoids free-tier hang)
                if self._hb_stop.wait(12.0):
                    self._hb_alive = False
                    return
                try:
                    self.cycle(force_train=False, train_if_eligible=False, skip_tick=True)
                except Exception as exc:
                    log.warning("unified first soft cycle failed: %s", exc)
                while not self._hb_stop.wait(self.heartbeat_seconds):
                    try:
                        self._hb_beats += 1
                        # Learn every beat; LoRA only every N beats (0 = never from heartbeat)
                        train_now = (
                            self.heartbeat_train_every > 0
                            and (self._hb_beats % self.heartbeat_train_every) == 0
                        )
                        self.cycle(force_train=False, train_if_eligible=train_now)
                    except Exception as exc:
                        log.warning("unified heartbeat cycle failed: %s", exc)
                        with self._lock:
                            self._errors = (self._errors + [str(exc)[:160]])[-8:]
                self._hb_alive = False

            t = threading.Thread(target=_loop, name="pfai-unified-train-learn", daemon=True)
            self._hb_thread = t
            t.start()
            return {
                "ok": True,
                "alive": True,
                "heartbeat_seconds": self.heartbeat_seconds,
                "heartbeat_train_every": self.heartbeat_train_every,
                "version": self.VERSION,
                "weight_promotion": "never_auto",
            }

    def stop(self, reason: str = "") -> dict[str, Any]:
        self._hb_stop.set()
        th = self._hb_thread
        if th and th.is_alive():
            th.join(timeout=3.0)
        self._hb_alive = False
        return {"ok": True, "alive": False, "reason": reason or "stopped", "version": self.VERSION}

    def status(self) -> dict[str, Any]:
        with self._lock:
            last = dict(self._last or {})
            cycles = self._cycles
            errors = list(self._errors)
            hb = self._hb_alive and bool(self._hb_thread and self._hb_thread.is_alive())
        # Short timeouts — never stall chat while LoRA holds the CPU
        cont = self._safe("continuous_status", self.continuous_status_fn, timeout=4)
        train = self._safe("training_status", self.training_status_fn, timeout=4)
        # Skip heavy diagnose while async LoRA is running (use last snapshot)
        if train.get("async_running"):
            diag = {
                "eligible": ((last.get("train") or {}).get("eligible")),
                "reason": "async_training_running",
                "skipped": True,
            }
        else:
            diag = self._safe("training_diagnose", self.training_diagnose_fn, timeout=6)
        return {
            "ok": True,
            "version": self.VERSION,
            "cycles": cycles,
            "last": last,
            "recent_errors": errors,
            "heartbeat_alive": hb,
            "heartbeat_seconds": self.heartbeat_seconds,
            "heartbeat_train_every": self.heartbeat_train_every,
            "heartbeat_beats": self._hb_beats,
            "continuous": {
                "worker_alive": cont.get("worker_alive"),
                "real_loop": cont.get("real_loop"),
                "pending_examples": cont.get("pending_examples"),
            },
            "training": {
                "eligible": diag.get("eligible"),
                "reason": diag.get("reason"),
                "async_running": train.get("async_running"),
                "runs": train.get("runs"),
                "last_cycle": (train.get("last") or {}).get("cycle"),
            },
            "train_cooldown_seconds": self.train_cooldown_seconds,
            "weight_promotion": "never_auto",
            "unified": True,
        }

    def answer(self, *, language: str = "ar") -> str:
        st = self.status()
        en = (language or "").startswith("en")
        cont = st.get("continuous") or {}
        tr = st.get("training") or {}
        last = st.get("last") or {}
        last_train = (last.get("train") or {}) if last else {}
        hb = "ON" if st.get("heartbeat_alive") else "off"
        if en:
            parts = [
                f"Unified learn+train loop v{self.VERSION} — cycles={st.get('cycles')} · heartbeat={hb}.",
                f"Continuous learn={'ALIVE 24/7' if cont.get('worker_alive') else 'DOWN'} "
                f"(pending={cont.get('pending_examples')}).",
                f"Training eligible={'YES' if tr.get('eligible') else 'NO'}"
                + (f" · {tr.get('reason')}" if tr.get("reason") and not tr.get("eligible") else "")
                + ".",
            ]
            if last_train.get("triggered") or tr.get("async_running"):
                parts.append(
                    f"LoRA status={last_train.get('status') or 'RUNNING'} "
                    f"(executed={last_train.get('actual_training_executed')})."
                )
            parts.append("Weight promotion stays owner-gated — never silent.")
            return " ".join(parts)
        parts = [
            f"حلقة التعلّم+التدريب الموحّدة v{self.VERSION} — دورات={st.get('cycles')} · نبض={'يعمل' if st.get('heartbeat_alive') else 'متوقف'}.",
            f"التعلّم المستمر={'يعمل 24/7' if cont.get('worker_alive') else 'متوقف'} "
            f"(معلّق={cont.get('pending_examples')}).",
            f"أهلية التدريب={'نعم' if tr.get('eligible') else 'لا'}"
            + (f" · {tr.get('reason')}" if tr.get("reason") and not tr.get("eligible") else "")
            + ".",
        ]
        if last_train.get("triggered") or tr.get("async_running"):
            parts.append(
                f"حالة LoRA={last_train.get('status') or 'RUNNING'} "
                f"(نُفّذ={last_train.get('actual_training_executed')})."
            )
        parts.append("ترقية الأوزان تبقى بموافقة المالك — بلا تفعيل صامت.")
        return " ".join(parts)
