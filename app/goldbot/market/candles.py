"""Candle engine — multi-timeframe OHLC + classic patterns."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return max(1e-9, self.high - self.low)

    @property
    def bullish(self) -> bool:
        return self.close >= self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    def to_dict(self) -> dict:
        return asdict(self)


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return candles[-1].range if candles else 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    window = trs[-period:]
    return sum(window) / len(window)


def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def detect_patterns(candles: list[Candle]) -> list[dict]:
    """Recognize high-value candlestick patterns on the last bar."""
    if len(candles) < 3:
        return []
    a, b, c = candles[-3], candles[-2], candles[-1]
    found: list[dict] = []

    # Pin bar / hammer / shooting star
    if c.lower_wick >= c.body * 2 and c.upper_wick <= c.body * 0.5:
        found.append({"name": "hammer_pin", "bias": "buy", "strength": min(1.0, c.lower_wick / c.range)})
    if c.upper_wick >= c.body * 2 and c.lower_wick <= c.body * 0.5:
        found.append({"name": "shooting_star", "bias": "sell", "strength": min(1.0, c.upper_wick / c.range)})

    # Engulfing
    if (not b.bullish) and c.bullish and c.open <= b.close and c.close >= b.open and c.body > b.body:
        found.append({"name": "bullish_engulfing", "bias": "buy", "strength": 0.85})
    if b.bullish and (not c.bullish) and c.open >= b.close and c.close <= b.open and c.body > b.body:
        found.append({"name": "bearish_engulfing", "bias": "sell", "strength": 0.85})

    # Inside bar break context
    if c.high < b.high and c.low > b.low:
        found.append({"name": "inside_bar", "bias": "neutral", "strength": 0.45})

    # Morning / evening star proxy
    if (not a.bullish) and b.body < a.body * 0.45 and c.bullish and c.close > (a.open + a.close) / 2:
        found.append({"name": "morning_star", "bias": "buy", "strength": 0.8})
    if a.bullish and b.body < a.body * 0.45 and (not c.bullish) and c.close < (a.open + a.close) / 2:
        found.append({"name": "evening_star", "bias": "sell", "strength": 0.8})

    return found


def swing_points(candles: list[Candle], left: int = 2, right: int = 2) -> dict:
    highs: list[dict] = []
    lows: list[dict] = []
    for i in range(left, len(candles) - right):
        window = candles[i - left : i + right + 1]
        hi = candles[i].high
        lo = candles[i].low
        if hi == max(x.high for x in window):
            highs.append({"index": i, "price": hi, "time": candles[i].time})
        if lo == min(x.low for x in window):
            lows.append({"index": i, "price": lo, "time": candles[i].time})
    return {"swing_highs": highs[-8:], "swing_lows": lows[-8:]}


def summarize_structure(candles: list[Candle]) -> dict:
    if len(candles) < 30:
        return {"trend": "flat", "bos": None, "choch": None}
    closes = [c.close for c in candles]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    trend = "bull" if e20[-1] > e50[-1] and closes[-1] > e20[-1] else "bear" if e20[-1] < e50[-1] and closes[-1] < e20[-1] else "flat"
    swings = swing_points(candles)
    bos = None
    if swings["swing_highs"] and trend == "bull" and closes[-1] > swings["swing_highs"][-1]["price"]:
        bos = {"type": "bullish_bos", "level": swings["swing_highs"][-1]["price"]}
    if swings["swing_lows"] and trend == "bear" and closes[-1] < swings["swing_lows"][-1]["price"]:
        bos = {"type": "bearish_bos", "level": swings["swing_lows"][-1]["price"]}
    return {
        "trend": trend,
        "ema20": round(e20[-1], 3),
        "ema50": round(e50[-1], 3),
        "atr14": round(atr(candles, 14), 3),
        "rsi14": round(rsi(closes, 14), 2),
        "swings": swings,
        "bos": bos,
        "patterns": detect_patterns(candles),
    }


def candles_to_rows(candles: Iterable[Candle]) -> list[dict]:
    return [c.to_dict() for c in candles]
