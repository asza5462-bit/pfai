"""Evolution cadence — hard work every minute / hour / day.

Runs real bounded ticks:
- minute: quantum hot pulse + continuous soft tick (curation)
- hour: autonomy self-improve (safe heal + learn)
- day: advanced self-develop cycle

Never auto-promotes model weights. Soft-fails lanes; keeps worker alive.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.evolve")


def evolution_enabled() -> bool:
    v = os.environ.get("PFAI_EVOLUTION_CADENCE", "").strip().lower()
    if v in {"0", "false", "off", "no"}:
        return False
    if v in {"1", "true", "on", "yes"}:
        return True
    return True


class EvolutionCadence:
    """Background minute/hour/day evolution scheduler."""

    VERSION = "8.8.0"

    def __init__(
        self,
        *,
        minute_fn: Optional[Callable[[], dict]] = None,
        hour_fn: Optional[Callable[[], dict]] = None,
        day_fn: Optional[Callable[[], dict]] = None,
        minute_seconds: int = 60,
        hour_seconds: int = 3600,
        day_seconds: int = 86400,
    ) -> None:
        self.minute_fn = minute_fn
        self.hour_fn = hour_fn
        self.day_fn = day_fn
        self.minute_seconds = max(15, int(minute_seconds))
        self.hour_seconds = max(120, int(hour_seconds))
        self.day_seconds = max(600, int(day_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "running": False,
            "alive": False,
            "minute_ticks": 0,
            "hour_ticks": 0,
            "day_ticks": 0,
            "last_minute": None,
            "last_hour": None,
            "last_day": None,
            "last_error": None,
            "started_at": None,
        }

    def _alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> dict[str, Any]:
        if not evolution_enabled():
            return {"ok": False, "enabled": False, "running": False}
        with self._lock:
            if self._alive():
                return {**self.status(), "ok": True, "already": True}
            self._stop.clear()
            self._state["running"] = True
            self._state["started_at"] = time.time()
            self._state["last_error"] = None
            t = threading.Thread(target=self._loop, name="pfai-evolution-cadence", daemon=True)
            self._thread = t
            t.start()
            self._state["alive"] = True
            log.info(
                "evolution cadence started minute=%ss hour=%ss day=%ss",
                self.minute_seconds,
                self.hour_seconds,
                self.day_seconds,
            )
            return {**self.status(), "ok": True}

    def stop(self, reason: str = "operator") -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            self._state["running"] = False
            self._state["alive"] = False
            self._state["last_error"] = reason
        return {**self.status(), "ok": True, "stopped": True}

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
            log.warning("evolution %s failed: %s", label, exc)
            return {"ok": False, "error": str(exc)[:240], "_label": label}

    def tick_minute(self) -> dict[str, Any]:
        out = self._safe("minute", self.minute_fn)
        with self._lock:
            self._state["minute_ticks"] += 1
            self._state["last_minute"] = {"ts": time.time(), "result": {
                "ok": out.get("ok"),
                "ms": out.get("_ms"),
                "keys": list(out.keys())[:12],
            }}
        return out

    def tick_hour(self) -> dict[str, Any]:
        out = self._safe("hour", self.hour_fn)
        with self._lock:
            self._state["hour_ticks"] += 1
            self._state["last_hour"] = {"ts": time.time(), "ok": out.get("ok"), "ms": out.get("_ms")}
        return out

    def tick_day(self) -> dict[str, Any]:
        out = self._safe("day", self.day_fn)
        with self._lock:
            self._state["day_ticks"] += 1
            self._state["last_day"] = {"ts": time.time(), "ok": out.get("ok"), "ms": out.get("_ms")}
        return out

    def _loop(self) -> None:
        next_minute = time.time()
        next_hour = time.time() + self.hour_seconds
        next_day = time.time() + self.day_seconds
        # Immediate first minute tick so evolution is visible
        try:
            self.tick_minute()
        except Exception as exc:
            log.warning("evolution first minute failed: %s", exc)
        next_minute = time.time() + self.minute_seconds
        while not self._stop.is_set():
            now = time.time()
            try:
                if now >= next_minute:
                    self.tick_minute()
                    next_minute = now + self.minute_seconds
                if now >= next_hour:
                    self.tick_hour()
                    next_hour = now + self.hour_seconds
                if now >= next_day:
                    self.tick_day()
                    next_day = now + self.day_seconds
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)[:240]
                log.warning("evolution loop error: %s", exc)
            with self._lock:
                self._state["alive"] = self._alive()
            # Sleep short slices for responsive stop
            self._stop.wait(2.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
        st["alive"] = self._alive()
        st["enabled"] = evolution_enabled()
        st["version"] = self.VERSION
        st["intervals"] = {
            "minute_seconds": self.minute_seconds,
            "hour_seconds": self.hour_seconds,
            "day_seconds": self.day_seconds,
        }
        st["weight_promotion"] = "never_auto"
        st["ok"] = True
        return st
