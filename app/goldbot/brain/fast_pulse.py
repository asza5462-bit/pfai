"""Sub-second pulse brain — microstructure / momentum trigger layer."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from goldbot.market.candles import Candle, atr


@dataclass
class FastPulse:
    """Rolling tick memory for fraction-of-a-second decisions."""

    max_ticks: int = 240
    _ticks: deque = field(default_factory=lambda: deque(maxlen=240))

    def push(self, bid: float, ask: float, ts: float | None = None) -> None:
        mid = (bid + ask) / 2.0
        self._ticks.append({"ts": ts or time.time(), "bid": bid, "ask": ask, "mid": mid})

    @property
    def age_ms(self) -> float:
        if not self._ticks:
            return 1e9
        return (time.time() - self._ticks[-1]["ts"]) * 1000.0

    def analyze(self, candles: list[Candle] | None = None) -> dict:
        now = time.time()
        if len(self._ticks) < 3:
            return {
                "bias": "neutral",
                "score": 0.0,
                "velocity": 0.0,
                "accel": 0.0,
                "spread": 0.0,
                "ticks": len(self._ticks),
                "fresh_ms": self.age_ms,
                "trigger": False,
            }

        recent = [t for t in self._ticks if now - t["ts"] <= 8.0]
        if len(recent) < 3:
            recent = list(self._ticks)[-8:]

        mids = [t["mid"] for t in recent]
        spreads = [t["ask"] - t["bid"] for t in recent]
        dt = max(1e-3, recent[-1]["ts"] - recent[0]["ts"])
        velocity = (mids[-1] - mids[0]) / dt  # price units per second
        # short vs shorter window acceleration
        mid_n = len(mids)
        half = max(2, mid_n // 2)
        v1 = (mids[half] - mids[0]) / max(1e-3, recent[half]["ts"] - recent[0]["ts"])
        v2 = (mids[-1] - mids[half]) / max(1e-3, recent[-1]["ts"] - recent[half]["ts"])
        accel = v2 - v1

        a = atr(candles, 14) if candles and len(candles) >= 20 else max(0.5, abs(mids[-1]) * 0.0004)
        # normalize velocity to ATR fraction per second
        norm_v = velocity / max(a, 1e-6)
        score = max(-1.0, min(1.0, norm_v * 12.0 + accel / max(a, 1e-6) * 4.0))

        bias = "buy" if score >= 0.18 else "sell" if score <= -0.18 else "neutral"
        # trigger = decisive short-window impulse
        trigger = abs(score) >= 0.28 and abs(mids[-1] - mids[0]) >= a * 0.05

        # candle micro confirm: last bar pressure
        pressure = 0.0
        if candles:
            c = candles[-1]
            pressure = (c.close - c.open) / max(c.range, 1e-9)
            if bias == "buy" and pressure < -0.55:
                score *= 0.7
            if bias == "sell" and pressure > 0.55:
                score *= 0.7

        return {
            "bias": bias,
            "score": round(score, 4),
            "velocity": round(velocity, 5),
            "accel": round(accel, 5),
            "spread": round(sum(spreads) / len(spreads), 4),
            "ticks": len(self._ticks),
            "window_ticks": len(recent),
            "fresh_ms": round(self.age_ms, 1),
            "trigger": bool(trigger),
            "pressure": round(pressure, 3),
            "atr": round(a, 3),
        }

    def confirms(self, action: str, pulse: dict | None = None) -> bool:
        p = pulse or self.analyze()
        if action == "flat":
            return False
        if p["bias"] == action and (p["trigger"] or abs(p["score"]) >= 0.22):
            return True
        # soft confirm: same side mild score
        if action == "buy" and p["score"] >= 0.12:
            return True
        if action == "sell" and p["score"] <= -0.12:
            return True
        return False


fast_pulse = FastPulse()
