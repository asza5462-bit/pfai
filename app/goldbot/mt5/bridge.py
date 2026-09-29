"""
MT5 / Exness bridge.

- `paper` mode: works on Linux/Render with live gold quotes (Yahoo) + simulated fills.
- `mt5` mode: requires Windows host with MetaTrader5 terminal + Exness account.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.request import urlopen, Request
import json

from goldbot.config import settings
from goldbot.market.candles import Candle

log = logging.getLogger("aurum.mt5")


@dataclass
class AccountSnapshot:
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str
    mode: str
    connected: bool
    server: str
    login: int
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "margin": round(self.margin, 2),
            "free_margin": round(self.free_margin, 2),
            "currency": self.currency,
            "mode": self.mode,
            "connected": self.connected,
            "server": self.server,
            "login": self.login,
            "detail": self.detail,
        }


@dataclass
class Bridge:
    mode: str = field(default_factory=lambda: settings.mode)
    paper_balance: float = field(default_factory=lambda: settings.paper_balance)
    paper_equity: float = field(default_factory=lambda: settings.paper_balance)
    _mt5: Any = None
    _last_price: float = 2350.0
    _seeded: bool = False

    def connect(self) -> AccountSnapshot:
        if self.mode == "mt5":
            return self._connect_mt5()
        return AccountSnapshot(
            balance=self.paper_balance,
            equity=self.paper_equity,
            margin=0.0,
            free_margin=self.paper_equity,
            currency="USD",
            mode="paper",
            connected=True,
            server="AURUM-PAPER",
            login=0,
            detail="Paper desk — set AURUM_MODE=mt5 + MT5_* on Windows VPS for Exness live/demo.",
        )

    def _connect_mt5(self) -> AccountSnapshot:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except Exception as e:
            self.mode = "paper"
            snap = self.connect()
            snap.detail = f"MetaTrader5 package unavailable ({e}); fell back to paper."
            return snap

        kwargs = {}
        if settings.mt5_path:
            kwargs["path"] = settings.mt5_path
        if not mt5.initialize(**kwargs):
            self.mode = "paper"
            snap = self.connect()
            snap.detail = f"mt5.initialize failed: {mt5.last_error()}; paper fallback."
            return snap
        if settings.mt5_login and settings.mt5_password and settings.mt5_server:
            ok = mt5.login(settings.mt5_login, password=settings.mt5_password, server=settings.mt5_server)
            if not ok:
                self.mode = "paper"
                mt5.shutdown()
                snap = self.connect()
                snap.detail = f"mt5.login failed: {mt5.last_error()}; paper fallback."
                return snap
        self._mt5 = mt5
        info = mt5.account_info()
        if info is None:
            return AccountSnapshot(0, 0, 0, 0, "USD", "mt5", False, settings.mt5_server, settings.mt5_login, "no account_info")
        return AccountSnapshot(
            balance=float(info.balance),
            equity=float(info.equity),
            margin=float(info.margin),
            free_margin=float(info.margin_free),
            currency=str(info.currency),
            mode="mt5",
            connected=True,
            server=str(info.server),
            login=int(info.login),
            detail="Connected to MetaTrader 5 / broker terminal.",
        )

    def shutdown(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
            self._mt5 = None

    def fetch_candles(self, symbol: str | None = None, timeframe: str | None = None, count: int = 200) -> list[Candle]:
        symbol = symbol or settings.symbol
        timeframe = (timeframe or settings.timeframe).upper()
        if self.mode == "mt5" and self._mt5 is not None:
            return self._fetch_mt5(symbol, timeframe, count)
        return self._fetch_paper(count)

    def _tf_mt5(self, timeframe: str):
        mt5 = self._mt5
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        return mapping.get(timeframe, mt5.TIMEFRAME_M15)

    def _fetch_mt5(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        rates = self._mt5.copy_rates_from_pos(symbol, self._tf_mt5(timeframe), 0, count)
        if rates is None:
            log.warning("mt5 rates empty: %s", self._mt5.last_error())
            return self._fetch_paper(count)
        out = []
        for r in rates:
            out.append(
                Candle(
                    time=int(r["time"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                )
            )
        if out:
            self._last_price = out[-1].close
        return out

    def _yahoo_chart(self, interval: str = "15m", range_: str = "5d") -> list[Candle] | None:
        """Live gold OHLC proxy (GC futures / XAU) when MT5 is unavailable."""
        urls = [
            f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={range_}",
            f"https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval={interval}&range={range_}",
        ]
        for url in urls:
            try:
                req = Request(url, headers={"User-Agent": "AURUM/1.0"})
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                result = data["chart"]["result"][0]
                ts = result.get("timestamp") or []
                quote = (result.get("indicators") or {}).get("quote") or [{}]
                q = quote[0]
                opens, highs, lows, closes = q.get("open") or [], q.get("high") or [], q.get("low") or [], q.get("close") or []
                vols = q.get("volume") or []
                out: list[Candle] = []
                for i, t in enumerate(ts):
                    o, h, l, c = (
                        opens[i] if i < len(opens) else None,
                        highs[i] if i < len(highs) else None,
                        lows[i] if i < len(lows) else None,
                        closes[i] if i < len(closes) else None,
                    )
                    if None in (o, h, l, c):
                        continue
                    vol = float(vols[i] or 0) if i < len(vols) else 0.0
                    out.append(Candle(time=int(t), open=float(o), high=float(h), low=float(l), close=float(c), volume=vol))
                if out:
                    self._last_price = out[-1].close
                    return out
            except Exception as e:
                log.warning("yahoo chart fail %s: %s", url, e)
        return None

    def _yahoo_last(self) -> float | None:
        bars = self._yahoo_chart()
        if bars:
            return bars[-1].close
        return None

    def _fetch_paper(self, count: int) -> list[Candle]:
        tf = (settings.timeframe or "M15").upper()
        interval = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m", "H4": "60m", "D1": "1d"}.get(tf, "15m")
        range_ = "5d" if interval.endswith("m") else "3mo"
        live = self._yahoo_chart(interval=interval, range_=range_)
        if live:
            self._seeded = True
            return live[-count:] if len(live) > count else live

        # Offline fallback — synthetic walk only if market feed unreachable
        price = self._last_price
        now = int(time.time()) // 900 * 900
        candles: list[Candle] = []
        x = price * 0.985
        for i in range(count):
            t = now - (count - i) * 900
            wave = math.sin(i / 9.0) * price * 0.0018 + math.cos(i / 21.0) * price * 0.0011
            o = x
            c = x + wave * 0.15 + (price - x) * 0.03
            h = max(o, c) + abs(wave) * 0.25
            l = min(o, c) - abs(wave) * 0.25
            vol = 800 + abs(wave) * 50 + (1200 if i % 17 == 0 else 0)
            candles.append(Candle(time=t, open=o, high=h, low=l, close=c, volume=vol))
            x = c
        if candles:
            candles[-1].close = price
            candles[-1].high = max(candles[-1].high, price)
            candles[-1].low = min(candles[-1].low, price)
        self._seeded = True
        return candles

    def tick(self) -> dict:
        if self.mode == "mt5" and self._mt5 is not None:
            tick = self._mt5.symbol_info_tick(settings.symbol)
            if tick is None:
                return {"bid": self._last_price, "ask": self._last_price + 0.2, "spread_points": 20.0, "source": "stale"}
            spread = (tick.ask - tick.bid) / 0.01  # points approx for gold
            self._last_price = float(tick.bid)
            return {
                "bid": float(tick.bid),
                "ask": float(tick.ask),
                "spread_points": round(spread, 2),
                "source": "mt5",
            }
        last = self._yahoo_last() or self._last_price
        self._last_price = last
        spread = 2.5  # typical demo proxy
        return {"bid": last, "ask": last + 0.25, "spread_points": spread * 10, "source": "paper_yahoo"}

    def order_market(self, side: str, lot: float, sl: float, tp: float, comment: str = "AURUM") -> dict:
        if self.mode == "mt5" and self._mt5 is not None:
            return self._order_mt5(side, lot, sl, tp, comment)
        # paper fill at bid/ask
        tick = self.tick()
        price = tick["ask"] if side == "buy" else tick["bid"]
        return {
            "ok": True,
            "mode": "paper",
            "side": side,
            "lot": lot,
            "price": price,
            "sl": sl,
            "tp": tp,
            "ticket": int(time.time()),
            "comment": comment,
        }

    def _order_mt5(self, side: str, lot: float, sl: float, tp: float, comment: str) -> dict:
        mt5 = self._mt5
        symbol = settings.symbol
        info = mt5.symbol_info(symbol)
        if info is None:
            if not mt5.symbol_select(symbol, True):
                return {"ok": False, "error": f"symbol_select failed {mt5.last_error()}"}
            info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == "buy" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 40,
            "magic": 908070,
            "comment": comment[:30],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return {"ok": False, "error": str(mt5.last_error())}
        ok = result.retcode == mt5.TRADE_RETCODE_DONE
        return {
            "ok": ok,
            "mode": "mt5",
            "retcode": int(result.retcode),
            "ticket": int(getattr(result, "order", 0) or 0),
            "price": float(getattr(result, "price", price) or price),
            "side": side,
            "lot": lot,
            "sl": sl,
            "tp": tp,
            "comment": comment,
            "error": None if ok else str(result.comment),
        }


bridge = Bridge()
