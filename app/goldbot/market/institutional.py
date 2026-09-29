"""
Institutional / 'smart money' *proxies* from OHLC+volume.

True exchange whale tapes / dark-pool feeds are not available on retail MT5.
We approximate with: round-number liquidity, volume anomalies, absorption,
and stop-run (liquidity sweep) signatures used by SMC/ICT desks.
"""
from __future__ import annotations

from .candles import Candle, atr


def round_levels(price: float, step: float = 5.0) -> list[float]:
    base = round(price / step) * step
    return [base - 2 * step, base - step, base, base + step, base + step * 2]


def volume_anomaly(candles: list[Candle], lookback: int = 40) -> dict:
    if len(candles) < 10:
        return {"spike": False, "ratio": 1.0}
    vols = [c.volume for c in candles[-lookback:] if c.volume > 0]
    if not vols:
        # synthetic volume from range when feed has no real volume
        vols = [c.range for c in candles[-lookback:]]
    avg = sum(vols[:-1]) / max(1, len(vols) - 1)
    last = vols[-1]
    ratio = last / avg if avg else 1.0
    return {"spike": ratio >= 1.8, "ratio": round(ratio, 2), "avg": round(avg, 3)}


def liquidity_sweep(candles: list[Candle]) -> dict | None:
    """Stop-run: pierce prior swing then close back inside (common MM raid)."""
    if len(candles) < 25:
        return None
    prior = candles[-20:-1]
    last = candles[-1]
    swing_high = max(c.high for c in prior)
    swing_low = min(c.low for c in prior)
    if last.high > swing_high and last.close < swing_high and not last.bullish:
        return {"type": "sellside_raid_then_reject", "bias": "sell", "level": swing_high, "strength": 0.88}
    if last.low < swing_low and last.close > swing_low and last.bullish:
        return {"type": "buyside_raid_then_reject", "bias": "buy", "level": swing_low, "strength": 0.88}
    return None


def fair_value_gaps(candles: list[Candle]) -> list[dict]:
    gaps: list[dict] = []
    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        if a.high < c.low:
            gaps.append({"type": "bullish_fvg", "low": a.high, "high": c.low, "index": i})
        if a.low > c.high:
            gaps.append({"type": "bearish_fvg", "low": c.high, "high": a.low, "index": i})
    return gaps[-6:]


def order_block_proxy(candles: list[Candle]) -> dict | None:
    """Last opposite candle before impulsive move — retail OB approximation."""
    if len(candles) < 8:
        return None
    a = atr(candles, 14)
    for i in range(len(candles) - 2, max(3, len(candles) - 12), -1):
        c = candles[i]
        nxt = candles[i + 1]
        impulse = abs(nxt.close - nxt.open)
        if impulse < a * 0.8:
            continue
        if (not c.bullish) and nxt.bullish and nxt.close > c.high:
            return {"type": "bullish_ob", "low": c.low, "high": c.high, "bias": "buy", "strength": 0.75}
        if c.bullish and (not nxt.bullish) and nxt.close < c.low:
            return {"type": "bearish_ob", "low": c.low, "high": c.high, "bias": "sell", "strength": 0.75}
    return None


def institutional_read(candles: list[Candle]) -> dict:
    price = candles[-1].close if candles else 0.0
    sweep = liquidity_sweep(candles)
    vol = volume_anomaly(candles)
    ob = order_block_proxy(candles)
    fvgs = fair_value_gaps(candles)
    levels = round_levels(price, 5.0)
    near_round = min(abs(price - lv) for lv in levels) <= atr(candles, 14) * 0.35 if candles else False

    bias = "neutral"
    score = 0.0
    reasons: list[str] = []
    if sweep:
        bias = sweep["bias"]
        score += sweep["strength"]
        reasons.append(sweep["type"])
    if ob and (bias == "neutral" or ob["bias"] == bias):
        bias = ob["bias"]
        score += ob["strength"] * 0.7
        reasons.append(ob["type"])
    if vol["spike"]:
        score += 0.15
        reasons.append(f"volume_spike_x{vol['ratio']}")
    if near_round:
        score += 0.08
        reasons.append("round_number_magnet")

    score = min(1.0, score)
    return {
        "bias": bias,
        "institutional_score": round(score, 3),
        "liquidity_sweep": sweep,
        "order_block": ob,
        "fair_value_gaps": fvgs,
        "volume": vol,
        "round_levels": levels,
        "near_round_number": near_round,
        "reasons": reasons,
        "disclaimer": "Proxies from OHLC/volume — not a live institutional tape or dark-pool feed.",
    }
