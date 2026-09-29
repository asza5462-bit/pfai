"""
MT5 / Exness bridge.

- `paper` mode: works on Linux/Render with live gold quotes + simulated fills.
- `mt5` + MetaApi: real Exness execution from cloud (no Windows).
- Legacy Windows agent hub remains as optional fallback.
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
    remote_user_id: int | None = None
    metaapi_account_id: str = ""
    metaapi_region: str = ""
    execution: str = ""  # metaapi | windows_bridge | local_mt5 | paper
    _mt5: Any = None
    _last_price: float = 0.0
    _seeded: bool = False
    _candle_cache: list = field(default_factory=list)
    _candle_cache_ts: float = 0.0
    _spot_cache_ts: float = 0.0
    _feed_source: str = "init"
    _cache_ttl: float = 55.0
    _yahoo_backoff_until: float = 0.0
    _yahoo_ok_until: float = 0.0

    def bind_remote_user(self, user_id: int | None) -> None:
        self.remote_user_id = int(user_id) if user_id else None
        if self.remote_user_id:
            self.mode = "mt5"

    def bind_metaapi(self, account_id: str, region: str | None = None) -> None:
        self.metaapi_account_id = str(account_id or "").strip()
        self.metaapi_region = (region or settings.metaapi_region or "new-york").strip()
        if self.metaapi_account_id:
            self.mode = "mt5"
            self.execution = "metaapi"

    def connect(self) -> AccountSnapshot:
        # 1) MetaApi cloud — primary real path (no Windows)
        if self.mode == "mt5" and self.metaapi_account_id and settings.prefer_metaapi:
            from goldbot.mt5.metaapi_cloud import metaapi

            if metaapi.configured:
                snap = metaapi.snapshot(self.metaapi_account_id, region=self.metaapi_region or None)
                if snap.get("connected"):
                    self.execution = "metaapi"
                    return AccountSnapshot(
                        balance=float(snap["balance"]),
                        equity=float(snap["equity"]),
                        margin=float(snap["margin"]),
                        free_margin=float(snap["free_margin"]),
                        currency=str(snap.get("currency") or "USD"),
                        mode="mt5",
                        connected=True,
                        server=str(snap.get("server") or settings.mt5_server),
                        login=int(snap.get("login") or settings.mt5_login or 0),
                        detail=str(snap.get("detail") or "MetaApi cloud"),
                    )
                return AccountSnapshot(
                    balance=0.0,
                    equity=0.0,
                    margin=0.0,
                    free_margin=0.0,
                    currency="USD",
                    mode="mt5",
                    connected=False,
                    server=settings.mt5_server or "Exness",
                    login=int(settings.mt5_login or 0),
                    detail=str(snap.get("detail") or "بانتظار اتصال MetaApi السحابي"),
                )

        # 2) Legacy Windows agent hub
        if self.mode == "mt5" and self.remote_user_id and self.execution != "metaapi":
            from goldbot.mt5.remote_hub import hub

            st = hub.status_for_user(self.remote_user_id)
            acc = st.get("account") or {}
            if st.get("online") and acc:
                self.execution = "windows_bridge"
                return AccountSnapshot(
                    balance=float(acc.get("balance") or 0),
                    equity=float(acc.get("equity") or 0),
                    margin=float(acc.get("margin") or 0),
                    free_margin=float(acc.get("free_margin") or 0),
                    currency=str(acc.get("currency") or "USD"),
                    mode="mt5",
                    connected=True,
                    server=str(acc.get("server") or settings.mt5_server),
                    login=int(acc.get("login") or settings.mt5_login or 0),
                    detail=st.get("detail") or "Exness via MT5 agent",
                )
            # If MetaApi id is set but not yet connected, prefer that messaging
            if self.metaapi_account_id:
                return AccountSnapshot(
                    balance=float(acc.get("balance") or 0),
                    equity=float(acc.get("equity") or 0),
                    margin=0.0,
                    free_margin=0.0,
                    currency="USD",
                    mode="mt5",
                    connected=False,
                    server=settings.mt5_server or "Exness",
                    login=int(settings.mt5_login or 0),
                    detail="حساب MetaApi قيد الربط — بدون Windows",
                )
            return AccountSnapshot(
                balance=float(acc.get("balance") or 0),
                equity=float(acc.get("equity") or 0),
                margin=0.0,
                free_margin=0.0,
                currency="USD",
                mode="mt5",
                connected=False,
                server=settings.mt5_server or "Exness",
                login=int(settings.mt5_login or 0),
                detail=st.get("detail") or "بانتظار اتصال السحابة بـ Exness",
            )
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
            detail="Paper desk — سجّل دخول Exness من التطبيق للربط السحابي الحقيقي.",
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

    def _http_json(self, url: str, timeout: float = 10.0) -> dict | list | None:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 AURUM/1.1"})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            log.warning("feed fail %s: %s", url, e)
            return None

    def _spot_gold_api(self) -> float | None:
        data = self._http_json("https://api.gold-api.com/price/XAU", timeout=8)
        if isinstance(data, dict) and data.get("price"):
            px = float(data["price"])
            self._last_price = px
            self._feed_source = "gold_api"
            self._spot_cache_ts = time.time()
            return px
        return None

    def _yahoo_chart(self, interval: str = "15m", range_: str = "5d") -> list[Candle] | None:
        """OHLC proxy with long backoff after 429 — gold-api is primary on Render."""
        now = time.time()
        if now < self._yahoo_backoff_until:
            return None
        urls = [
            f"https://query2.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={range_}",
        ]
        for url in urls:
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0 AURUM/1.1"})
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as e:
                msg = str(e)
                # Back off hard on rate limits
                if "429" in msg or "Too Many" in msg:
                    self._yahoo_backoff_until = now + 900
                    log.warning("yahoo backoff 15m after rate limit: %s", e)
                else:
                    self._yahoo_backoff_until = now + 120
                    log.warning("yahoo feed fail: %s", e)
                continue
            try:
                result = data["chart"]["result"][0]
                ts = result.get("timestamp") or []
                q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
                out: list[Candle] = []
                for i, t in enumerate(ts):
                    o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                    if None in (o, h, l, c):
                        continue
                    vol = float((q.get("volume") or [0])[i] or 0)
                    out.append(Candle(time=int(t), open=float(o), high=float(h), low=float(l), close=float(c), volume=vol))
                if out:
                    self._last_price = out[-1].close
                    self._feed_source = "yahoo_ohlc"
                    self._yahoo_ok_until = now + 600
                    return out
            except Exception as e:
                log.warning("yahoo parse fail: %s", e)
        return None

    def _synthetic_around(self, price: float, count: int) -> list[Candle]:
        now = int(time.time()) // 900 * 900
        candles: list[Candle] = []
        x = price * 0.992
        for i in range(count):
            t = now - (count - i) * 900
            wave = math.sin(i / 7.5) * price * 0.0015 + math.cos(i / 17.0) * price * 0.0009
            o = x
            c = x + wave * 0.2 + (price - x) * 0.04
            h = max(o, c) + abs(wave) * 0.3
            l = min(o, c) - abs(wave) * 0.3
            vol = 900 + abs(wave) * 40 + (1500 if i % 13 == 0 else 0)
            candles.append(Candle(time=t, open=o, high=h, low=l, close=c, volume=vol))
            x = c
        if candles:
            candles[-1].close = price
            candles[-1].high = max(candles[-1].high, price)
            candles[-1].low = min(candles[-1].low, price)
        return candles

    def _fetch_paper(self, count: int) -> list[Candle]:
        now = time.time()
        spot = self._cached_spot() or self._spot_gold_api() or self._last_price

        if self._candle_cache and now - self._candle_cache_ts < self._cache_ttl:
            bars = list(self._candle_cache)
            if spot and bars:
                bars[-1] = Candle(
                    time=bars[-1].time,
                    open=bars[-1].open,
                    high=max(bars[-1].high, spot),
                    low=min(bars[-1].low, spot),
                    close=spot,
                    volume=bars[-1].volume + 1,
                )
                self._candle_cache = bars
            return bars[-count:] if len(bars) > count else bars

        # Prefer reliable spot-based structure; try Yahoo only when not in backoff.
        live = None
        if now >= self._yahoo_backoff_until:
            tf = (settings.timeframe or "M15").upper()
            interval = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m", "H4": "60m", "D1": "1d"}.get(tf, "15m")
            live = self._yahoo_chart(interval=interval, range_="5d")
        if live:
            if spot:
                live[-1] = Candle(
                    time=live[-1].time,
                    open=live[-1].open,
                    high=max(live[-1].high, spot),
                    low=min(live[-1].low, spot),
                    close=spot,
                    volume=live[-1].volume,
                )
            self._candle_cache = live
            self._candle_cache_ts = now
            self._seeded = True
            return live[-count:] if len(live) > count else live

        # Primary Render path: gold-api spot + structure scaffold (updated live each scan)
        spot = spot or 2650.0
        self._last_price = spot
        if self._candle_cache and self._feed_source.startswith("gold_api"):
            # Evolve scaffold with fresh spot instead of regenerating random walk every TTL.
            bars = list(self._candle_cache)
            last = bars[-1]
            bucket = int(now) // 900 * 900
            if last.time < bucket:
                bars.append(Candle(time=bucket, open=spot, high=spot, low=spot, close=spot, volume=1))
                if len(bars) > 240:
                    bars = bars[-240:]
            else:
                bars[-1] = Candle(
                    time=last.time,
                    open=last.open,
                    high=max(last.high, spot),
                    low=min(last.low, spot),
                    close=spot,
                    volume=last.volume + 1,
                )
            self._candle_cache = bars
            self._candle_cache_ts = now
            self._feed_source = "gold_api_live"
            self._seeded = True
            return bars[-count:] if len(bars) > count else bars

        bars = self._synthetic_around(spot, max(count, 120))
        self._candle_cache = bars
        self._candle_cache_ts = now
        self._feed_source = "gold_api_synth"
        self._seeded = True
        return bars[-count:] if len(bars) > count else bars

    def _cached_spot(self) -> float | None:
        now = time.time()
        # Tight cache for sub-second desk; still protects gold-api from spam
        if self._last_price and now - self._spot_cache_ts < 3:
            return self._last_price
        return self._spot_gold_api() or (self._last_price or None)

    def tick(self) -> dict:
        if self.mode == "mt5" and self.metaapi_account_id and settings.prefer_metaapi:
            from goldbot.mt5.metaapi_cloud import metaapi

            if metaapi.configured:
                try:
                    px = metaapi.symbol_price(self.metaapi_account_id, settings.symbol, region=self.metaapi_region or None)
                    bid = float(px.get("bid") or px.get("price") or 0)
                    ask = float(px.get("ask") or (bid + 0.2 if bid else 0))
                    if bid > 0:
                        self._last_price = bid
                        spread = (ask - bid) / 0.01 if ask >= bid else 20.0
                        return {
                            "bid": bid,
                            "ask": ask,
                            "spread_points": round(spread, 2),
                            "source": "metaapi",
                        }
                except Exception as e:
                    log.warning("metaapi tick fail: %s", e)
        if self.mode == "mt5" and self._mt5 is not None:
            tick = self._mt5.symbol_info_tick(settings.symbol)
            if tick is None:
                return {"bid": self._last_price, "ask": self._last_price + 0.2, "spread_points": 20.0, "source": "stale"}
            spread = (tick.ask - tick.bid) / 0.01
            self._last_price = float(tick.bid)
            return {
                "bid": float(tick.bid),
                "ask": float(tick.ask),
                "spread_points": round(spread, 2),
                "source": "mt5",
            }
        last = self._cached_spot() or self._last_price
        if not last:
            # ensure candles path fills price
            self.fetch_candles(count=30)
            last = self._last_price
        self._last_price = last
        return {
            "bid": float(last),
            "ask": float(last) + 0.25,
            "spread_points": 25.0,
            "source": self._feed_source or "paper",
        }

    def order_market(self, side: str, lot: float, sl: float, tp: float, comment: str = "AURUM") -> dict:
        # Primary: MetaApi cloud (no Windows)
        if self.mode == "mt5" and self.metaapi_account_id and settings.prefer_metaapi:
            from goldbot.mt5.metaapi_cloud import metaapi

            if metaapi.configured:
                result = metaapi.order_market(
                    self.metaapi_account_id,
                    side,
                    float(lot),
                    float(sl),
                    float(tp),
                    symbol=settings.symbol,
                    comment=comment,
                    region=self.metaapi_region or None,
                )
                result.setdefault("mode", "mt5")
                result["execution"] = "metaapi"
                return result

        # Fallback: queue to Windows MT5 agent
        if self.mode == "mt5" and self.remote_user_id and self.execution != "metaapi":
            from goldbot.mt5.remote_hub import hub

            enq = hub.enqueue(
                self.remote_user_id,
                "order_market",
                {
                    "side": side,
                    "lot": float(lot),
                    "sl": float(sl),
                    "tp": float(tp),
                    "symbol": settings.symbol,
                    "comment": comment,
                },
            )
            if not enq.get("ok"):
                return {"ok": False, "error": enq.get("error"), "detail": enq.get("detail"), "mode": "mt5"}
            result = hub.wait_result(int(enq["command_id"]), timeout=15.0)
            result.setdefault("mode", "mt5")
            result.setdefault("side", side)
            result.setdefault("lot", lot)
            result.setdefault("sl", sl)
            result.setdefault("tp", tp)
            result["execution"] = "windows_bridge"
            return result
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
