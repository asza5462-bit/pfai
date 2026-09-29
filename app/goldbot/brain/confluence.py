"""Elite confluence brain — multi-school vote with hard vetoes."""
from __future__ import annotations

from dataclasses import dataclass

from goldbot.config import settings
from goldbot.market.candles import Candle, atr, summarize_structure
from goldbot.market.institutional import institutional_read
from goldbot.strategy.schools import all_school_votes


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
        }


def _levels(action: str, price: float, candles: list[Candle], rr: float) -> tuple[float, float, float, float]:
    a = max(atr(candles, 14), price * 0.0008)
    # Gold stop: 1.15 ATR, target: rr * risk
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

    buy_w = sum(v["strength"] for v in schools if v["bias"] == "buy")
    sell_w = sum(v["strength"] for v in schools if v["bias"] == "sell")
    total = buy_w + sell_w + 1e-9
    action = "flat"
    confluence = 0.0
    if buy_w > sell_w and buy_w / total >= 0.58:
        action = "buy"
        confluence = buy_w / len(schools)
    elif sell_w > buy_w and sell_w / total >= 0.58:
        action = "sell"
        confluence = sell_w / len(schools)

    # Institutional alignment bonus
    if action != "flat" and inst["bias"] == action:
        confluence = min(1.0, confluence + 0.08)

    vetoes: list[str] = []
    if spread_points > settings.max_spread_points:
        vetoes.append(f"spread_too_wide:{spread_points}")
    session_vote = next((v for v in schools if v["school"].startswith("Session")), None)
    if session_vote and not (session_vote.get("detail") or {}).get("prefer_trade", True):
        if confluence < 0.9:
            vetoes.append("outside_killzone")
    vol_vote = next((v for v in schools if v["school"].startswith("Volatility")), None)
    if vol_vote and vol_vote["bias"] == "neutral":
        vetoes.append("volatility_regime_blocked")
    if confluence < settings.min_confluence:
        vetoes.append(f"confluence_below_{settings.min_confluence}")

    entry, stop, take, rr = _levels(action if action != "flat" else "buy", price, candles, settings.min_reward_risk)
    if action == "flat":
        rr = 0.0

    if vetoes:
        action = "flat"

    narrative = _narrative(action, confluence, schools, vetoes, inst)
    return Signal(
        action=action,
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
    )


def _narrative(action: str, conf: float, schools: list[dict], vetoes: list[str], inst: dict) -> str:
    aligned = [s["school"] for s in schools if s["bias"] == action and action != "flat"]
    if action == "flat":
        reason = ", ".join(vetoes) if vetoes else "no_majority"
        return f"لا صفقة الآن — الحفظ أولاً. أسباب: {reason}."
    side = "شراء" if action == "buy" else "بيع"
    inst_note = "; ".join(inst.get("reasons") or []) or "لا إشارة مؤسساتية قوية"
    return (
        f"إشارة {side} بتقارب {conf:.0%} عبر: {', '.join(aligned)}. "
        f"قراءة السيولة: {inst_note}. إدارة المخاطر ترفض أي صفقة دون وقف وهدف RR."
    )
