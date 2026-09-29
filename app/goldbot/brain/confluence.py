"""Elite confluence brain — weighted multi-school vote with smart vetoes."""
from __future__ import annotations

from dataclasses import dataclass

from goldbot.config import settings
from goldbot.market.candles import Candle, atr, summarize_structure
from goldbot.market.institutional import institutional_read
from goldbot.strategy.schools import all_school_votes

# Core alpha schools weigh more; session/vol are filters with lighter vote weight.
SCHOOL_WEIGHTS = {
    "Price Action": 1.35,
    "SMC / ICT": 1.40,
    "Trend": 1.15,
    "Session": 0.65,
    "Volatility": 0.45,
}


@dataclass
class Signal:
    action: str  # buy | sell | flat
    confluence: float
    entry: float
    stop: float
    take: float
    reward_risk: float
    schools: list[dict]
    vetoes: list[str]
    narrative: str
    structure: dict
    institutional: dict
    quality: str = "none"

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "confluence": self.confluence,
            "entry": self.entry,
            "stop": self.stop,
            "take": self.take,
            "reward_risk": self.reward_risk,
            "schools": self.schools,
            "vetoes": self.vetoes,
            "narrative": self.narrative,
            "structure": self.structure,
            "institutional": self.institutional,
            "quality": self.quality,
        }


def _weight_for(school_name: str) -> float:
    for key, w in SCHOOL_WEIGHTS.items():
        if school_name.startswith(key):
            return w
    return 1.0


def _levels(action: str, price: float, candles: list[Candle], rr: float) -> tuple[float, float, float, float]:
    a = max(atr(candles, 14), price * 0.0008)
    if action == "buy":
        stop = price - a * 1.15
        risk = price - stop
        take = price + risk * rr
    else:
        stop = price + a * 1.15
        risk = stop - price
        take = price - risk * rr
    return price, stop, take, (abs(take - price) / risk if risk else 0.0)


def build_signal(candles: list[Candle], spread_points: float = 0.0) -> Signal:
    schools = all_school_votes(candles)
    structure = summarize_structure(candles)
    inst = institutional_read(candles)
    price = candles[-1].close

    buy_w = sell_w = weight_sum = 0.0
    for v in schools:
        w = _weight_for(v["school"])
        weight_sum += w
        scored = float(v.get("strength") or 0) * w
        if v["bias"] == "buy":
            buy_w += scored
        elif v["bias"] == "sell":
            sell_w += scored

    total = buy_w + sell_w + 1e-9
    action = "flat"
    confluence = 0.0
    majority = max(buy_w, sell_w) / total
    if buy_w > sell_w and majority >= 0.55:
        action = "buy"
        confluence = min(1.0, buy_w / max(weight_sum, 1e-9))
    elif sell_w > buy_w and majority >= 0.55:
        action = "sell"
        confluence = min(1.0, sell_w / max(weight_sum, 1e-9))

    pa = next((v for v in schools if v["school"].startswith("Price Action")), None)
    smc = next((v for v in schools if v["school"].startswith("SMC")), None)
    core_aligned = bool(
        pa and smc and pa["bias"] == smc["bias"] and pa["bias"] in {"buy", "sell"} and pa["bias"] == action
    )
    if core_aligned:
        confluence = min(1.0, confluence + 0.10)
    if action != "flat" and inst["bias"] == action:
        confluence = min(1.0, confluence + 0.06)

    vetoes: list[str] = []
    soft_notes: list[str] = []

    if spread_points > settings.max_spread_points:
        vetoes.append(f"spread_too_wide:{spread_points}")

    vol_vote = next((v for v in schools if v["school"].startswith("Volatility")), None)
    vol_tradable = True
    if vol_vote:
        detail = vol_vote.get("detail") or {}
        # FIX: previously vetoed whenever bias was neutral (trend flat) even if ATR regime was fine.
        if "tradable" in detail:
            vol_tradable = bool(detail["tradable"])
        else:
            vol_tradable = vol_vote.get("strength", 0) >= 0.5
        if not vol_tradable:
            vetoes.append("volatility_regime_blocked")

    session_vote = next((v for v in schools if v["school"].startswith("Session")), None)
    in_killzone = True
    if session_vote:
        in_killzone = bool((session_vote.get("detail") or {}).get("prefer_trade", True))
        if not in_killzone:
            if core_aligned and confluence >= settings.min_confluence + 0.08:
                soft_notes.append("outside_killzone_soft_pass")
            else:
                vetoes.append("outside_killzone")

    min_conf = settings.min_confluence - (0.05 if core_aligned else 0.0)
    if confluence < min_conf:
        vetoes.append(f"confluence_below_{round(min_conf, 2)}")

    entry, stop, take, rr = _levels(action if action != "flat" else "buy", price, candles, settings.min_reward_risk)
    if action == "flat":
        rr = 0.0

    final_action = "flat" if vetoes else action
    quality = "none"
    if final_action != "flat":
        if core_aligned and in_killzone and confluence >= 0.75:
            quality = "A"
        elif core_aligned:
            quality = "B"
        else:
            quality = "C"

    narrative = _narrative(final_action, confluence, schools, vetoes, inst, quality, soft_notes)
    return Signal(
        action=final_action,
        confluence=round(confluence, 3),
        entry=round(entry, 3),
        stop=round(stop, 3),
        take=round(take, 3),
        reward_risk=round(rr, 3),
        schools=schools,
        vetoes=vetoes,
        narrative=narrative,
        structure=structure,
        institutional=inst,
        quality=quality,
    )


def _narrative(
    action: str,
    conf: float,
    schools: list[dict],
    vetoes: list[str],
    inst: dict,
    quality: str,
    soft_notes: list[str],
) -> str:
    aligned = [s["school"] for s in schools if s["bias"] == action and action != "flat"]
    if action == "flat":
        reason = ", ".join(vetoes) if vetoes else "no_majority"
        return f"لا صفقة الآن — الحفظ أولاً. أسباب: {reason}."
    side = "شراء" if action == "buy" else "بيع"
    inst_note = "; ".join(inst.get("reasons") or []) or "لا إشارة مؤسساتية قوية"
    soft = f" ({', '.join(soft_notes)})" if soft_notes else ""
    return (
        f"إشارة {side} جودة {quality} بتقارب {conf:.0%} عبر: {', '.join(aligned)}. "
        f"قراءة السيولة: {inst_note}.{soft} إدارة مخاطر صارمة مفعّلة."
    )
