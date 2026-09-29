"""Global trading schools — each returns a scored vote for XAUUSD."""
from __future__ import annotations

from goldbot.market.candles import Candle, summarize_structure, atr
from goldbot.market.institutional import institutional_read
from goldbot.market.sessions import killzone_score


SchoolVote = dict


def school_price_action(candles: list[Candle]) -> SchoolVote:
    s = summarize_structure(candles)
    pats = s.get("patterns") or []
    buy = sum(p["strength"] for p in pats if p["bias"] == "buy")
    sell = sum(p["strength"] for p in pats if p["bias"] == "sell")
    bias = "buy" if buy > sell else "sell" if sell > buy else "neutral"
    strength = min(1.0, abs(buy - sell) + (0.2 if bias != "neutral" else 0))
    return {
        "school": "Price Action (Nison / Al Brooks lineage)",
        "bias": bias,
        "strength": round(strength, 3),
        "detail": {"patterns": pats, "trend": s["trend"]},
    }


def school_smc_ict(candles: list[Candle]) -> SchoolVote:
    inst = institutional_read(candles)
    return {
        "school": "SMC / ICT (liquidity · OB · FVG)",
        "bias": inst["bias"],
        "strength": inst["institutional_score"],
        "detail": {
            "sweep": inst["liquidity_sweep"],
            "order_block": inst["order_block"],
            "fvg": inst["fair_value_gaps"],
            "reasons": inst["reasons"],
        },
    }


def school_trend_following(candles: list[Candle]) -> SchoolVote:
    s = summarize_structure(candles)
    bias = "buy" if s["trend"] == "bull" else "sell" if s["trend"] == "bear" else "neutral"
    strength = 0.55 if bias != "neutral" else 0.2
    if s.get("bos"):
        strength = min(1.0, strength + 0.25)
    if s["rsi14"] > 70 and bias == "buy":
        strength *= 0.6
    if s["rsi14"] < 30 and bias == "sell":
        strength *= 0.6
    return {
        "school": "Trend (Dow / EMA stack / ADX-style)",
        "bias": bias,
        "strength": round(strength, 3),
        "detail": {"ema20": s["ema20"], "ema50": s["ema50"], "rsi": s["rsi14"], "bos": s["bos"]},
    }


def school_session(candles: list[Candle]) -> SchoolVote:
    kz = killzone_score()
    s = summarize_structure(candles)
    bias = "buy" if s["trend"] == "bull" else "sell" if s["trend"] == "bear" else "neutral"
    strength = kz["session_edge"] * (0.85 if bias != "neutral" else 0.35)
    return {
        "school": "Session Liquidity (London / NY)",
        "bias": bias if kz["prefer_trade"] else "neutral",
        "strength": round(strength if kz["prefer_trade"] else strength * 0.4, 3),
        "detail": kz,
    }


def school_volatility_regime(candles: list[Candle]) -> SchoolVote:
    if len(candles) < 30:
        return {"school": "Volatility Regime (ATR)", "bias": "neutral", "strength": 0.0, "detail": {}}
    a = atr(candles, 14)
    ranges = [c.range for c in candles[-40:]]
    avg = sum(ranges) / len(ranges)
    # Avoid chop (too quiet) and news spikes (too wild)
    ratio = a / avg if avg else 1.0
    ok = 0.7 <= ratio <= 1.65
    s = summarize_structure(candles)
    bias = "buy" if s["trend"] == "bull" else "sell" if s["trend"] == "bear" else "neutral"
    return {
        "school": "Volatility Regime (ATR filter)",
        "bias": bias if ok else "neutral",
        "strength": round(0.7 if ok else 0.15, 3),
        "detail": {"atr": round(a, 3), "atr_vs_avg": round(ratio, 3), "tradable": ok},
    }


def all_school_votes(candles: list[Candle]) -> list[SchoolVote]:
    return [
        school_price_action(candles),
        school_smc_ict(candles),
        school_trend_following(candles),
        school_session(candles),
        school_volatility_regime(candles),
    ]
