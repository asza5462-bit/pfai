"""
MT5 / FP Markets bridge.

- `paper` mode: works on Linux/Render with live gold quotes + simulated fills.
- `mt5` + MetaApi: real FP Markets execution from cloud (no Windows).
- `mt5` + cTrader Open API: real FP Markets/cTrader execution from the app (no Windows).
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
    ctrader_account_id: int | None = None
    execution: str = ""  # ctrader | metaapi | windows_bridge | mt5_linux | local_mt5 | paper
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
        from goldbot.mt5.metaapi_cloud import is_metaapi_account_id, normalize_account_id

        raw = str(account_id or "").strip()
        self.metaapi_account_id = normalize_account_id(raw) if is_metaapi_account_id(raw) else ""
        self.metaapi_region = (region or settings.metaapi_region or "new-york").strip()
        if self.metaapi_account_id:
            self.mode = "mt5"
            self.execution = "metaapi"
        elif raw:
            log.warning("refusing to bind invalid metaapi account id %r", raw)

    def bind_ctrader(self, account_id: int | str | None = None) -> None:
        from goldbot.mt5.ctrader_cloud import ctrader

        if account_id not in (None, "", 0, "0"):
            try:
                aid = int(account_id)
            except (TypeError, ValueError):
                log.warning("refusing invalid ctrader account id %r", account_id)
                return
            ctrader.select_account(aid)
            self.ctrader_account_id = aid
        else:
            ctrader.refresh()
            self.ctrader_account_id = ctrader.account_id
        if self.ctrader_account_id and ctrader.ready:
            self.mode = "mt5"
            self.execution = "ctrader"

    def connect(self) -> AccountSnapshot:
        # 0) cTrader Open API — in-app FP Markets/cTrader (no Windows; cTrader accounts only)
        if (
            self.mode == "mt5"
            and self.execution != "windows_bridge"
            and settings.prefer_ctrader
            and (self.execution == "ctrader" or self.ctrader_account_id)
        ):
            from goldbot.mt5.ctrader_cloud import ctrader

            ctrader.refresh()
            if ctrader.ready:
                snap = ctrader.snapshot()
                if snap.get("connected"):
                    self.execution = "ctrader"
                    self.ctrader_account_id = int(snap.get("account_id") or self.ctrader_account_id or 0) or None
                    return AccountSnapshot(
                        balance=float(snap["balance"]),
                        equity=float(snap["equity"]),
                        margin=float(snap["margin"]),
                        free_margin=float(snap["free_margin"]),
                        currency=str(snap.get("currency") or "USD"),
                        mode="mt5",
                        connected=True,
                        server=str(snap.get("server") or "cTrader"),
                        login=int(snap.get("login") or 0),
                        detail=str(snap.get("detail") or "cTrader Open API"),
                    )
                if self.execution == "ctrader":
                    return AccountSnapshot(
                        balance=0.0,
                        equity=0.0,
                        margin=0.0,
                        free_margin=0.0,
                        currency="USD",
                        mode="mt5",
                        connected=False,
                        server="cTrader",
                        login=int(self.ctrader_account_id or 0),
                        detail=str(snap.get("detail") or "بانتظار اتصال cTrader Open API"),
                    )

        # 1) MetaApi cloud — primary real path (skipped when user chose Windows agent)
        if (
            self.mode == "mt5"
            and self.execution not in {"windows_bridge", "ctrader"}
            and self.metaapi_account_id
            and settings.prefer_metaapi
        ):
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
                # Corrupt / deleted MetaApi id — drop so ensure_account can recreate
                if snap.get("stale") or snap.get("error") in {"E_BAD_ACCOUNT_ID", "E_NOT_FOUND", "NotFoundError"}:
                    log.warning("clearing stale metaapi_account_id=%s", self.metaapi_account_id)
                    self.metaapi_account_id = ""
                    self.execution = ""
                    return AccountSnapshot(
                        balance=0.0,
                        equity=0.0,
                        margin=0.0,
                        free_margin=0.0,
                        currency="USD",
                        mode="mt5",
                        connected=False,
                        server=settings.mt5_server or "FP Markets",
                        login=int(settings.mt5_login or 0),
                        detail=str(snap.get("detail") or "معرّف MetaApi تالف — أعد الربط الكامل"),
                    )
                # fall through to Linux executor if MetaApi not yet connected
                if not settings.prefer_mt5_linux:
                    return AccountSnapshot(
                        balance=0.0,
                        equity=0.0,
                        margin=0.0,
                        free_margin=0.0,
                        currency="USD",
                        mode="mt5",
                        connected=False,
                        server=settings.mt5_server or "FP Markets",
                        login=int(settings.mt5_login or 0),
                        detail=str(snap.get("detail") or "بانتظار اتصال MetaApi السحابي"),
                    )

        # 2) Linux Docker/Wine MT5 — real FP Markets without Windows OS
        if self.mode == "mt5" and settings.prefer_mt5_linux:
            from goldbot.mt5.mt5_linux import mt5_linux

            mt5_linux.refresh()
            if mt5_linux.configured:
                snap = mt5_linux.snapshot()
                if snap.get("connected"):
                    self.execution = "mt5_linux"
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
                        detail=str(snap.get("detail") or "MT5 Linux Docker"),
                    )
                if self.execution == "mt5_linux" or not self.metaapi_account_id:
                    return AccountSnapshot(
                        balance=0.0,
                        equity=0.0,
                        margin=0.0,
                        free_margin=0.0,
                        currency="USD",
                        mode="mt5",
                        connected=False,
                        server=settings.mt5_server or "FP Markets",
                        login=int(settings.mt5_login or 0),
                        detail=str(snap.get("detail") or "منفّذ Linux غير متصل — افتح VNC وسجّل FP Markets مرة واحدة"),
                    )

        # 3) MetaApi configured but account id not ready yet — never pretend Windows agent is required
        if self.mode == "mt5" and settings.prefer_metaapi:
            from goldbot.mt5.metaapi_cloud import metaapi

            if metaapi.configured and not self.metaapi_account_id:
                return AccountSnapshot(
                    balance=0.0,
                    equity=0.0,
                    margin=0.0,
                    free_margin=0.0,
                    currency="USD",
                    mode="mt5",
                    connected=False,
                    server=settings.mt5_server or "FP Markets",
                    login=int(settings.mt5_login or 0),
                    detail="توكن MetaApi جاهز — جاري إنشاء الطرفية السحابية على FP Markets (بدون Windows)",
                )

        # 4) Windows MT5 agent — explicit choice or fallback when MetaApi/Linux/cTrader not live
        if self.mode == "mt5" and self.remote_user_id and self.execution not in {"metaapi", "mt5_linux", "ctrader"}:
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
                    detail=st.get("detail") or "FP Markets via MT5 agent",
                )
            return AccountSnapshot(
                balance=float(acc.get("balance") or 0),
                equity=float(acc.get("equity") or 0),
                margin=0.0,
                free_margin=0.0,
                currency="USD",
                mode="mt5",
                connected=False,
                server=settings.mt5_server or "FP Markets",
                login=int(settings.mt5_login or 0),
                detail=st.get("detail") or "بانتظار اتصال السحابة بـ FP Markets",
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
            detail="Paper desk — سجّل دخول FP Markets من التطبيق للربط السحابي الحقيقي.",
        )

    def _connect_mt5(self) -> AccountSnapshot:
        """Local MetaTrader5 package path — never silently switch product mode to paper."""
        fail = AccountSnapshot(
            balance=0.0,
            equity=0.0,
            margin=0.0,
            free_margin=0.0,
            currency="USD",
            mode="mt5",
            connected=False,
            server=settings.mt5_server or "FP Markets",
            login=int(settings.mt5_login or 0),
            detail="",
        )
        try:
            import MetaTrader5 as mt5  # type: ignore
        except Exception as e:
            fail.detail = f"حزمة MetaTrader5 غير متاحة على السيرفر ({e}) — استخدم MetaApi السحابي"
            return fail

        kwargs = {}
        if settings.mt5_path:
            kwargs["path"] = settings.mt5_path
        if not mt5.initialize(**kwargs):
            fail.detail = f"mt5.initialize فشل: {mt5.last_error()}"
            return fail
        if settings.mt5_login and settings.mt5_password and settings.mt5_server:
            ok = mt5.login(settings.mt5_login, password=settings.mt5_password, server=settings.mt5_server)
            if not ok:
                mt5.shutdown()
                fail.detail = f"mt5.login فشل: {mt5.last_error()}"
                return fail
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
        # Live MetaApi path: broker OHLC only (never mix Yahoo/synth into live signals)
        if self.mode == "mt5" and self.metaapi_account_id and settings.prefer_metaapi:
            bars = self._fetch_metaapi(symbol, timeframe, count)
            if bars:
                return bars
            log.warning("metaapi candles empty — refusing paper fallback while live mode active")
            # Keep last cache briefly so desk doesn't stall hard
            if self._candle_cache and time.time() - self._candle_cache_ts < 120:
                return self._candle_cache[-count:] if len(self._candle_cache) > count else list(self._candle_cache)
            return []
        if self.mode == "mt5" and self._mt5 is not None:
            return self._fetch_mt5(symbol, timeframe, count)
        # Live mt5 mode: never mix Yahoo/synth into broker signals (cTrader/Windows/Linux)
        if self.mode == "mt5":
            if self._candle_cache and time.time() - self._candle_cache_ts < 120:
                return self._candle_cache[-count:] if len(self._candle_cache) > count else list(self._candle_cache)
            log.warning("live mt5 candles unavailable — refusing paper/Yahoo fallback")
            return []
        return self._fetch_paper(count)

    def _fetch_metaapi(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        from goldbot.mt5.metaapi_cloud import metaapi

        if not metaapi.configured or not self.metaapi_account_id:
            return []
        now = time.time()
        # Cache broker candles briefly — MetaApi historical is heavier than tick
        if (
            self._candle_cache
            and self._feed_source == "metaapi"
            and now - self._candle_cache_ts < 20
            and len(self._candle_cache) >= min(count, 50)
        ):
            return self._candle_cache[-count:] if len(self._candle_cache) > count else list(self._candle_cache)
        try:
            raw = metaapi.candles(
                self.metaapi_account_id,
                symbol,
                timeframe,
                count=count,
                region=self.metaapi_region or None,
            )
        except Exception as e:
            log.warning("metaapi candles fail: %s", e)
            return []
        out: list[Candle] = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            ts = r.get("time") or r.get("brokerTime") or r.get("timestamp")
            try:
                if isinstance(ts, str):
                    # ISO → unix
                    from datetime import datetime

                    t = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                else:
                    t = int(ts)
                    if t > 10_000_000_000:
                        t //= 1000
            except Exception:
                continue
            try:
                out.append(
                    Candle(
                        time=t,
                        open=float(r.get("open") or 0),
                        high=float(r.get("high") or 0),
                        low=float(r.get("low") or 0),
                        close=float(r.get("close") or 0),
                        volume=float(r.get("tickVolume") or r.get("volume") or r.get("realVolume") or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
        if out:
            out.sort(key=lambda c: c.time)
            self._last_price = out[-1].close
            self._candle_cache = out
            self._candle_cache_ts = now
            self._feed_source = "metaapi"
            self._seeded = True
        return out[-count:] if len(out) > count else out

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
            if self._candle_cache and time.time() - self._candle_cache_ts < 120:
                return self._candle_cache[-count:] if len(self._candle_cache) > count else list(self._candle_cache)
            return []
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
        if self.mode == "mt5" and self.execution == "ctrader" and settings.prefer_ctrader:
            from goldbot.mt5.ctrader_cloud import ctrader

            if ctrader.ready:
                try:
                    px = ctrader.symbol_price(settings.symbol)
                    bid = float(px.get("bid") or px.get("price") or 0)
                    ask = float(px.get("ask") or (bid + 0.2 if bid else 0))
                    if bid > 0:
                        self._last_price = bid
                        spread = (ask - bid) / 0.01 if ask >= bid else 20.0
                        return {
                            "bid": bid,
                            "ask": ask,
                            "spread_points": round(spread, 2),
                            "source": "ctrader",
                        }
                except Exception as e:
                    log.warning("ctrader tick fail: %s", e)
        if self.mode == "mt5" and self.execution != "ctrader" and self.metaapi_account_id and settings.prefer_metaapi:
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
        # cTrader Open API (in-app, no Windows) — when selected/ready
        if self.mode == "mt5" and settings.prefer_ctrader and (self.execution == "ctrader" or self.ctrader_account_id):
            from goldbot.mt5.ctrader_cloud import CTraderError, ctrader

            if ctrader.ready:
                try:
                    result = ctrader.order_market(
                        side,
                        float(lot),
                        float(sl),
                        float(tp),
                        symbol=settings.symbol,
                        comment=comment,
                    )
                    result["mode"] = "mt5"
                    result["execution"] = "ctrader"
                    if result.get("ok") or self.execution == "ctrader":
                        return result
                except CTraderError as e:
                    log.warning("ctrader order failed: %s", e)
                    if self.execution == "ctrader":
                        return {
                            "ok": False,
                            "mode": "mt5",
                            "execution": "ctrader",
                            "side": side,
                            "lot": lot,
                            "sl": sl,
                            "tp": tp,
                            "error": e.code or "ctrader",
                            "detail": str(e.message or e),
                        }

        # Primary: MetaApi cloud (no Windows)
        if self.mode == "mt5" and self.execution != "ctrader" and self.metaapi_account_id and settings.prefer_metaapi:
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
                if result.get("ok"):
                    return result
                log.warning("metaapi order failed: %s", result.get("error"))
                # Do not swallow broker rejects when MetaApi is the active path
                if self.execution == "metaapi" or not settings.prefer_mt5_linux:
                    return result

        # Secondary: Linux Docker MT5 (no Windows OS)
        if self.mode == "mt5" and settings.prefer_mt5_linux:
            from goldbot.mt5.mt5_linux import mt5_linux

            mt5_linux.refresh()
            if mt5_linux.configured:
                result = mt5_linux.order_market(
                    side, float(lot), float(sl), float(tp), symbol=settings.symbol, comment=comment
                )
                result["mode"] = "mt5"
                result["execution"] = "mt5_linux"
                if result.get("ok") or self.execution == "mt5_linux":
                    return result

        # Fallback: queue to Windows MT5 agent
        if self.mode == "mt5" and self.remote_user_id and self.execution not in {"metaapi", "mt5_linux", "ctrader"}:
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
        # CRITICAL: never silently paper-fill when user asked for live FP Markets/MT5
        if self.mode == "mt5":
            return {
                "ok": False,
                "mode": "mt5",
                "execution": self.execution or "none",
                "side": side,
                "lot": lot,
                "sl": sl,
                "tp": tp,
                "error": "no_live_executor",
                "detail": (
                    "لا يوجد منفّذ حقيقي متصل (cTrader/MetaApi/Linux). "
                    "لن يُنفَّذ أمر ورقي وهمي. أعد الربط السحابي أولاً."
                ),
            }
        # Explicit paper mode only
        tick = self.tick()
        price = tick["ask"] if side == "buy" else tick["bid"]
        return {
            "ok": True,
            "mode": "paper",
            "execution": "paper",
            "side": side,
            "lot": lot,
            "price": price,
            "sl": sl,
            "tp": tp,
            "ticket": int(time.time()),
            "comment": comment,
        }

    def is_live_execution(self) -> bool:
        """True only when a real broker path is bound (cTrader/MetaApi/Linux/local MT5)."""
        if self.mode != "mt5":
            return False
        if self.execution == "ctrader":
            from goldbot.mt5.ctrader_cloud import ctrader

            ctrader.refresh()
            return bool(ctrader.ready)
        if self.execution == "metaapi" and self.metaapi_account_id:
            from goldbot.mt5.metaapi_cloud import is_metaapi_account_id, metaapi

            if not (metaapi.configured and is_metaapi_account_id(self.metaapi_account_id)):
                return False
            # Soft connectivity gate: last connect/tick must not be long-stale disconnected
            try:
                from goldbot.storage.state import store

                prov = store.get_kv("metaapi_provision_state") or {}
                if isinstance(prov, dict) and prov.get("status") == "error":
                    return False
            except Exception:
                pass
            return True
        if self.execution == "mt5_linux":
            from goldbot.mt5.mt5_linux import mt5_linux

            mt5_linux.refresh()
            return bool(mt5_linux.configured)
        if self.execution == "windows_bridge" and self.remote_user_id:
            from goldbot.mt5.remote_hub import hub

            return bool(hub.is_online(self.remote_user_id))
        if self._mt5 is not None:
            return True
        return False

    def close_position(
        self,
        position_id: str | int,
        *,
        ticket: str | int | None = None,
        volume: float | None = None,
    ) -> dict:
        """Close a live position on the active executor. Never fakes paper closes for mt5 mode."""
        pid = position_id or ticket
        if self.mode == "mt5" and self.execution == "ctrader":
            from goldbot.mt5.ctrader_cloud import ctrader

            if ctrader.ready and pid not in (None, "", 0, "0"):
                result = ctrader.close_position(pid, volume=volume)
                result.setdefault("execution", "ctrader")
                result.setdefault("mode", "mt5")
                return result
            return {"ok": False, "error": "no_position_id", "execution": "ctrader", "mode": "mt5"}
        if self.mode == "mt5" and self.metaapi_account_id and self.execution == "metaapi":
            from goldbot.mt5.metaapi_cloud import metaapi

            if metaapi.configured and pid not in (None, "", 0, "0"):
                result = metaapi.close_position(
                    self.metaapi_account_id,
                    pid,
                    region=self.metaapi_region or None,
                    volume=volume,
                )
                result.setdefault("execution", "metaapi")
                result.setdefault("mode", "mt5")
                return result
            return {"ok": False, "error": "no_position_id", "execution": "metaapi", "mode": "mt5"}
        if self.mode == "mt5" and self.execution == "mt5_linux":
            from goldbot.mt5.mt5_linux import mt5_linux

            mt5_linux.refresh()
            if mt5_linux.configured and hasattr(mt5_linux, "close_position"):
                result = mt5_linux.close_position(pid)
                result.setdefault("execution", "mt5_linux")
                result.setdefault("mode", "mt5")
                return result
            return {"ok": False, "error": "linux_close_unsupported", "execution": "mt5_linux", "mode": "mt5"}
        if self.mode == "mt5" and self.execution == "windows_bridge" and self.remote_user_id:
            from goldbot.mt5.remote_hub import hub

            if pid in (None, "", 0, "0"):
                return {"ok": False, "error": "no_position_id", "execution": "windows_bridge", "mode": "mt5"}
            enq = hub.enqueue(
                self.remote_user_id,
                "close_position",
                {"position_id": pid, "ticket": ticket, "volume": volume},
            )
            if not enq.get("ok"):
                return {
                    "ok": False,
                    "error": enq.get("error"),
                    "detail": enq.get("detail"),
                    "execution": "windows_bridge",
                    "mode": "mt5",
                }
            result = hub.wait_result(int(enq["command_id"]), timeout=15.0)
            result.setdefault("execution", "windows_bridge")
            result.setdefault("mode", "mt5")
            return result
        if self.mode == "paper":
            return {"ok": True, "mode": "paper", "execution": "paper"}
        return {"ok": False, "error": "no_live_executor", "execution": self.execution or "none", "mode": self.mode}

    def modify_position_sl_tp(self, position_id: str | int, sl: float | None = None, tp: float | None = None) -> dict:
        if self.mode == "mt5" and self.metaapi_account_id and self.execution == "metaapi":
            from goldbot.mt5.metaapi_cloud import SUCCESS_CODES, SUCCESS_STRINGS, metaapi

            if not metaapi.configured or position_id in (None, "", 0, "0"):
                return {"ok": False, "error": "no_position_id"}
            payload: dict = {"actionType": "POSITION_MODIFY", "positionId": str(position_id)}
            if sl and float(sl) > 0:
                payload["stopLoss"] = float(sl)
            if tp and float(tp) > 0:
                payload["takeProfit"] = float(tp)
            try:
                resp = metaapi.trade(self.metaapi_account_id, payload, region=self.metaapi_region or None)
                numeric = resp.get("numericCode")
                string_code = str(resp.get("stringCode") or "")
                ok = (numeric in SUCCESS_CODES) or (string_code in SUCCESS_STRINGS)
                if not ok and isinstance(numeric, (int, float)):
                    ok = int(numeric) in SUCCESS_CODES
                return {
                    "ok": ok,
                    "raw": resp,
                    "execution": "metaapi",
                    "error": None if ok else (resp.get("message") or string_code or "modify_failed"),
                }
            except Exception as e:
                return {"ok": False, "error": str(e), "execution": "metaapi"}
        if self.mode == "paper":
            return {"ok": True, "mode": "paper"}
        return {"ok": False, "error": "modify_unsupported"}

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
