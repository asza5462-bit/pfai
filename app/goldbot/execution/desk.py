"""AURUM trading desk — dual-loop fast pulse + smart lifecycle."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from goldbot.brain.confluence import build_signal
from goldbot.brain.fast_pulse import fast_pulse
from goldbot.config import settings
from goldbot.execution.smart_exits import run_smart_manager
from goldbot.mt5.bridge import bridge
from goldbot.risk.manager import RiskManager
from goldbot.storage.state import store

log = logging.getLogger("aurum.desk")


class TradingDesk:
    def __init__(self) -> None:
        self.risk = RiskManager()
        self._lock = threading.RLock()
        self._task: asyncio.Task | None = None
        self._running = False
        self.armed = False
        self.state = "IDLE"  # IDLE | SCANNING | ARMED | IN_TRADE | MANAGING
        self.last: dict[str, Any] = {}
        self.last_pulse: dict[str, Any] = {}
        self.last_manage: dict[str, Any] = {}
        self._last_full_scan = 0.0
        self._pending_signal: dict[str, Any] | None = None
        self.account = bridge.connect()
        opens = store.open_trades()
        self.risk.state.open_trades = len(opens)
        if opens:
            self.state = "IN_TRADE"
        if settings.auto_trade:
            store.set_kv("auto_trade", True)
            self.armed = True
            self.state = "ARMED" if not opens else "IN_TRADE"
        store.log_event(
            "boot",
            {
                "mode": self.account.mode,
                "detail": self.account.detail,
                "auto_trade": self.auto_trade,
                "tick_seconds": settings.tick_seconds,
            },
        )

    @property
    def auto_trade(self) -> bool:
        return bool(store.get_kv("auto_trade", settings.auto_trade))

    def set_auto_trade(self, enabled: bool) -> None:
        store.set_kv("auto_trade", bool(enabled))
        self.armed = bool(enabled)
        if enabled and self.state == "IDLE":
            self.state = "ARMED"
        if not enabled and not store.open_trades():
            self.state = "IDLE"
        store.log_event("auto_trade", {"enabled": bool(enabled)})

    def start_desk(self) -> dict:
        self._refresh_account()
        live = bridge.is_live_execution() and self.account.connected and self.account.mode == "mt5"
        # If MT5 credentials/mode are active, refuse to arm on paper/fake fills
        if settings.mode == "mt5" and not live:
            self.set_auto_trade(False)
            self.armed = False
            self.state = "IDLE"
            snap = self.scan(full=True)
            return {
                "ok": False,
                "armed": False,
                "auto_trade": False,
                "mode": self.account.mode,
                "execution": bridge.execution or "none",
                "live": False,
                "state": self.state,
                "scan": snap,
                "executed": None,
                "error": "not_live",
                "message": (
                    "التداول الحقيقي غير متصل بعد — لن نفتح صفقات وهمية. "
                    "أكمل ربط MetaApi/Exness حتى يظهر «متصل Exness» ثم اضغط ابدأ."
                ),
            }
        self.armed = True
        self.set_auto_trade(True)
        self.state = "ARMED"
        self.start_background()
        snap = self.scan(full=True)
        executed = None
        if live and snap["execution_gate"]["allowed"] and snap["signal"]["action"] != "flat":
            if snap.get("pulse_confirm", True):
                executed = self.execute_signal(force=False)
        return {
            "ok": True,
            "armed": True,
            "auto_trade": True,
            "mode": self.account.mode,
            "execution": bridge.execution or ("paper" if self.account.mode == "paper" else "pending"),
            "live": live,
            "state": self.state,
            "scan": snap,
            "executed": executed,
            "message": (
                "التنفيذ الحقيقي على Exness يعمل — تحليل بأجزاء الثانية + إدارة ذكية."
                if live
                else "المكتب الورقي يعمل للتجربة فقط — ليس تنفيذاً على Exness."
            ),
        }

    def _refresh_account(self) -> None:
        if bridge.mode == "paper":
            self.account.balance = bridge.paper_balance
            self.account.equity = bridge.paper_equity
            self.account.free_margin = bridge.paper_equity
        else:
            self.account = bridge.connect()

    def pulse_tick(self) -> dict:
        """Sub-second path: quote → pulse → smart manage open trades."""
        with self._lock:
            t0 = time.perf_counter()
            tick = bridge.tick()
            bid = float(tick["bid"])
            ask = float(tick["ask"])
            fast_pulse.push(bid, ask)
            candles = bridge.fetch_candles(count=120)
            pulse = fast_pulse.analyze(candles)
            self.last_pulse = pulse

            managed = run_smart_manager(bid, ask, candles, fast_pulse)
            if managed.closed:
                for c in managed.closed:
                    self.risk.register_close(float(c.get("pnl") or 0))
            self.risk.state.open_trades = len(store.open_trades())
            self._refresh_account()

            if store.open_trades():
                self.state = "MANAGING" if managed.updated or managed.events else "IN_TRADE"
            elif self.auto_trade:
                self.state = "ARMED"
            else:
                self.state = "IDLE"

            # Try entry on pending confluence with pulse confirm (no heavy rescan)
            executed = None
            if (
                self.auto_trade
                and self._pending_signal
                and not store.open_trades()
                and self._pending_signal.get("action") in {"buy", "sell"}
            ):
                if self._try_pending_entry(bid, ask, pulse):
                    executed = True

            elapsed_ms = (time.perf_counter() - t0) * 1000
            payload = {
                "state": self.state,
                "tick": tick,
                "pulse": pulse,
                "manage": {
                    "events": managed.events,
                    "closed": managed.closed,
                    "updated": managed.updated,
                },
                "open_trades": store.open_trades(),
                "account": self.account.to_dict(),
                "elapsed_ms": round(elapsed_ms, 2),
                "executed_pending": bool(executed),
                "pending_signal": self._pending_signal,
            }
            self.last_manage = payload
            if self.last:
                self.last["pulse"] = pulse
                self.last["state"] = self.state
                self.last["tick"] = tick
                self.last["open_trades"] = payload["open_trades"]
                self.last["manage"] = payload["manage"]
                self.last["latency_ms"] = payload["elapsed_ms"]
            return payload

    def _try_pending_entry(self, bid: float, ask: float, pulse: dict) -> bool:
        sig = self._pending_signal or {}
        action = sig.get("action")
        if action not in {"buy", "sell"}:
            return False
        if settings.require_pulse_confirm and not fast_pulse.confirms(action, pulse):
            return False
        # anti-chase: price already ran away from planned entry
        entry = float(sig.get("entry") or 0)
        stop = float(sig.get("stop") or 0)
        risk = abs(entry - stop) or 1.0
        px = ask if action == "buy" else bid
        chase = abs(px - entry) / risk
        if chase > settings.max_chase_r:
            store.log_event("entry_skip", {"reason": "chase", "chase_r": chase, "action": action})
            self._pending_signal = None
            return False
        equity = self.account.equity or settings.paper_balance
        allowed, reason = self.risk.allow_trade(equity, action)
        if not allowed:
            return False
        lot = self.risk.lot_size(equity, entry, stop)
        # Shift SL/TP with live fill so R:R geometry stays intact
        delta = px - entry
        sl = float(sig["stop"]) + delta
        tp = float(sig["take"]) + delta
        result = bridge.order_market(action, lot, sl, tp, comment="AURUM-FAST")
        if not result.get("ok"):
            return False
        fill = float(result.get("price") or result.get("entry") or 0)
        if fill <= 0 and result.get("mode") != "paper":
            store.log_event("trade_reject", {**result, "error": "filled_no_price"})
            return False
        self.risk.register_open()
        trade_id = store.add_trade(
            {
                **result,
                "status": "open",
                "meta": {
                    "confluence": sig.get("confluence"),
                    "quality": sig.get("quality"),
                    "pulse": pulse,
                    "narrative": sig.get("narrative"),
                    "fast_entry": True,
                    "position_id": result.get("position_id"),
                    "order_id": result.get("order_id"),
                    "execution": result.get("execution") or result.get("mode"),
                },
            }
        )
        self._pending_signal = None
        self.state = "IN_TRADE"
        store.log_event("trade_open", {"trade_id": trade_id, "fast": True, **result})
        return True

    def scan(self, full: bool = True) -> dict:
        with self._lock:
            self.state = "SCANNING" if not store.open_trades() else self.state
            t0 = time.perf_counter()
            candles = bridge.fetch_candles()
            tick = bridge.tick()
            bid, ask = float(tick["bid"]), float(tick["ask"])
            fast_pulse.push(bid, ask)
            # smart manage first (integrated)
            managed = run_smart_manager(bid, ask, candles or [], fast_pulse)
            if managed.closed:
                for c in managed.closed:
                    self.risk.register_close(float(c.get("pnl") or 0))

            if not candles:
                self._refresh_account()
                payload = {
                    "symbol": settings.symbol,
                    "timeframe": settings.timeframe,
                    "tick": tick,
                    "account": self.account.to_dict(),
                    "signal": {
                        "action": "flat",
                        "confluence": 0,
                        "quality": "none",
                        "narrative": "بانتظار شموع الوسيط من MetaApi",
                        "entry": bid,
                        "stop": 0,
                        "take": 0,
                        "schools": [],
                    },
                    "pulse": {"bias": "neutral", "score": 0},
                    "pulse_confirm": False,
                    "pending_signal": None,
                    "risk": self.risk.state.to_dict(),
                    "execution_gate": {"allowed": False, "reason": "broker_candles_warming", "lot": 0},
                    "auto_trade": self.auto_trade,
                    "armed": self.armed or self.auto_trade,
                    "state": self.state,
                    "feed": tick.get("source") or bridge.mode,
                    "manage": {"events": managed.events, "closed": managed.closed, "updated": managed.updated},
                    "closed_this_scan": managed.closed,
                    "open_trades": store.open_trades(),
                    "candles_tail": [],
                    "candle_count": 0,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "tick_seconds": settings.tick_seconds,
                    "loop_seconds": settings.loop_seconds,
                }
                self.last = payload
                return payload

            signal = build_signal(candles, spread_points=float(tick.get("spread_points") or 0))
            pulse = fast_pulse.analyze(candles)
            self.last_pulse = pulse
            pulse_ok = (not settings.require_pulse_confirm) or signal.action == "flat" or fast_pulse.confirms(
                signal.action, pulse
            )

            self._refresh_account()
            equity = self.account.equity or settings.paper_balance
            self.risk.roll_day(equity)
            self.risk.state.open_trades = len(store.open_trades())
            allowed, reason = self.risk.allow_trade(equity, signal.action)
            if signal.action != "flat" and not pulse_ok:
                allowed, reason = False, "awaiting_pulse_confirm"
            if signal.action != "flat" and len(candles) < 40:
                allowed, reason = False, "broker_candles_warming"
            lot = self.risk.lot_size(equity, signal.entry, signal.stop) if signal.action != "flat" else 0.0
            if signal.action != "flat" and lot < 0.01:
                allowed, reason = False, "lot_too_small"

            if signal.action in {"buy", "sell"} and signal.quality in {"A", "B", "C"}:
                self._pending_signal = signal.to_dict()
            elif signal.action == "flat":
                self._pending_signal = None

            if store.open_trades():
                self.state = "IN_TRADE"
            elif self.auto_trade:
                self.state = "ARMED"
            else:
                self.state = "IDLE"

            elapsed_ms = (time.perf_counter() - t0) * 1000
            payload = {
                "symbol": settings.symbol,
                "timeframe": settings.timeframe,
                "tick": tick,
                "account": self.account.to_dict(),
                "signal": signal.to_dict(),
                "pulse": pulse,
                "pulse_confirm": pulse_ok,
                "pending_signal": self._pending_signal,
                "risk": self.risk.state.to_dict(),
                "execution_gate": {"allowed": allowed, "reason": reason, "lot": lot},
                "auto_trade": self.auto_trade,
                "armed": self.armed or self.auto_trade,
                "state": self.state,
                "feed": tick.get("source") or bridge.mode,
                "manage": {
                    "events": managed.events,
                    "closed": managed.closed,
                    "updated": managed.updated,
                },
                "closed_this_scan": managed.closed,
                "open_trades": store.open_trades(),
                "candles_tail": [c.to_dict() for c in candles[-80:]],
                "candle_count": len(candles),
                "latency_ms": round(elapsed_ms, 2),
                "tick_seconds": settings.tick_seconds,
                "loop_seconds": settings.loop_seconds,
            }
            self.last = payload
            self._last_full_scan = time.time()
            store.log_event(
                "scan",
                {
                    "action": signal.action,
                    "confluence": signal.confluence,
                    "quality": signal.quality,
                    "pulse": pulse.get("bias"),
                    "pulse_ok": pulse_ok,
                    "state": self.state,
                    "latency_ms": payload["latency_ms"],
                },
            )
            return payload

    def execute_signal(self, force: bool = False) -> dict:
        snap = self.scan(full=True)
        sig = snap["signal"]
        gate = snap["execution_gate"]
        if sig["action"] == "flat":
            return {"ok": False, "error": "no_actionable_signal", "scan": snap}
        # Hard risk halt — never bypassable by force
        if self.risk.state.halted:
            return {"ok": False, "error": self.risk.state.halt_reason or "halted", "scan": snap}
        if not force and not gate["allowed"]:
            return {"ok": False, "error": gate["reason"], "scan": snap}
        if not force and not self.auto_trade:
            return {"ok": False, "error": "auto_trade_disabled", "scan": snap}
        if not force and settings.require_pulse_confirm and not snap.get("pulse_confirm"):
            self._pending_signal = sig
            return {"ok": False, "error": "awaiting_pulse_confirm", "scan": snap}
        # Hard gate: never paper-fill or order while claiming live MT5
        if settings.mode == "mt5":
            self._refresh_account()
            if not (bridge.is_live_execution() and self.account.connected):
                return {
                    "ok": False,
                    "error": "not_live",
                    "message": "التنفيذ الحقيقي غير متصل — لن نفتح صفقة وهمية.",
                    "scan": snap,
                }

        lot = float(gate.get("lot") or 0)
        if lot < 0.01:
            return {"ok": False, "error": "lot_too_small", "message": "حجم الصفقة أقل من الحد الأدنى 0.01", "scan": snap}
        result = bridge.order_market(sig["action"], lot, sig["stop"], sig["take"], comment="AURUM-ELITE")
        if result.get("ok"):
            fill = float(result.get("price") or result.get("entry") or 0)
            if fill <= 0 and result.get("mode") != "paper":
                store.log_event("trade_reject", {**result, "error": "filled_no_price"})
                return {"ok": False, "error": "filled_no_price", "result": result, "scan": snap}
            self.risk.register_open()
            trade_id = store.add_trade(
                {
                    **result,
                    "status": "open",
                    "meta": {
                        "confluence": sig["confluence"],
                        "quality": sig.get("quality"),
                        "narrative": sig["narrative"],
                        "pulse": snap.get("pulse"),
                        "position_id": result.get("position_id"),
                        "order_id": result.get("order_id"),
                        "execution": result.get("execution") or result.get("mode"),
                    },
                }
            )
            if result.get("mode") == "paper":
                cost = abs(sig["entry"] - sig["stop"]) * lot * 100 * 0.02
                bridge.paper_equity -= cost
                bridge.paper_balance = bridge.paper_equity
            self._pending_signal = None
            self.state = "IN_TRADE"
            store.log_event("trade_open", {"trade_id": trade_id, **result})
            # Reuse snap + light refresh instead of a second full scan
            snap2 = dict(snap)
            snap2["open_trades"] = store.open_trades()
            snap2["account"] = self.account.to_dict()
            self.last = snap2
            return {"ok": True, "trade_id": trade_id, "result": result, "scan": snap2}
        store.log_event("trade_reject", result)
        return {"ok": False, "error": result.get("error") or "order_failed", "result": result, "scan": snap}

    def _tick_once(self) -> None:
        """Sync desk work — always run off the asyncio event loop."""
        self.pulse_tick()
        if time.time() - self._last_full_scan >= settings.loop_seconds:
            snap = self.scan(full=True)
            if (
                self.auto_trade
                and snap["execution_gate"]["allowed"]
                and snap["signal"]["action"] != "flat"
                and snap.get("pulse_confirm")
            ):
                self.execute_signal(force=False)

    async def _loop(self) -> None:
        self._running = True
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                await loop.run_in_executor(None, self._tick_once)
            except Exception as e:
                log.exception("desk loop error: %s", e)
                store.log_event("error", {"message": str(e)})
            await asyncio.sleep(max(0.35, float(settings.tick_seconds)))

    def start_background(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task and not self._task.done():
            return
        self._task = loop.create_task(self._loop())

    def stop_background(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None


desk = TradingDesk()
