"""
MetaApi cloud connector — real Exness/MT5 execution without Windows.

Uses MetaApi Provisioning API + Client REST API so AURUM on Linux/Render
can create a cloud MT5 terminal and place live orders from the app alone.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from goldbot.config import settings

log = logging.getLogger("aurum.metaapi")

PROVISIONING_BASE = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT_HOST = "https://mt-client-api-v1.{region}.agiliumtrade.ai"

SUCCESS_CODES = {
    0,
    10008,  # TRADE_RETCODE_PLACED
    10009,  # TRADE_RETCODE_DONE
    10010,  # TRADE_RETCODE_DONE_PARTIAL
    10025,  # TRADE_RETCODE_NO_CHANGES
}
SUCCESS_STRINGS = {
    "ERR_NO_ERROR",
    "TRADE_RETCODE_PLACED",
    "TRADE_RETCODE_DONE",
    "TRADE_RETCODE_DONE_PARTIAL",
    "TRADE_RETCODE_NO_CHANGES",
}


class MetaApiError(Exception):
    def __init__(self, message: str, *, code: str | None = None, status: int = 400, details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details


class MetaApiCloud:
    """Thin REST client for MetaApi cloud G2 accounts."""

    def __init__(
        self,
        token: str | None = None,
        region: str | None = None,
        magic: int | None = None,
        http: Callable[..., dict | list | None] | None = None,
    ) -> None:
        self.token = (token if token is not None else settings.metaapi_token).strip()
        self.region = (region if region is not None else settings.metaapi_region).strip() or "new-york"
        self.magic = int(magic if magic is not None else settings.metaapi_magic)
        self._http = http or self._default_http

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _headers(self, *, transaction: bool = False) -> dict[str, str]:
        h = {
            "auth-token": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if transaction:
            h["transaction-id"] = secrets.token_hex(16)
        return h

    def _default_http(
        self,
        method: str,
        url: str,
        body: dict | None = None,
        *,
        transaction: bool = False,
        transaction_id: str | None = None,
        timeout: float = 60.0,
        accept_202: bool = True,
    ) -> dict | list | None:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = self._headers(transaction=False)
        if transaction or transaction_id:
            headers["transaction-id"] = transaction_id or secrets.token_hex(16)
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"message": raw or str(e)}
            if e.code == 202 and accept_202:
                raise MetaApiError(
                    payload.get("message") or "MetaApi request accepted — retry shortly",
                    code="ACCEPTED",
                    status=202,
                    details=payload,
                )
            details = payload.get("details")
            code = None
            if isinstance(details, dict):
                code = details.get("code") or details.get("error")
            elif isinstance(details, str):
                code = details
            raise MetaApiError(
                payload.get("message") or payload.get("error") or f"MetaApi HTTP {e.code}",
                code=str(code) if code else payload.get("error"),
                status=int(e.code),
                details=payload,
            )
        except urllib.error.URLError as e:
            raise MetaApiError(f"MetaApi network error: {e.reason}", code="NETWORK", status=502) from e

    def _client_url(self, path: str, region: str | None = None) -> str:
        host = CLIENT_HOST.format(region=(region or self.region).strip())
        return f"{host}{path}"

    def _prov_url(self, path: str) -> str:
        return f"{PROVISIONING_BASE}{path}"

    def list_accounts(self) -> list[dict]:
        data = self._http("GET", self._prov_url("/users/current/accounts"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("accounts") or data.get("items") or [])
        return []

    def get_account(self, account_id: str) -> dict:
        data = self._http("GET", self._prov_url(f"/users/current/accounts/{account_id}"))
        if not isinstance(data, dict):
            raise MetaApiError("invalid account response", code="BAD_RESPONSE")
        return data

    def find_account_by_login(self, login: str, server: str | None = None) -> dict | None:
        login_s = str(login).strip()
        server_s = (server or "").strip().lower()
        for acc in self.list_accounts():
            if str(acc.get("login") or "").strip() != login_s:
                continue
            if server_s and str(acc.get("server") or "").strip().lower() != server_s:
                continue
            return acc
        return None

    def create_account(
        self,
        login: str,
        password: str,
        server: str,
        *,
        name: str | None = None,
        symbol: str = "XAUUSD",
        keywords: list[str] | None = None,
        resource_slots: int | None = None,
    ) -> dict:
        """Create cloud-g2 MT5 account with retries for broker detection / 202."""
        body: dict[str, Any] = {
            "login": str(login).strip(),
            "password": str(password),
            "name": name or f"AURUM-{login}",
            "server": str(server).strip(),
            "platform": "mt5",
            "magic": self.magic,
            "type": "cloud-g2",
            "region": self.region,
            "reliability": "high",
            "manualTrades": False,
            "keywords": keywords or ["Exness", "Exness Technologies"],
            "metadata": {"product": "AURUM", "symbol": symbol},
        }
        if resource_slots:
            body["resourceSlots"] = int(resource_slots)

        tx = secrets.token_hex(16)
        last_err: MetaApiError | None = None
        for attempt in range(8):
            try:
                data = self._http(
                    "POST",
                    self._prov_url("/users/current/accounts"),
                    body,
                    transaction_id=tx,
                    timeout=90,
                )
                if isinstance(data, dict) and data.get("id"):
                    return data
                raise MetaApiError("create returned no account id", details=data)
            except MetaApiError as e:
                last_err = e
                if e.code == "E_RESOURCE_SLOTS" and isinstance(e.details, dict):
                    details = e.details.get("details") if isinstance(e.details.get("details"), dict) else e.details
                    slots = 2
                    if isinstance(details, dict):
                        slots = int(details.get("recommendedResourceSlots") or 2)
                    body["resourceSlots"] = slots
                    tx = secrets.token_hex(16)
                    continue
                if e.code == "ACCEPTED" or e.status == 202:
                    wait = 12 + attempt * 6
                    log.info("metaapi create accepted, retry in %ss", wait)
                    time.sleep(wait)
                    continue
                msg = (e.message or "").lower()
                if "retry" in msg or "in progress" in msg or "detection" in msg:
                    time.sleep(15 + attempt * 5)
                    continue
                raise
        raise last_err or MetaApiError("create account timed out")

    def deploy(self, account_id: str) -> dict:
        data = self._http("POST", self._prov_url(f"/users/current/accounts/{account_id}/deploy"), {}, transaction=True)
        return data if isinstance(data, dict) else {"ok": True}

    def ensure_deployed(self, account_id: str) -> dict:
        acc = self.get_account(account_id)
        state = str(acc.get("state") or "").upper()
        if state != "DEPLOYED":
            try:
                self.deploy(account_id)
            except MetaApiError as e:
                # already deploying / deployed is fine
                if "already" not in (e.message or "").lower():
                    log.warning("deploy: %s", e.message)
            # refresh
            for _ in range(12):
                time.sleep(5)
                acc = self.get_account(account_id)
                if str(acc.get("state") or "").upper() == "DEPLOYED":
                    break
        return acc

    def wait_connected(self, account_id: str, timeout: float = 120.0) -> dict:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            last = self.get_account(account_id)
            # connectionStatus may be on account or primary replica
            status = str(last.get("connectionStatus") or "").upper()
            replicas = last.get("accountReplicas") or last.get("replicas") or []
            if not status and isinstance(replicas, list):
                for r in replicas:
                    if isinstance(r, dict) and r.get("connectionStatus"):
                        status = str(r["connectionStatus"]).upper()
                        break
            state = str(last.get("state") or "").upper()
            if status == "CONNECTED" and state == "DEPLOYED":
                return last
            if state != "DEPLOYED":
                try:
                    self.deploy(account_id)
                except Exception:
                    pass
            time.sleep(4)
        return last

    def ensure_account(
        self,
        login: str,
        password: str,
        server: str,
        *,
        symbol: str = "XAUUSD",
        existing_id: str | None = None,
        wait: bool = True,
    ) -> dict:
        """Find or create cloud account; optionally wait until CONNECTED."""
        if not self.configured:
            raise MetaApiError(
                "METAAPI_TOKEN غير مضبوط — أضفه في Render لربط Exness من السحابة بدون Windows",
                code="NO_TOKEN",
                status=503,
            )

        acc = None
        if existing_id:
            try:
                acc = self.get_account(existing_id)
            except MetaApiError:
                acc = None
        if not acc:
            acc = self.find_account_by_login(login, server)
        if not acc:
            created = self.create_account(login, password, server, symbol=symbol)
            account_id = str(created["id"])
            acc = self.get_account(account_id)
        else:
            account_id = str(acc["id"])
            # Update password if account already exists (best-effort)
            try:
                self._http(
                    "PUT",
                    self._prov_url(f"/users/current/accounts/{account_id}/password"),
                    {"password": password},
                    transaction=True,
                )
            except MetaApiError as e:
                log.info("password update skipped: %s", e.message)

        acc = self.ensure_deployed(account_id)
        connected = False
        if wait:
            acc = self.wait_connected(account_id, timeout=float(settings.metaapi_connect_timeout))
            status = str(acc.get("connectionStatus") or "").upper()
            replicas = acc.get("accountReplicas") or acc.get("replicas") or []
            if not status and isinstance(replicas, list):
                for r in replicas:
                    if isinstance(r, dict) and str(r.get("connectionStatus") or "").upper() == "CONNECTED":
                        status = "CONNECTED"
                        break
            connected = status == "CONNECTED"

        region = str(acc.get("region") or self.region)
        return {
            "ok": True,
            "account_id": account_id,
            "region": region,
            "state": acc.get("state"),
            "connection_status": acc.get("connectionStatus"),
            "connected": connected,
            "login": acc.get("login") or login,
            "server": acc.get("server") or server,
            "raw": acc,
        }

    def account_information(self, account_id: str, region: str | None = None) -> dict:
        data = self._http(
            "GET",
            self._client_url(f"/users/current/accounts/{account_id}/account-information", region),
            timeout=30,
        )
        if not isinstance(data, dict):
            raise MetaApiError("no account information")
        return data

    def positions(self, account_id: str, region: str | None = None) -> list[dict]:
        data = self._http(
            "GET",
            self._client_url(f"/users/current/accounts/{account_id}/positions", region),
            timeout=30,
        )
        return data if isinstance(data, list) else []

    def symbol_price(self, account_id: str, symbol: str, region: str | None = None) -> dict:
        data = self._http(
            "GET",
            self._client_url(f"/users/current/accounts/{account_id}/symbols/{symbol}/current-price", region),
            timeout=20,
        )
        return data if isinstance(data, dict) else {}

    def trade(self, account_id: str, trade: dict, region: str | None = None) -> dict:
        data = self._http(
            "POST",
            self._client_url(f"/users/current/accounts/{account_id}/trade", region),
            trade,
            timeout=45,
        )
        if not isinstance(data, dict):
            raise MetaApiError("empty trade response")
        return data

    def order_market(
        self,
        account_id: str,
        side: str,
        lot: float,
        sl: float,
        tp: float,
        *,
        symbol: str = "XAUUSD",
        comment: str = "AURUM",
        region: str | None = None,
    ) -> dict:
        action = "ORDER_TYPE_BUY" if side.lower() == "buy" else "ORDER_TYPE_SELL"
        payload: dict[str, Any] = {
            "actionType": action,
            "symbol": symbol,
            "volume": float(lot),
            "comment": (comment or "AURUM")[:31],
        }
        if sl and float(sl) > 0:
            payload["stopLoss"] = float(sl)
        if tp and float(tp) > 0:
            payload["takeProfit"] = float(tp)

        try:
            resp = self.trade(account_id, payload, region=region)
        except MetaApiError as e:
            return {"ok": False, "error": e.message, "code": e.code, "mode": "metaapi", "details": e.details}

        numeric = resp.get("numericCode")
        string_code = str(resp.get("stringCode") or "")
        ok = (numeric in SUCCESS_CODES) or (string_code in SUCCESS_STRINGS)
        # Some responses nest under 'result'
        if not ok and isinstance(resp.get("numericCode"), (int, float)):
            ok = int(resp["numericCode"]) in SUCCESS_CODES

        ticket = resp.get("orderId") or resp.get("positionId") or 0
        try:
            ticket_i = int(ticket) if ticket not in (None, "") else 0
        except (TypeError, ValueError):
            ticket_i = 0

        return {
            "ok": ok,
            "mode": "metaapi",
            "side": side,
            "lot": float(lot),
            "sl": float(sl or 0),
            "tp": float(tp or 0),
            "ticket": ticket_i,
            "order_id": resp.get("orderId"),
            "position_id": resp.get("positionId"),
            "retcode": numeric,
            "string_code": string_code,
            "comment": comment,
            "error": None if ok else (resp.get("message") or string_code or "trade failed"),
            "raw": resp,
        }

    def close_position(self, account_id: str, position_id: str | int, region: str | None = None) -> dict:
        try:
            resp = self.trade(
                account_id,
                {"actionType": "POSITION_CLOSE_ID", "positionId": str(position_id)},
                region=region,
            )
        except MetaApiError as e:
            return {"ok": False, "error": e.message, "code": e.code}
        numeric = resp.get("numericCode")
        string_code = str(resp.get("stringCode") or "")
        ok = (numeric in SUCCESS_CODES) or (string_code in SUCCESS_STRINGS)
        return {"ok": ok, "raw": resp, "error": None if ok else resp.get("message")}

    def snapshot(self, account_id: str, region: str | None = None) -> dict:
        """Normalized account snapshot for the desk."""
        try:
            info = self.account_information(account_id, region=region)
        except MetaApiError as e:
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
                "error": e.code,
            }
        return {
            "connected": True,
            "balance": float(info.get("balance") or 0),
            "equity": float(info.get("equity") or 0),
            "margin": float(info.get("margin") or 0),
            "free_margin": float(info.get("freeMargin") or info.get("marginFree") or 0),
            "currency": str(info.get("currency") or "USD"),
            "server": str(info.get("server") or ""),
            "login": int(info.get("login") or 0),
            "detail": "Exness عبر MetaApi السحابي (بدون Windows)",
            "leverage": info.get("leverage"),
            "trade_allowed": info.get("tradeAllowed", True),
        }


# Process-wide client (token from env)
metaapi = MetaApiCloud()
