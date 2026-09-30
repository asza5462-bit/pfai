"""
cTrader Open API connector — real FP Markets/cTrader execution from AURUM (no Windows).

Uses WebSocket JSON protocol (wss://live|demo.ctraderapi.com:5036).
Requires a Spotware Open API app (clientId/secret) + user OAuth access token.
Only works if the FP Markets account is a **cTrader** account (not MT5-only).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("aurum.ctrader")

# Official payload types (Spotware Open API)
PT_APP_AUTH_REQ = 2100
PT_APP_AUTH_RES = 2101
PT_ACCOUNT_AUTH_REQ = 2102
PT_ACCOUNT_AUTH_RES = 2103
PT_NEW_ORDER_REQ = 2106
PT_AMEND_POSITION_SLTP_REQ = 2110
PT_CLOSE_POSITION_REQ = 2111
PT_SYMBOLS_LIST_REQ = 2114
PT_SYMBOLS_LIST_RES = 2115
PT_TRADER_REQ = 2121
PT_TRADER_RES = 2122
PT_RECONCILE_REQ = 2124
PT_RECONCILE_RES = 2125
PT_EXECUTION_EVENT = 2126
PT_SUBSCRIBE_SPOTS_REQ = 2127
PT_SUBSCRIBE_SPOTS_RES = 2128
PT_SPOT_EVENT = 2131  # ProtoOASpotEvent (legacy docs sometimes cited 2120)
PT_GET_TRENDBARS_REQ = 2137
PT_GET_TRENDBARS_RES = 2138
PT_ERROR_RES = 2142
PT_GET_ACCOUNTS_REQ = 2149
PT_GET_ACCOUNTS_RES = 2150
PT_HEARTBEAT = 51

ORDER_TYPE_MARKET = 1
TRADE_SIDE_BUY = 1
TRADE_SIDE_SELL = 2
EXEC_TYPE_FILLED = 2
EXEC_TYPE_PARTIAL_FILL = 9

# ProtoOATrendbarPeriod
PERIOD_MAP = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M10": 6,
    "M15": 7,
    "M30": 8,
    "H1": 9,
    "H4": 10,
    "H12": 11,
    "D1": 12,
    "W1": 13,
    "MN1": 14,
}

PRICE_SCALE = 100_000.0


def _decode_price(raw: Any) -> float:
    """Decode Spotware absolute/delta prices (often 1/100000 units)."""
    try:
        x = float(raw or 0)
    except (TypeError, ValueError):
        return 0.0
    if x == 0:
        return 0.0
    # Encoded absolute prices for gold/FX are huge integers
    if abs(x) >= 50_000:
        return x / PRICE_SCALE
    return x


def _trendbar_ohlc(bar: dict) -> tuple[float, float, float, float]:
    low_raw = float(bar.get("low") or 0)
    o = (low_raw + float(bar.get("deltaOpen") or 0)) / PRICE_SCALE
    h = (low_raw + float(bar.get("deltaHigh") or 0)) / PRICE_SCALE
    c = (low_raw + float(bar.get("deltaClose") or 0)) / PRICE_SCALE
    low = low_raw / PRICE_SCALE
    return o, h, low, c

AUTH_URI = "https://connect.spotware.com/apps/auth"
TOKEN_URI = "https://connect.spotware.com/apps/token"
WS_LIVE = "wss://live.ctraderapi.com:5036"
WS_DEMO = "wss://demo.ctraderapi.com:5036"


class CTraderError(Exception):
    def __init__(self, message: str, *, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


def arabic_ctrader_error(exc: CTraderError | Exception) -> str:
    msg = str(getattr(exc, "message", None) or exc)
    code = str(getattr(exc, "code", "") or "")
    low = msg.lower()
    if code == "NO_APP" or "client" in low and "secret" in low:
        return (
            "أضف CTRADER_CLIENT_ID و CTRADER_CLIENT_SECRET من "
            "https://openapi.ctrader.com ثم أعد المحاولة."
        )
    if code == "NO_TOKEN" or "access token" in low or "unauthorized" in low:
        return "يلزم تفويض cTrader — اضغط «تفويض cTrader» وأكمل تسجيل الدخول بحساب FP Markets."
    if code == "NO_ACCOUNT" or "account" in low and "select" in low:
        return "اختر حساب FP Markets cTrader من القائمة بعد التفويض."
    if code == "WRONG_BROKER" or "not fp markets" in low or "wrong broker" in low:
        return (
            "هذا الحساب ليس لدى وسيط FP Markets. "
            "AURUM مربوط بـ FP Markets فقط — افتح حساب cTrader من بوابة FP Markets ثم أعد التفويض."
        )
    if "mt5" in low or "not a ctrader" in low:
        return "هذا الحساب MT5 فقط — يلزم حساب FP Markets على منصة cTrader."
    if "timeout" in low or code == "TIMEOUT":
        return "انتهت مهلة الاتصال بـ cTrader — أعد المحاولة."
    if "websocket" in low or code == "NETWORK":
        return "تعذّر فتح اتصال cTrader WebSocket — تحقق من الشبكة/الخطة."
    return f"تعذّر ربط cTrader / FP Markets: {msg}"


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _http_form(url: str, data: dict, timeout: float = 30.0) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"message": raw or str(e)}
        raise CTraderError(
            payload.get("error_description") or payload.get("error") or f"HTTP {e.code}",
            code=str(payload.get("error") or e.code),
            details=payload,
        ) from e
    except urllib.error.URLError as e:
        raise CTraderError(f"network: {e.reason}", code="NETWORK") from e


def _load_kv() -> dict:
    try:
        from goldbot.storage.state import store

        row = store.get_kv("ctrader_auth") or {}
        return row if isinstance(row, dict) else {}
    except Exception:
        return {}


def _save_kv(patch: dict) -> dict:
    cur = _load_kv()
    cur.update({k: v for k, v in patch.items() if v is not None})
    try:
        from goldbot.storage.state import store

        store.set_kv("ctrader_auth", cur)
    except Exception as e:
        log.warning("ctrader kv save: %s", e)
    return cur


class CTraderSession:
    """Short-lived authenticated WebSocket session (sync)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
        account_id: int | None = None,
        *,
        live: bool = True,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.account_id = int(account_id) if account_id else None
        self.live = live
        self._ws = None
        self._lock = threading.RLock()
        self._pending: dict[str, dict] = {}
        self._inbox: list[dict] = []
        self._recv_thread: threading.Thread | None = None
        self._stop = False
        self._app_ok = False
        self._account_ok = False
        self._symbols: dict[str, dict] = {}
        self._last_spots: dict[int, dict] = {}

    @property
    def ws_url(self) -> str:
        return WS_LIVE if self.live else WS_DEMO

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as e:
            raise CTraderError("websocket-client غير مثبت", code="NO_WS") from e
        self._stop = False
        self._ws = websocket.create_connection(self.ws_url, timeout=20, enable_multithread=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, name="ctrader-ws", daemon=True)
        self._recv_thread.start()
        self._rpc(PT_APP_AUTH_REQ, {"clientId": self.client_id, "clientSecret": self.client_secret}, expect={PT_APP_AUTH_RES})
        self._app_ok = True
        if self.account_id:
            self.authorize_account(self.account_id)

    def close(self) -> None:
        self._stop = True
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        self._app_ok = False
        self._account_ok = False

    def _recv_loop(self) -> None:
        while not self._stop and self._ws:
            try:
                raw = self._ws.recv()
            except Exception:
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            ptype = int(msg.get("payloadType") or 0)
            if ptype == PT_HEARTBEAT:
                try:
                    self._ws.send(json.dumps({"payloadType": PT_HEARTBEAT, "payload": {}}))
                except Exception:
                    pass
                continue
            if ptype in {PT_SPOT_EVENT, 2120}:  # 2120 = legacy mislabel tolerance
                payload = msg.get("payload") or {}
                sid = int(payload.get("symbolId") or 0)
                if sid:
                    # Normalize bid/ask to human prices for the desk
                    norm = dict(payload)
                    if "bid" in payload:
                        norm["bid"] = _decode_price(payload.get("bid"))
                    if "ask" in payload:
                        norm["ask"] = _decode_price(payload.get("ask"))
                    self._last_spots[sid] = norm
                continue
            mid = str(msg.get("clientMsgId") or "")
            with self._lock:
                if mid and mid in self._pending:
                    self._pending[mid]["response"] = msg
                    self._pending[mid]["event"].set()
                else:
                    self._inbox.append(msg)

    def _rpc(self, payload_type: int, payload: dict, *, expect: set[int], timeout: float = 20.0) -> dict:
        if not self._ws:
            raise CTraderError("غير متصل", code="NOT_CONNECTED")
        mid = secrets.token_hex(8)
        event = threading.Event()
        with self._lock:
            self._pending[mid] = {"event": event, "response": None}
        try:
            self._ws.send(
                json.dumps(
                    {
                        "clientMsgId": mid,
                        "payloadType": payload_type,
                        "payload": payload,
                    }
                )
            )
            if not event.wait(timeout):
                raise CTraderError("timeout waiting cTrader response", code="TIMEOUT")
            with self._lock:
                msg = self._pending[mid]["response"] or {}
            ptype = int(msg.get("payloadType") or 0)
            if ptype == PT_ERROR_RES:
                err = msg.get("payload") or {}
                raise CTraderError(
                    str(err.get("description") or err.get("errorCode") or "cTrader error"),
                    code=str(err.get("errorCode") or "E_CTRADER"),
                    details=err,
                )
            if expect and ptype not in expect:
                # Some servers omit clientMsgId echo — accept matching type from inbox
                raise CTraderError(f"unexpected payloadType {ptype}", code="BAD_RESPONSE", details=msg)
            return msg.get("payload") or {}
        finally:
            with self._lock:
                self._pending.pop(mid, None)

    def authorize_account(self, account_id: int) -> dict:
        self.account_id = int(account_id)
        payload = self._rpc(
            PT_ACCOUNT_AUTH_REQ,
            {"ctidTraderAccountId": self.account_id, "accessToken": self.access_token},
            expect={PT_ACCOUNT_AUTH_RES},
        )
        self._account_ok = True
        return payload

    def list_accounts(self) -> list[dict]:
        from goldbot.mt5.broker import BROKER_NAME, is_fp_markets_ctrader_broker

        payload = self._rpc(
            PT_GET_ACCOUNTS_REQ,
            {"accessToken": self.access_token},
            expect={PT_GET_ACCOUNTS_RES},
        )
        rows = payload.get("ctidTraderAccount") or payload.get("accounts") or []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            title = str(r.get("brokerTitle") or r.get("brokerName") or r.get("broker") or "")
            fp = is_fp_markets_ctrader_broker(title)
            out.append(
                {
                    "ctidTraderAccountId": int(r.get("ctidTraderAccountId") or r.get("accountId") or 0),
                    "isLive": bool(r.get("isLive", self.live)),
                    "traderLogin": r.get("traderLogin") or r.get("login"),
                    "brokerTitle": title or BROKER_NAME,
                    "broker": BROKER_NAME if fp else (title or "unknown"),
                    "is_fp_markets": fp,
                    "depositCurrency": r.get("depositCurrency") or r.get("currency") or "USD",
                }
            )
        return [a for a in out if a["ctidTraderAccountId"]]

    def trader(self) -> dict:
        if not self.account_id:
            raise CTraderError("no account selected", code="NO_ACCOUNT")
        return self._rpc(PT_TRADER_REQ, {"ctidTraderAccountId": self.account_id}, expect={PT_TRADER_RES})

    def reconcile(self) -> dict:
        if not self.account_id:
            raise CTraderError("no account selected", code="NO_ACCOUNT")
        return self._rpc(PT_RECONCILE_REQ, {"ctidTraderAccountId": self.account_id}, expect={PT_RECONCILE_RES})

    def load_symbols(self) -> dict[str, dict]:
        if not self.account_id:
            raise CTraderError("no account selected", code="NO_ACCOUNT")
        payload = self._rpc(PT_SYMBOLS_LIST_REQ, {"ctidTraderAccountId": self.account_id}, expect={PT_SYMBOLS_LIST_RES})
        self._symbols = {}
        for s in payload.get("symbol") or []:
            if not isinstance(s, dict):
                continue
            name = str(s.get("symbolName") or s.get("name") or "").upper()
            if not name:
                continue
            self._symbols[name] = s
        return self._symbols

    def resolve_symbol(self, symbol: str) -> dict:
        if not self._symbols:
            self.load_symbols()
        want = str(symbol or "").upper().replace("/", "")
        candidates = [want, want.replace("M", ""), "XAUUSD", "XAUUSD", "GOLD"]
        for c in candidates:
            if c in self._symbols:
                return self._symbols[c]
            for name, row in self._symbols.items():
                if c in name or name in c:
                    return row
        raise CTraderError(f"الرمز غير موجود في cTrader: {symbol}", code="E_SYMBOL")

    def subscribe_spot(self, symbol_id: int) -> None:
        if not self.account_id:
            return
        try:
            self._rpc(
                PT_SUBSCRIBE_SPOTS_REQ,
                {"ctidTraderAccountId": self.account_id, "symbolId": [int(symbol_id)]},
                expect=set(),
                timeout=5,
            )
        except CTraderError:
            # best-effort — spots may still arrive
            pass

    def _volume_from_lot(self, sym: dict, lot: float) -> int:
        """Spotware volume = lots * symbol.lotSize (lotSize in 0.01 units)."""
        lot_size = int(sym.get("lotSize") or 0)
        if lot_size > 0:
            return max(1, int(round(float(lot) * lot_size)))
        # Conservative fallback: 1.00 lot → 100 units → volume 10000 (common FX)
        return max(1, int(round(float(lot) * 10_000)))

    def trendbars(self, symbol: str, timeframe: str = "M15", count: int = 200) -> list[dict]:
        if not self._account_ok:
            raise CTraderError("account not authorized", code="NO_ACCOUNT")
        sym = self.resolve_symbol(symbol)
        symbol_id = int(sym.get("symbolId") or 0)
        period = PERIOD_MAP.get(str(timeframe or "M15").upper(), 7)
        to_ts = int(time.time() * 1000)
        payload = self._rpc(
            PT_GET_TRENDBARS_REQ,
            {
                "ctidTraderAccountId": self.account_id,
                "symbolId": symbol_id,
                "period": period,
                "count": int(max(10, min(count, 500))),
                "toTimestamp": to_ts,
            },
            expect={PT_GET_TRENDBARS_RES},
            timeout=25,
        )
        out: list[dict] = []
        for bar in payload.get("trendbar") or []:
            if not isinstance(bar, dict):
                continue
            mins = int(bar.get("utcTimestampInMinutes") or 0)
            if mins <= 0:
                continue
            o, h, low, c = _trendbar_ohlc(bar)
            if h <= 0 or low <= 0:
                continue
            out.append(
                {
                    "time": mins * 60,
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": float(bar.get("volume") or 0),
                }
            )
        out.sort(key=lambda x: x["time"])
        return out

    def amend_position_sl_tp(self, position_id: int | str, sl: float | None = None, tp: float | None = None) -> dict:
        if not self._account_ok:
            raise CTraderError("account not authorized", code="NO_ACCOUNT")
        payload: dict[str, Any] = {
            "ctidTraderAccountId": self.account_id,
            "positionId": int(position_id),
        }
        if sl is not None and float(sl) > 0:
            payload["stopLoss"] = float(sl)
        if tp is not None and float(tp) > 0:
            payload["takeProfit"] = float(tp)
        if "stopLoss" not in payload and "takeProfit" not in payload:
            return {"ok": False, "error": "no_sl_tp", "execution": "ctrader"}
        try:
            body = self._rpc(
                PT_AMEND_POSITION_SLTP_REQ,
                payload,
                expect={PT_EXECUTION_EVENT, PT_RECONCILE_RES},
                timeout=15,
            )
            return {"ok": True, "raw": body, "execution": "ctrader"}
        except CTraderError as e:
            return {"ok": False, "error": e.message, "code": e.code, "execution": "ctrader"}

    def open_positions(self) -> list[dict]:
        body = self.reconcile() or {}
        rows = body.get("position") or body.get("positions") or []
        out = []
        for p in rows:
            if not isinstance(p, dict):
                continue
            pid = p.get("positionId") or p.get("id")
            if pid in (None, "", 0):
                continue
            out.append(
                {
                    "positionId": str(pid),
                    "id": str(pid),
                    "ticket": str(pid),
                    "volume": p.get("volume"),
                    "tradeSide": p.get("tradeSide"),
                    "price": _decode_price(p.get("price") or p.get("entryPrice")),
                    "stopLoss": p.get("stopLoss"),
                    "takeProfit": p.get("takeProfit"),
                    "raw": p,
                }
            )
        return out

    def order_market(
        self,
        side: str,
        lot: float,
        sl: float = 0.0,
        tp: float = 0.0,
        *,
        symbol: str = "XAUUSD",
        comment: str = "AURUM",
    ) -> dict:
        if not self._account_ok:
            raise CTraderError("account not authorized", code="NO_ACCOUNT")
        sym = self.resolve_symbol(symbol)
        symbol_id = int(sym.get("symbolId") or 0)
        volume = self._volume_from_lot(sym, lot)
        payload: dict[str, Any] = {
            "ctidTraderAccountId": self.account_id,
            "symbolId": symbol_id,
            "orderType": ORDER_TYPE_MARKET,
            "tradeSide": TRADE_SIDE_BUY if side.lower() == "buy" else TRADE_SIDE_SELL,
            "volume": volume,
            "comment": (comment or "AURUM")[:50],
        }
        # Relative SL/TP in 1/100000 price units (best-effort; absolute amend after fill)
        spot = self._last_spots.get(symbol_id) or {}
        bid = float(spot.get("bid") or 0)
        ask = float(spot.get("ask") or 0)
        mark = ask if side.lower() == "buy" else bid
        if sl and float(sl) > 0 and mark > 0:
            payload["relativeStopLoss"] = int(round(abs(mark - float(sl)) * PRICE_SCALE))
        if tp and float(tp) > 0 and mark > 0:
            payload["relativeTakeProfit"] = int(round(abs(float(tp) - mark) * PRICE_SCALE))

        mid = secrets.token_hex(8)
        event = threading.Event()
        with self._lock:
            self._pending[mid] = {"event": event, "response": None}
        assert self._ws
        self._ws.send(json.dumps({"clientMsgId": mid, "payloadType": PT_NEW_ORDER_REQ, "payload": payload}))
        deadline = time.time() + 25
        msg = None
        while time.time() < deadline:
            with self._lock:
                if self._pending[mid]["response"]:
                    msg = self._pending[mid]["response"]
                    break
                for i, m in enumerate(self._inbox):
                    pt = int(m.get("payloadType") or 0)
                    if pt in {PT_EXECUTION_EVENT, PT_ERROR_RES}:
                        msg = self._inbox.pop(i)
                        break
            if msg:
                break
            time.sleep(0.05)
        with self._lock:
            self._pending.pop(mid, None)
        if not msg:
            raise CTraderError("لم يصل تأكيد تنفيذ الأمر من cTrader", code="TIMEOUT")
        if int(msg.get("payloadType") or 0) == PT_ERROR_RES:
            err = msg.get("payload") or {}
            raise CTraderError(str(err.get("description") or err), code=str(err.get("errorCode") or "E_ORDER"))
        body = msg.get("payload") or {}
        exec_type = int(body.get("executionType") or 0)
        pos = body.get("position") or {}
        order = body.get("order") or {}
        deal = body.get("deal") or {}
        pos_id = pos.get("positionId") or order.get("positionId") or deal.get("positionId")
        fill = _decode_price(
            deal.get("executionPrice")
            or deal.get("closePrice")
            or pos.get("price")
            or pos.get("entryPrice")
            or 0
        )
        # Reject cancelled/expired/rejected; require position + fill price
        rejected = exec_type in {3, 4, 5, 6}
        filled_ok = (not rejected) and bool(pos_id) and fill > 0 and (
            exec_type in {EXEC_TYPE_FILLED, EXEC_TYPE_PARTIAL_FILL, 0, 1}
        )
        if not filled_ok:
            return {
                "ok": False,
                "mode": "mt5",
                "execution": "ctrader",
                "error": "not_filled",
                "execution_type": exec_type,
                "raw": body,
            }
        # Absolute SL/TP on broker after fill (protective)
        if pos_id and ((sl and float(sl) > 0) or (tp and float(tp) > 0)):
            try:
                self.amend_position_sl_tp(pos_id, sl=float(sl) if sl else None, tp=float(tp) if tp else None)
            except Exception as e:
                log.warning("ctrader post-fill SL/TP amend failed: %s", e)
        return {
            "ok": True,
            "mode": "mt5",
            "execution": "ctrader",
            "side": side.lower(),
            "lot": float(lot),
            "price": fill,
            "entry": fill,
            "sl": float(sl or 0),
            "tp": float(tp or 0),
            "ticket": int(pos_id or order.get("orderId") or 0),
            "position_id": str(pos_id) if pos_id else None,
            "order_id": order.get("orderId"),
            "symbol": sym.get("symbolName") or symbol,
            "volume": volume,
            "raw": body,
        }

    def close_position(self, position_id: str | int, volume: float | None = None) -> dict:
        if not self.account_id:
            raise CTraderError("no account", code="NO_ACCOUNT")
        payload: dict[str, Any] = {
            "ctidTraderAccountId": self.account_id,
            "positionId": int(position_id),
        }
        if volume is not None:
            # Best-effort: use first symbol lotSize if loaded, else FX-style fallback
            lot_size = 0
            for s in self._symbols.values():
                lot_size = int(s.get("lotSize") or 0)
                if lot_size:
                    break
            if lot_size > 0:
                payload["volume"] = max(1, int(round(float(volume) * lot_size)))
            else:
                payload["volume"] = max(1, int(round(float(volume) * 10_000)))
        try:
            body = self._rpc(PT_CLOSE_POSITION_REQ, payload, expect={PT_EXECUTION_EVENT, PT_RECONCILE_RES})
            return {"ok": True, "raw": body, "execution": "ctrader"}
        except CTraderError as e:
            if "not found" in (e.message or "").lower():
                return {"ok": True, "already_closed": True, "execution": "ctrader"}
            deadline = time.time() + 12
            while time.time() < deadline:
                with self._lock:
                    for i, m in enumerate(self._inbox):
                        if int(m.get("payloadType") or 0) in {PT_EXECUTION_EVENT, PT_ERROR_RES}:
                            msg = self._inbox.pop(i)
                            if int(msg.get("payloadType") or 0) == PT_ERROR_RES:
                                err = msg.get("payload") or {}
                                return {"ok": False, "error": err.get("description") or str(err), "execution": "ctrader"}
                            return {"ok": True, "raw": msg.get("payload"), "execution": "ctrader"}
                time.sleep(0.05)
            return {"ok": False, "error": e.message, "code": e.code, "execution": "ctrader"}


class CTraderCloud:
    """Process-wide cTrader config + helpers for AURUM desk."""

    def __init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        kv = _load_kv()
        self.client_id = _env("CTRADER_CLIENT_ID") or str(kv.get("client_id") or "")
        self.client_secret = _env("CTRADER_CLIENT_SECRET") or str(kv.get("client_secret") or "")
        self.access_token = _env("CTRADER_ACCESS_TOKEN") or str(kv.get("access_token") or "")
        self.refresh_token = _env("CTRADER_REFRESH_TOKEN") or str(kv.get("refresh_token") or "")
        acc = _env("CTRADER_ACCOUNT_ID") or str(kv.get("account_id") or "")
        self.account_id = int(acc) if str(acc).isdigit() else None
        live_raw = _env("CTRADER_LIVE", "") or str(kv.get("live") or "1")
        self.live = str(live_raw).strip().lower() in {"1", "true", "yes", "on", "live"}
        self.redirect_uri = (
            _env("CTRADER_REDIRECT_URI")
            or f"{_env('AURUM_PUBLIC_URL', 'https://pfai-v8.onrender.com').rstrip('/')}/api/ctrader/oauth/callback"
        )

    @property
    def configured(self) -> bool:
        self.refresh()
        return bool(self.client_id and self.client_secret)

    @property
    def ready(self) -> bool:
        self.refresh()
        return bool(self.configured and self.access_token and self.account_id)

    def save_app(self, client_id: str, client_secret: str, *, live: bool | None = None) -> dict:
        patch = {"client_id": client_id.strip(), "client_secret": client_secret.strip()}
        if live is not None:
            patch["live"] = "1" if live else "0"
        _save_kv(patch)
        self.refresh()
        return {"ok": True, "configured": self.configured}

    def auth_url(self, *, state: str | None = None) -> str:
        self.refresh()
        if not self.configured:
            raise CTraderError("missing client id/secret", code="NO_APP")
        q = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "trading",
            "product": "web",
        }
        if state:
            q["state"] = state
        return f"{AUTH_URI}?{urllib.parse.urlencode(q)}"

    def exchange_code(self, code: str) -> dict:
        self.refresh()
        if not self.configured:
            raise CTraderError("missing client id/secret", code="NO_APP")
        token = _http_form(
            TOKEN_URI,
            {
                "grant_type": "authorization_code",
                "code": code.strip(),
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        access = token.get("accessToken") or token.get("access_token")
        refresh = token.get("refreshToken") or token.get("refresh_token")
        if not access:
            raise CTraderError(str(token), code="NO_TOKEN", details=token)
        _save_kv({"access_token": access, "refresh_token": refresh or ""})
        self.refresh()
        return {"ok": True, "access_token": access, "refresh_token": refresh}

    def refresh_access_token(self) -> dict:
        self.refresh()
        if not self.refresh_token:
            raise CTraderError("no refresh token", code="NO_TOKEN")
        token = _http_form(
            TOKEN_URI,
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        access = token.get("accessToken") or token.get("access_token")
        refresh = token.get("refreshToken") or token.get("refresh_token") or self.refresh_token
        if not access:
            raise CTraderError(str(token), code="NO_TOKEN", details=token)
        _save_kv({"access_token": access, "refresh_token": refresh})
        self.refresh()
        return {"ok": True}

    def save_access_token(self, access_token: str, refresh_token: str | None = None) -> dict:
        _save_kv({"access_token": access_token.strip(), "refresh_token": (refresh_token or "").strip()})
        self.refresh()
        return {"ok": True}

    def select_account(self, account_id: int, *, live: bool | None = None) -> dict:
        """Bind only an FP Markets cTrader account — reject other brokers."""
        from goldbot.mt5.broker import BROKER_NAME, DEFAULT_CTRADER_SERVER, is_fp_markets_ctrader_broker

        aid = int(account_id)
        rows = self.list_accounts(fp_markets_only=False)
        match = next((a for a in rows if int(a.get("ctidTraderAccountId") or 0) == aid), None)
        if not match:
            raise CTraderError("account not found after OAuth", code="NO_ACCOUNT")
        title = str(match.get("brokerTitle") or "")
        # Allow empty title only when Spotware omits it (rare); require FP marker when present
        if title and not (is_fp_markets_ctrader_broker(title) or match.get("is_fp_markets")):
            raise CTraderError(
                f"not FP Markets broker: {title}",
                code="WRONG_BROKER",
                details={"brokerTitle": title, "account_id": aid},
            )
        if not title:
            # Spotware sometimes omits brokerTitle — still stamp FP Markets as product broker
            match["is_fp_markets"] = True
        if live is None:
            live = bool(match.get("isLive", self.live))
        server = f"{DEFAULT_CTRADER_SERVER}-{'Live' if live else 'Demo'}"
        patch = {
            "account_id": str(aid),
            "live": "1" if live else "0",
            "broker": BROKER_NAME,
            "broker_title": title or BROKER_NAME,
            "server": server,
            "trader_login": str(match.get("traderLogin") or ""),
        }
        _save_kv(patch)
        self.refresh()
        return {
            "ok": True,
            "account_id": self.account_id,
            "ready": self.ready,
            "broker": BROKER_NAME,
            "broker_title": title or BROKER_NAME,
            "server": server,
            "trader_login": match.get("traderLogin"),
            "is_fp_markets": True,
        }

    def open_session(self) -> CTraderSession:
        self.refresh()
        if not self.configured:
            raise CTraderError("missing app credentials", code="NO_APP")
        if not self.access_token:
            raise CTraderError("missing access token", code="NO_TOKEN")
        sess = CTraderSession(
            self.client_id,
            self.client_secret,
            self.access_token,
            self.account_id,
            live=self.live,
        )
        try:
            sess.connect()
        except CTraderError as e:
            if "TOKEN" in (e.code or "") or "AUTH" in (e.message or "").upper() or "expired" in (e.message or "").lower():
                try:
                    self.refresh_access_token()
                    sess.access_token = self.access_token
                    sess.connect()
                except Exception:
                    raise e from None
            else:
                raise
        return sess

    def list_accounts(self, *, fp_markets_only: bool = True) -> list[dict]:
        sess = self.open_session()
        try:
            rows = sess.list_accounts()
        finally:
            sess.close()
        if not fp_markets_only:
            return rows
        fp = [a for a in rows if a.get("is_fp_markets")]
        # If Spotware omits brokerTitle on all rows, keep them but mark for UI warning
        if not fp and rows and all(not str(a.get("brokerTitle") or "").strip() for a in rows):
            for a in rows:
                a["is_fp_markets"] = True
                a["broker"] = "FP Markets"
                a["broker_assumed"] = True
            return rows
        return fp

    def snapshot(self) -> dict:
        from goldbot.mt5.broker import BROKER_ID, BROKER_NAME, BROKER_PLATFORM, DEFAULT_CTRADER_SERVER

        kv = _load_kv()
        server = str(kv.get("server") or "") or f"{DEFAULT_CTRADER_SERVER}-{'Live' if self.live else 'Demo'}"
        if not self.ready:
            return {
                "connected": False,
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "currency": "USD",
                "server": server,
                "login": 0,
                "broker": BROKER_NAME,
                "broker_id": BROKER_ID,
                "platform": BROKER_PLATFORM,
                "detail": "cTrader/FP Markets غير جاهز — فوّض التطبيق واختر حساب FP Markets",
            }
        sess = self.open_session()
        try:
            trader = sess.trader() or {}
            # trader fields vary by broker
            balance = float(trader.get("balance") or trader.get("balanceMoney") or 0)
            # balances often in cents
            if balance > 10000 and balance == int(balance):
                # heuristic: monetary values in cents
                if balance > 1_000_000 or trader.get("moneyDigits") == 2:
                    balance = balance / 100.0
            equity = float(trader.get("equity") or trader.get("equityMoney") or balance)
            if equity > 10000 and equity == int(equity) and trader.get("moneyDigits") == 2:
                equity = equity / 100.0
            margin = float(trader.get("usedMargin") or trader.get("margin") or 0)
            if margin > 10000 and trader.get("moneyDigits") == 2:
                margin = margin / 100.0
            free_m = float(trader.get("freeMargin") or max(0.0, equity - margin))
            login = int(trader.get("login") or trader.get("traderLogin") or kv.get("trader_login") or self.account_id or 0)
            return {
                "connected": True,
                "balance": balance,
                "equity": equity,
                "margin": margin,
                "free_margin": free_m,
                "currency": str(trader.get("depositAssetId") or trader.get("currency") or "USD"),
                "server": server,
                "login": login,
                "broker": BROKER_NAME,
                "broker_id": BROKER_ID,
                "broker_title": str(kv.get("broker_title") or BROKER_NAME),
                "platform": BROKER_PLATFORM,
                "detail": f"{BROKER_NAME} عبر cTrader Open API (من التطبيق مباشرة)",
                "account_id": self.account_id,
            }
        finally:
            sess.close()

    def order_market(self, side: str, lot: float, sl: float, tp: float, *, symbol: str = "XAUUSD", comment: str = "AURUM") -> dict:
        sess = self.open_session()
        try:
            try:
                sym = sess.resolve_symbol(symbol)
                sess.subscribe_spot(int(sym.get("symbolId") or 0))
                time.sleep(0.3)
            except Exception:
                pass
            return sess.order_market(side, lot, sl, tp, symbol=symbol, comment=comment)
        finally:
            sess.close()

    def close_position(self, position_id: str | int, volume: float | None = None) -> dict:
        sess = self.open_session()
        try:
            return sess.close_position(position_id, volume=volume)
        finally:
            sess.close()

    def candles(self, symbol: str = "XAUUSD", timeframe: str = "M15", count: int = 200) -> list[dict]:
        sess = self.open_session()
        try:
            return sess.trendbars(symbol, timeframe=timeframe, count=count)
        finally:
            sess.close()

    def amend_position_sl_tp(self, position_id: str | int, sl: float | None = None, tp: float | None = None) -> dict:
        sess = self.open_session()
        try:
            return sess.amend_position_sl_tp(position_id, sl=sl, tp=tp)
        finally:
            sess.close()

    def open_positions(self) -> list[dict]:
        sess = self.open_session()
        try:
            return sess.open_positions()
        finally:
            sess.close()

    def symbol_price(self, symbol: str = "XAUUSD") -> dict:
        sess = self.open_session()
        try:
            sym = sess.resolve_symbol(symbol)
            sid = int(sym.get("symbolId") or 0)
            sess.subscribe_spot(sid)
            deadline = time.time() + 8
            while time.time() < deadline:
                spot = sess._last_spots.get(sid)
                if spot and (spot.get("bid") or spot.get("ask")):
                    return {
                        "bid": float(spot.get("bid") or 0),
                        "ask": float(spot.get("ask") or 0),
                        "symbol": sym.get("symbolName") or symbol,
                        "source": "ctrader",
                    }
                time.sleep(0.1)
            return {}
        finally:
            sess.close()


ctrader = CTraderCloud()
