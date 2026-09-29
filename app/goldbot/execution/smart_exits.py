"""Smart trade lifecycle — break-even, trail, partial TP, momentum fade."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from goldbot.brain.fast_pulse import FastPulse
from goldbot.config import settings
from goldbot.market.candles import Candle, atr
from goldbot.mt5.bridge import bridge
from goldbot.storage.state import store


@dataclass
class ManageResult:
    events: list[dict]
    closed: list[dict]
    updated: list[dict]


def _meta(trade: dict) -> dict:
    raw = trade.get("meta")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _is_live_trade(trade: dict) -> bool:
    mode = str(trade.get("mode") or trade.get("execution") or "paper").lower()
    return mode in {"mt5", "metaapi"} or str((_meta(trade) or {}).get("execution") or "").lower() == "metaapi"


def _broker_position_id(trade: dict) -> str | int | None:
    meta = _meta(trade)
    pid = trade.get("position_id") or meta.get("position_id") or trade.get("ticket") or meta.get("order_id") or trade.get("order_id")
    if pid in (None, "", 0, "0"):
        return None
    return pid


def _r_multiple(side: str, entry: float, sl: float, price: float) -> float:
    risk = abs(entry - sl)
    if risk <= 1e-9:
        return 0.0
    move = (price - entry) if side == "buy" else (entry - price)
    return move / risk


def manage_trade(
    trade: dict,
    bid: float,
    ask: float,
    candles: list[Candle],
    pulse: dict,
) -> tuple[dict | None, dict | None, dict | None]:
    """
    Returns (update_dict|None, close_dict|None, event|None)
    update_dict may change sl/tp/lot/meta; close_dict closes remaining size.
    """
    side = trade.get("side")
    entry = float(trade.get("entry") or 0)
    sl = float(trade.get("sl") or 0)
    tp = float(trade.get("tp") or 0)
    lot = float(trade.get("lot") or 0.01)
    meta = _meta(trade)
    mark = bid if side == "buy" else ask
    # Buys exit at bid; sells exit at ask
    exit_mark = bid if side == "buy" else ask

    r_now = _r_multiple(side, entry, sl if sl else entry * 0.999, mark)
    peak_r = max(float(meta.get("peak_r") or 0.0), r_now)
    meta["peak_r"] = round(peak_r, 3)
    meta["last_r"] = round(r_now, 3)
    meta["managed_at"] = time.time()

    a = atr(candles, 14) if candles else abs(entry) * 0.0005
    risk = abs(entry - sl) if sl else a * 1.15

    # 1) Hard SL / TP — use exit side (bid for buys, ask for sells)
    if side == "buy":
        if sl and bid <= sl:
            return None, {"reason": "sl", "exit": bid, "lot": lot, "pnl_r": r_now}, {"type": "hard_sl"}
        if tp and bid >= tp:
            return None, {"reason": "tp", "exit": bid, "lot": lot, "pnl_r": r_now}, {"type": "hard_tp"}
    else:
        if sl and ask >= sl:
            return None, {"reason": "sl", "exit": ask, "lot": lot, "pnl_r": r_now}, {"type": "hard_sl"}
        if tp and ask <= tp:
            return None, {"reason": "tp", "exit": ask, "lot": lot, "pnl_r": r_now}, {"type": "hard_tp"}

    update = None
    event = None

    # 2) Break-even after +1.0R
    if r_now >= 1.0 and not meta.get("be_locked"):
        be = entry + (0.05 * risk if side == "buy" else -0.05 * risk)
        if side == "buy" and (sl < be):
            sl = be
            meta["be_locked"] = True
            update = {"sl": sl, "meta": meta}
            event = {"type": "break_even", "sl": sl, "r": r_now}
        elif side == "sell" and (sl > be or sl == 0):
            sl = be
            meta["be_locked"] = True
            update = {"sl": sl, "meta": meta}
            event = {"type": "break_even", "sl": sl, "r": r_now}

    # 3) Trail after +1.5R — lock 0.8R then follow
    if r_now >= 1.5:
        trail_dist = max(a * 0.55, risk * 0.45)
        if side == "buy":
            new_sl = mark - trail_dist
            floor = entry + risk * 0.8
            new_sl = max(new_sl, floor, sl)
            if new_sl > sl + 1e-6:
                sl = new_sl
                meta["trailing"] = True
                update = {"sl": sl, "meta": meta}
                event = {"type": "trail", "sl": sl, "r": r_now}
        else:
            new_sl = mark + trail_dist
            ceiling = entry - risk * 0.8
            new_sl = min(new_sl, ceiling, sl) if sl else min(new_sl, ceiling)
            if sl == 0 or new_sl < sl - 1e-6:
                sl = new_sl
                meta["trailing"] = True
                update = {"sl": sl, "meta": meta}
                event = {"type": "trail", "sl": sl, "r": r_now}

    # 4) Partial take-profit at +1.2R (once)
    # Live: only after broker partial succeeds. Paper: local lot shrink + equity.
    if r_now >= 1.2 and not meta.get("partial_taken") and lot >= 0.02:
        part = round(max(0.01, lot * 0.4), 2)
        remain = round(lot - part, 2)
        if remain >= 0.01:
            live = _is_live_trade(trade)
            if live:
                pid = _broker_position_id(trade)
                if pid and bridge.is_live_execution():
                    broker = bridge.close_position(pid, volume=part)
                    if broker.get("ok"):
                        part_exit = exit_mark
                        move = (part_exit - entry) if side == "buy" else (entry - part_exit)
                        part_pnl = move * part * 100.0
                        meta["partial_taken"] = True
                        meta["partial_pnl"] = round(part_pnl, 2)
                        update = {"lot": remain, "meta": meta, "sl": sl}
                        event = {
                            "type": "partial_tp",
                            "closed_lot": part,
                            "remain": remain,
                            "pnl": round(part_pnl, 2),
                            "r": r_now,
                            "broker": True,
                        }
                        store.log_event("partial_tp", {"trade_id": trade.get("id"), **event})
                    else:
                        store.log_event(
                            "partial_tp_fail",
                            {"trade_id": trade.get("id"), "position_id": pid, **broker},
                        )
                # else: skip partial until live executor is up — do not shrink local lot
            else:
                part_exit = exit_mark
                move = (part_exit - entry) if side == "buy" else (entry - part_exit)
                part_pnl = move * part * 100.0
                meta["partial_taken"] = True
                meta["partial_pnl"] = round(part_pnl, 2)
                update = {"lot": remain, "meta": meta, "sl": sl}
                bridge.paper_equity += part_pnl
                bridge.paper_balance = bridge.paper_equity
                event = {
                    "type": "partial_tp",
                    "closed_lot": part,
                    "remain": remain,
                    "pnl": round(part_pnl, 2),
                    "r": r_now,
                }
                store.log_event("partial_tp", {"trade_id": trade.get("id"), **event})

    # 5) Momentum fade exit — protect open profit
    if r_now >= 0.45 and pulse:
        adverse = (pulse.get("bias") == "sell" and side == "buy") or (pulse.get("bias") == "buy" and side == "sell")
        strong = abs(float(pulse.get("score") or 0)) >= 0.35 or pulse.get("trigger")
        # give-back from peak
        giveback = peak_r - r_now
        if adverse and strong and (r_now >= 0.7 or giveback >= 0.55):
            return update, {"reason": "momentum_fade", "exit": exit_mark, "lot": lot, "pnl_r": r_now}, {
                "type": "momentum_fade",
                "r": r_now,
                "peak_r": peak_r,
            }

    # 6) Time stop — stale trade with no progress
    opened = float(trade.get("ts") or time.time())
    age = time.time() - opened
    max_hold = float(getattr(settings, "max_hold_seconds", 3 * 3600))
    if age >= max_hold:
        return update, {"reason": "time_stop", "exit": exit_mark, "lot": lot, "pnl_r": r_now}, {"type": "time_stop", "age": age}
    if age >= 45 * 60 and r_now < 0.15 and peak_r < 0.35:
        return update, {"reason": "stale_exit", "exit": exit_mark, "lot": lot, "pnl_r": r_now}, {"type": "stale_exit", "age": age}

    if update:
        return update, None, event
    # still refresh meta peak
    return {"meta": meta, "sl": sl}, None, None


def run_smart_manager(
    bid: float,
    ask: float,
    candles: list[Candle],
    pulse_engine: FastPulse,
) -> ManageResult:
    pulse = pulse_engine.analyze(candles)
    events: list[dict] = []
    closed: list[dict] = []
    updated: list[dict] = []
    for t in store.open_trades():
        upd, cls, ev = manage_trade(t, bid, ask, candles, pulse)
        if upd:
            store.update_trade(int(t["id"]), **{k: v for k, v in upd.items() if k in {"sl", "tp", "lot", "meta", "status", "pnl"}})
            updated.append({"trade_id": t["id"], **upd})
        if upd and not cls:
            # Push SL/TP changes to live broker when possible
            if _is_live_trade(t) and bridge.is_live_execution():
                pid = _broker_position_id(t)
                if pid and ("sl" in upd or "tp" in upd):
                    mod = bridge.modify_position_sl_tp(pid, sl=upd.get("sl"), tp=upd.get("tp") or t.get("tp"))
                    if not mod.get("ok"):
                        store.log_event("sl_tp_modify_fail", {"trade_id": t["id"], **mod})
        if cls:
            exit_px = float(cls["exit"])
            lot = float(cls["lot"])
            entry = float(t.get("entry") or 0)
            side = t.get("side")
            # Live trades: close on broker FIRST — never mark local-only close as success
            if _is_live_trade(t):
                if not bridge.is_live_execution():
                    store.log_event(
                        "broker_close_skip",
                        {"trade_id": t["id"], "reason": cls.get("reason"), "detail": "executor_offline"},
                    )
                    if ev:
                        events.append({"trade_id": t["id"], **ev, "broker_close": "offline"})
                    continue
                pid = _broker_position_id(t)
                if not pid:
                    store.log_event(
                        "broker_close_fail",
                        {"trade_id": t["id"], "reason": cls.get("reason"), "error": "no_position_id"},
                    )
                    if ev:
                        events.append({"trade_id": t["id"], **ev, "broker_close": "no_position_id"})
                    continue
                broker = bridge.close_position(pid)
                if not broker.get("ok"):
                    store.log_event(
                        "broker_close_fail",
                        {"trade_id": t["id"], "position_id": pid, "reason": cls.get("reason"), **broker},
                    )
                    if ev:
                        events.append({"trade_id": t["id"], **ev, "broker_close": "failed"})
                    continue
            move = (exit_px - entry) if side == "buy" else (entry - exit_px)
            pnl = move * lot * 100.0
            # include prior partial pnl in meta only for reporting
            meta = _meta(t)
            if upd and "meta" in upd:
                meta = upd["meta"]
            total_pnl = pnl + float(meta.get("partial_pnl") or 0)
            store.close_trade(int(t["id"]), pnl=total_pnl, status=f"closed_{cls['reason']}")
            if not _is_live_trade(t):
                bridge.paper_equity += pnl
                bridge.paper_balance = bridge.paper_equity
            row = {"trade_id": t["id"], "pnl": round(total_pnl, 2), **cls}
            closed.append(row)
            store.log_event("trade_close", row)
        if ev:
            events.append({"trade_id": t["id"], **ev})
    return ManageResult(events=events, closed=closed, updated=updated)
