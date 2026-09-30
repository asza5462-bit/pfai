"""Capital preservation desk — losses cannot be zero; we minimize and halt."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from goldbot.config import settings


@dataclass
class RiskState:
    day: str = ""
    starting_equity: float = 0.0
    realized_pnl: float = 0.0
    open_trades: int = 0
    last_trade_ts: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    trades_today: int = 0

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "starting_equity": self.starting_equity,
            "realized_pnl": round(self.realized_pnl, 2),
            "open_trades": self.open_trades,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "trades_today": self.trades_today,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "note": "Zero permanent loss is impossible in markets. This desk caps damage and stands down.",
        }


@dataclass
class RiskManager:
    state: RiskState = field(default_factory=RiskState)

    def roll_day(self, equity: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day != today:
            self.state = RiskState(day=today, starting_equity=equity)

    def register_open(self) -> None:
        self.state.open_trades += 1
        self.state.trades_today += 1
        self.state.last_trade_ts = datetime.now(timezone.utc).timestamp()

    def register_close(self, pnl: float) -> None:
        self.state.open_trades = max(0, self.state.open_trades - 1)
        self.state.realized_pnl += pnl
        self._check_halt()

    def _check_halt(self) -> None:
        if self.state.starting_equity <= 0:
            return
        dd = -self.state.realized_pnl / self.state.starting_equity * 100
        if dd >= settings.max_daily_loss_pct:
            self.state.halted = True
            self.state.halt_reason = f"daily_loss_cap_{settings.max_daily_loss_pct}%"

    def lot_size(self, equity: float, entry: float, stop: float, contract_size: float = 100.0) -> float:
        """XAUUSD: 1.0 lot ≈ 100 oz; risk money / (stop distance * contract).

        Returns 0.0 when computed size is below broker min (0.01) — never oversize tiny accounts.
        """
        risk_money = equity * (settings.risk_per_trade_pct / 100.0)
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or equity <= 0 or risk_money <= 0:
            return 0.0
        # For gold CFDs many brokers: PnL ≈ move_in_price * lot * 100
        raw = risk_money / (stop_dist * contract_size)
        lot = round(max(0.0, min(5.0, raw)), 2)
        if lot < 0.01:
            return 0.0
        return lot

    def allow_trade(self, equity: float, signal_action: str) -> tuple[bool, str]:
        self.roll_day(equity)
        if signal_action == "flat":
            return False, "no_signal"
        if self.state.halted:
            return False, self.state.halt_reason or "halted"
        if self.state.open_trades >= settings.max_open_trades:
            return False, "max_open_trades"
        now = datetime.now(timezone.utc).timestamp()
        if self.state.last_trade_ts and now - self.state.last_trade_ts < settings.cooldown_seconds:
            return False, "cooldown"
        return True, "ok"

    def reset_day(self, equity: float, note: str = "manual_reset") -> dict:
        """Owner-triggered paper reset — does not erase trade history."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        open_n = self.state.open_trades
        self.state = RiskState(day=today, starting_equity=equity, open_trades=open_n)
        return {"ok": True, "note": note, "risk": self.state.to_dict()}
