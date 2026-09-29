"""
Linux MT5 executor client — real Exness without Windows.

Talks to a headless MT5 REST wrapper running under Wine in Docker on any
Linux host (e.g. thanderoy/headless-mt5). The user never needs Windows;
they run one Linux container and point AURUM at its URL.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from goldbot.config import settings

log = logging.getLogger("aurum.mt5_linux")


class Mt5LinuxError(Exception):
    def __init__(self, message: str, *, status: int = 400, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details


class Mt5LinuxClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.mt5_linux_url).rstrip("/")
        self.token = (token if token is not None else settings.mt5_linux_token).strip()

    @property
    def configured(self) -> bool:
        if not self.base_url:
            self.refresh()
        return bool(self.base_url)

    def refresh(self) -> str:
        self.base_url = (settings.mt5_linux_url or "").rstrip("/")
        if not self.base_url:
            try:
                from goldbot.storage.state import store

                saved = store.get_kv("mt5_linux_url") or ""
                if saved:
                    self.base_url = str(saved).rstrip("/")
                    settings.mt5_linux_url = self.base_url
                tok = store.get_kv("mt5_linux_token") or ""
                if tok:
                    self.token = str(tok).strip()
                    settings.mt5_linux_token = self.token
            except Exception as e:
                log.warning("mt5_linux config load: %s", e)
        return self.base_url

    def set_config(self, base_url: str, token: str = "") -> None:
        from goldbot.storage.state import store

        self.base_url = (base_url or "").rstrip("/")
        self.token = (token or "").strip()
        settings.mt5_linux_url = self.base_url
        settings.mt5_linux_token = self.token
        store.set_kv("mt5_linux_url", self.base_url)
        if self.token:
            store.set_kv("mt5_linux_token", self.token)

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "AURUM/3.3"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, body: dict | None = None, timeout: float = 45.0) -> Any:
        if not self.configured:
            raise Mt5LinuxError("عنوان منفّذ Linux غير مضبوط", status=503)
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"detail": raw}
            msg = payload.get("detail") or payload.get("message") or payload.get("error") or f"HTTP {e.code}"
            if isinstance(msg, list):
                msg = str(msg)
            raise Mt5LinuxError(str(msg), status=int(e.code), details=payload) from e
        except urllib.error.URLError as e:
            raise Mt5LinuxError(f"تعذّر الوصول لمنفّذ Linux: {e.reason}", status=502) from e

    def health(self) -> dict:
        try:
            data = self._req("GET", "/", timeout=10)
            return {"ok": True, "raw": data}
        except Mt5LinuxError as e:
            return {"ok": False, "error": e.message}

    def connect(self) -> dict:
        return self._req("POST", "/api/v1/connect", {})

    def account(self) -> dict:
        data = self._req("GET", "/api/v1/account")
        return data if isinstance(data, dict) else {}

    def tick(self, symbol: str) -> dict:
        # Some wrappers use query, some path — try query first
        try:
            data = self._req("GET", f"/api/v1/tick?symbol={symbol}", timeout=15)
        except Mt5LinuxError:
            data = self._req("GET", f"/api/v1/tick/{symbol}", timeout=15)
        return data if isinstance(data, dict) else {}

    def order_market(
        self,
        side: str,
        lot: float,
        sl: float,
        tp: float,
        *,
        symbol: str = "XAUUSD",
        comment: str = "AURUM",
    ) -> dict:
        from goldbot.mt5.symbols import symbol_candidates

        action = "BUY" if side.lower() == "buy" else "SELL"
        last = {"ok": False, "error": "no symbol worked", "mode": "mt5", "execution": "mt5_linux"}
        for sym in symbol_candidates(symbol):
            body = {
                "action": action,
                "symbol": sym,
                "volume": float(lot),
                "order_type": "MARKET",
                "sl": float(sl) if sl else None,
                "tp": float(tp) if tp else None,
                "deviation": 40,
                "magic": int(settings.metaapi_magic or 908070),
                "comment": (comment or "AURUM")[:31],
            }
            try:
                resp = self._req("POST", "/api/v1/order/send", body, timeout=60)
            except Mt5LinuxError as e:
                last = {
                    "ok": False,
                    "error": e.message,
                    "mode": "mt5",
                    "execution": "mt5_linux",
                    "details": e.details,
                    "symbol": sym,
                }
                if "symbol" in (e.message or "").lower():
                    continue
                return last

            ok = bool(
                resp.get("success")
                or resp.get("ok")
                or str(resp.get("retcode") or "") in {"10009", "10008", "10010", "0"}
                or resp.get("order")
                or resp.get("ticket")
            )
            ticket = resp.get("order") or resp.get("ticket") or resp.get("order_id") or 0
            try:
                ticket_i = int(ticket) if ticket not in (None, "") else 0
            except (TypeError, ValueError):
                ticket_i = 0
            last = {
                "ok": ok,
                "mode": "mt5",
                "execution": "mt5_linux",
                "side": side,
                "lot": float(lot),
                "sl": float(sl or 0),
                "tp": float(tp or 0),
                "ticket": ticket_i,
                "price": resp.get("price") or resp.get("price_open"),
                "symbol": sym,
                "error": None if ok else (resp.get("message") or resp.get("comment") or "order failed"),
                "raw": resp,
            }
            if ok:
                settings.symbol = sym
                return last
            if "symbol" in str(resp.get("message") or "").lower():
                continue
            return last
        return last

    def snapshot(self) -> dict:
        try:
            self.connect()
        except Mt5LinuxError as e:
            # already connected is fine on some wrappers
            if "already" not in e.message.lower() and e.status not in {200, 409}:
                log.info("mt5_linux connect: %s", e.message)
        try:
            info = self.account()
        except Mt5LinuxError as e:
            return {
                "connected": False,
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "currency": "USD",
                "server": "",
                "login": 0,
                "detail": e.message,
            }
        return {
            "connected": True,
            "balance": float(info.get("balance") or 0),
            "equity": float(info.get("equity") or 0),
            "margin": float(info.get("margin") or 0),
            "free_margin": float(info.get("margin_free") or info.get("free_margin") or 0),
            "currency": str(info.get("currency") or "USD"),
            "server": str(info.get("server") or ""),
            "login": int(info.get("login") or 0),
            "detail": "Exness عبر MT5 على Linux Docker (بدون Windows)",
        }


mt5_linux = Mt5LinuxClient()
