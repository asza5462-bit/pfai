"""Quantum-inspired ultra-fast core — classical, measured, never fake.

Honesty contract:
- This is NOT a quantum computer and does not claim qubits / entanglement hardware.
- "Superposition" here = evaluate multiple hypotheses in parallel (ThreadPool).
- "Collapse" = pick the highest-scoring measured hypothesis.
- Hot-path timings use time.perf_counter_ns() and are reported honestly (μs / ns).
- Full LLM / network calls remain outside the μs budget — never invented as μs.

Goals satisfied in software reality:
- Extreme local speed for routing, IoT understanding, status collapse
- Parallel multi-hypothesis reasoning
- Feeds continuous evolution without weight auto-promotion
"""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


def quantum_core_enabled() -> bool:
    v = os.environ.get("PFAI_QUANTUM_CORE", "").strip().lower()
    if v in {"0", "false", "off", "no"}:
        return False
    if v in {"1", "true", "on", "yes"}:
        return True
    return True  # default on — classical ultra-fast path


@dataclass
class Hypothesis:
    name: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    elapsed_ns: int = 0


class QuantumInspiredCore:
    """Ultra-fast parallel hypothesis engine with honest timing."""

    VERSION = "8.8.0"

    def __init__(
        self,
        *,
        iot_fn: Optional[Callable[[str], dict]] = None,
        continuous_status_fn: Optional[Callable[[], dict]] = None,
        evolve_status_fn: Optional[Callable[[], dict]] = None,
        max_workers: int = 4,
    ) -> None:
        self.iot_fn = iot_fn
        self.continuous_status_fn = continuous_status_fn
        self.evolve_status_fn = evolve_status_fn
        self.max_workers = max(2, min(8, int(max_workers)))
        self._lock = threading.RLock()
        self._pulses = 0
        self._best_ns = 10**15
        self._last: dict[str, Any] = {}

    # -- timing helpers -------------------------------------------------
    @staticmethod
    def _ns() -> int:
        return time.perf_counter_ns()

    @staticmethod
    def _fmt(ns: int) -> dict[str, Any]:
        us = ns / 1000.0
        ms = ns / 1_000_000.0
        return {
            "elapsed_ns": int(ns),
            "elapsed_us": round(us, 3),
            "elapsed_ms": round(ms, 3),
            "target_band": (
                "sub_microsecond" if ns < 1000
                else "microsecond" if ns < 1000_000
                else "millisecond" if ns < 50_000_000
                else "network_or_heavy"
            ),
        }

    # -- hypothesis generators (local, no network) ----------------------
    def _hyp_speed_route(self, message: str) -> Hypothesis:
        t0 = self._ns()
        text = (message or "").lower()
        route = "status"
        if re.search(r"iot|أشياء|اشياء|mqtt|sensor|جهاز|حساس|zigbee|matter", text, re.I):
            route = "iot"
        elif re.search(r"تطور|evolve|دقيقة|ساعة|يوم|continuous|تدريب", text, re.I):
            route = "evolve"
        elif re.search(r"كم[يّ]|quantum|سرعة|فائق|micro", text, re.I):
            route = "quantum_pulse"
        score = 0.82 if route != "status" else 0.55
        return Hypothesis(
            "speed_route",
            score,
            {"route": route, "local_only": True},
            self._ns() - t0,
        )

    def _hyp_iot(self, message: str) -> Hypothesis:
        t0 = self._ns()
        if not self.iot_fn:
            return Hypothesis("iot", 0.0, {"available": False}, self._ns() - t0)
        try:
            out = self.iot_fn(message) or {}
        except Exception as exc:
            return Hypothesis("iot", 0.0, {"error": str(exc)[:160]}, self._ns() - t0)
        conf = float(out.get("confidence") or 0.0)
        return Hypothesis("iot", min(1.0, 0.35 + conf), out, self._ns() - t0)

    def _hyp_continuity(self, message: str) -> Hypothesis:
        t0 = self._ns()
        st: dict[str, Any] = {}
        if self.continuous_status_fn:
            try:
                st = self.continuous_status_fn() or {}
            except Exception as exc:
                st = {"error": str(exc)[:120]}
        worker = bool(st.get("worker_alive") or (st.get("real_loop")))
        smart = (st.get("smart") or {}) if isinstance(st.get("smart"), dict) else {}
        score = 0.7 if worker else 0.3
        if smart.get("enabled"):
            score += 0.15
        return Hypothesis(
            "continuity",
            min(1.0, score),
            {
                "worker_alive": worker,
                "pending": st.get("pending_examples"),
                "focus": (smart.get("last_prep") or {}).get("focus_tracks"),
                "auto_promote": False,
            },
            self._ns() - t0,
        )

    def _hyp_evolve(self, message: str) -> Hypothesis:
        t0 = self._ns()
        st: dict[str, Any] = {}
        if self.evolve_status_fn:
            try:
                st = self.evolve_status_fn() or {}
            except Exception as exc:
                st = {"error": str(exc)[:120]}
        alive = bool(st.get("alive") or st.get("running"))
        score = 0.75 if alive else 0.4
        return Hypothesis(
            "evolve_cadence",
            score,
            {
                "alive": alive,
                "minute_ticks": st.get("minute_ticks"),
                "hour_ticks": st.get("hour_ticks"),
                "day_ticks": st.get("day_ticks"),
                "last_minute": st.get("last_minute"),
            },
            self._ns() - t0,
        )

    # -- collapse -------------------------------------------------------
    def pulse(self, message: str = "", *, include_iot: bool = True) -> dict[str, Any]:
        """Parallel hypothesis pulse — local only, measured ns/μs."""
        if not quantum_core_enabled():
            return {
                "ok": False,
                "enabled": False,
                "quantum_hardware": False,
                "note": "PFAI_QUANTUM_CORE disabled",
            }
        wall0 = self._ns()
        msg = message or ""

        jobs: list[tuple[str, Callable[[], Hypothesis]]] = [
            ("speed_route", lambda: self._hyp_speed_route(msg)),
            ("continuity", lambda: self._hyp_continuity(msg)),
            ("evolve_cadence", lambda: self._hyp_evolve(msg)),
        ]
        if include_iot:
            jobs.append(("iot", lambda: self._hyp_iot(msg)))

        hyps: list[Hypothesis] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool:
            futs = {pool.submit(fn): name for name, fn in jobs}
            for fut in as_completed(futs):
                try:
                    hyps.append(fut.result())
                except Exception as exc:
                    hyps.append(Hypothesis(futs[fut], 0.0, {"error": str(exc)[:120]}, 0))

        # Collapse: highest score; prefer iot when scores close and message is iot-ish
        hyps.sort(key=lambda h: h.score, reverse=True)
        winner = hyps[0] if hyps else Hypothesis("none", 0.0, {})
        if msg and re.search(r"iot|أشياء|اشياء|mqtt|sensor|جهاز", msg, re.I):
            for h in hyps:
                if h.name == "iot" and h.score >= winner.score - 0.05:
                    winner = h
                    break

        wall_ns = self._ns() - wall0
        with self._lock:
            self._pulses += 1
            if wall_ns < self._best_ns:
                self._best_ns = wall_ns
            timing = self._fmt(wall_ns)
            out = {
                "ok": True,
                "quantum_inspired": True,
                "quantum_hardware": False,  # never claim fake qubits
                "engine": "classical_parallel_superposition",
                "version": self.VERSION,
                "collapsed": {
                    "hypothesis": winner.name,
                    "score": round(winner.score, 4),
                    "payload": winner.payload,
                    "hypothesis_ns": winner.elapsed_ns,
                },
                "superposition": [
                    {
                        "name": h.name,
                        "score": round(h.score, 4),
                        "elapsed_ns": h.elapsed_ns,
                        "keys": list((h.payload or {}).keys())[:8],
                    }
                    for h in hyps
                ],
                "timing": timing,
                "best_pulse_ns": self._best_ns if self._best_ns < 10**15 else wall_ns,
                "pulses": self._pulses,
                "weight_promotion": "never_auto",
                "honesty": (
                    "Classical parallel hypotheses with measured timing. "
                    "Not quantum hardware. Network/LLM paths are separate and slower."
                ),
                "speed_note": (
                    "Local collapse targets microsecond–millisecond bands. "
                    "Full chat with tools/LLM is outside this hot path."
                ),
            }
            self._last = out
            return out

    def hot_route(self, message: str) -> dict[str, Any]:
        """Minimal μs-oriented router — no thread pool overhead when possible."""
        t0 = self._ns()
        h = self._hyp_speed_route(message)
        timing = self._fmt(self._ns() - t0)
        return {
            "ok": True,
            "route": (h.payload or {}).get("route"),
            "score": h.score,
            "timing": timing,
            "quantum_hardware": False,
            "weight_promotion": "never_auto",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "enabled": quantum_core_enabled(),
                "quantum_inspired": True,
                "quantum_hardware": False,
                "version": self.VERSION,
                "pulses": self._pulses,
                "best_pulse_ns": self._best_ns if self._best_ns < 10**15 else None,
                "best_pulse_us": (
                    round(self._best_ns / 1000.0, 3) if self._best_ns < 10**15 else None
                ),
                "last_collapsed": (self._last.get("collapsed") or {}).get("hypothesis"),
                "last_timing": self._last.get("timing"),
                "weight_promotion": "never_auto",
                "note": "Honest classical ultra-fast core; no fake quantum claims.",
            }
