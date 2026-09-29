"""AURUM trading desk — scan → confluence → risk → execute loop."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from goldbot.brain.confluence import build_signal
from goldbot.config import settings
from goldbot.mt5.bridge import bridge
from goldbot.risk.manager import RiskManager
from goldbot.storage.state import store

log = logging.getLogger("aurum.desk")


class TradingDesk:
    def __init__(self) -> None:
        self.risk = RiskManager()
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._running = False
        self.last: dict[str, Any] = {}
        self.account = bridge.connect()
        store.log_event("boot", {"mode": self.account.mode, "detail": self.account.detail})

    @property
    def auto_trade(self) -> bool:
        return bool(store.get_kv("auto_trade", settings.auto_trade))

    def set_auto_trade(self, enabled: bool) -> None:
        store.set_kv("auto_trade", bool(enabled))
        store.log_event("auto_trade", {"enabled": bool(enabled)})

    def scan(self) -> dict:
        with self._lock:
            candles = bridge.fetch_candles()
            tick = bridge.tick()
            signal = build_signal(candles, spread_points=float(tick.get("spread_points") or 0))
            # refresh account soft
            if bridge.mode == "paper":
                self.account.balance = bridge.paper_balance
                self.account.equity = bridge.paper_equity
            else:
                self.account = bridge.connect()

            equity = self.account.equity or settings.paper_balance
            self.risk.roll_day(equity)
            allowed, reason = self.risk.allow_trade(equity, signal.action)
            lot = 0.0
            if signal.action != "flat":
                lot = self.risk.lot_size(equity, signal.entry, signal.stop)

            payload = {
                "symbol": settings.symbol,
                "timeframe": settings.timeframe,
                "tick": tick,
                "account": self.account.to_dict(),
                "signal": signal.to_dict(),
                "risk": self.risk.state.to_dict(),
                "execution_gate": {"allowed": allowed, "reason": reason, "lot": lot},
                "auto_trade": self.auto_trade,
                "candles_tail": [c.to_dict() for c in candles[-80:]],
            }
            self.last = payload
            store.log_event("scan", {"action": signal.action, "confluence": signal.confluence, "vetoes": signal.vetoes})
            return payload

    def execute_signal(self, force: bool = False) -> dict:
        snap = self.scan()
        sig = snap["signal"]
        gate = snap["execution_gate"]
        if sig["action"] == "flat":
            return {"ok": False, "error": "no_actionable_signal", "scan": snap}
        if not force and not gate["allowed"]:
            return {"ok": False, "error": gate["reason"], "scan": snap}
        if not force and not self.auto_trade:
            return {"ok": False, "error": "auto_trade_disabled", "scan": snap, "hint": "Enable auto-trade or call force execute."}

        lot = gate["lot"] or 0.01
        result = bridge.order_market(sig["action"], lot, sig["stop"], sig["take"], comment="AURUM-ELITE")
        if result.get("ok"):
            self.risk.register_open()
            trade_id = store.add_trade({**result, "status": "open", "meta": {"confluence": sig["confluence"], "narrative": sig["narrative"]}})
            # paper mark-to-model: instant unrealized ignore; simulate small slip cost
            if result.get("mode") == "paper":
                cost = abs(sig["entry"] - sig["stop"]) * lot * 100 * 0.02  # tiny friction model
                bridge.paper_equity -= cost
            store.log_event("trade_open", {"trade_id": trade_id, **result})
            return {"ok": True, "trade_id": trade_id, "result": result, "scan": self.scan()}
        store.log_event("trade_reject", result)
        return {"ok": False, "error": result.get("error") or "order_failed", "result": result, "scan": snap}

    async def _loop(self) -> None:
        self._running = True
        while self._running:
            try:
                snap = self.scan()
                if self.auto_trade and snap["execution_gate"]["allowed"] and snap["signal"]["action"] != "flat":
                    self.execute_signal(force=False)
            except Exception as e:
                log.exception("desk loop error: %s", e)
                store.log_event("error", {"message": str(e)})
            await asyncio.sleep(settings.loop_seconds)

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
