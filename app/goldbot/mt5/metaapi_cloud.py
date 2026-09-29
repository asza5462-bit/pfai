"""
MetaApi cloud connector — real Exness/MT5 execution without Windows.

Uses MetaApi Provisioning API + Client REST API so AURUM on Linux/Render
can create a cloud MT5 terminal and place live orders from the app alone.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from uuid import UUID

from goldbot.config import settings

log = logging.getLogger("aurum.metaapi")

PROVISIONING_BASE = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT_HOST = "https://mt-client-api-v1.{region}.agiliumtrade.ai"
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def is_metaapi_account_id(value: str | None) -> bool:
    """MetaApi account ids are UUIDs (with/without dashes). Reject bare numbers like 1215."""
    s = str(value or "").strip()
    if not s or s.isdigit():
        return False
    try:
        UUID(s)
        return True
    except Exception:
        pass
    if _HEX32.match(s):
        return True
    return False


def normalize_account_id(value: str | None) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if _HEX32.match(s):
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}".lower()
    try:
        return str(UUID(s))
    except Exception:
        return s if is_metaapi_account_id(s) else ""


def arabic_metaapi_error(exc: MetaApiError | Exception) -> str:
    msg = str(getattr(exc, "message", None) or exc)
    code = str(getattr(exc, "code", "") or "")
    low = msg.lower()
    # "Trading account with id: 1215 not found (...)" and similar MetaApi payloads
    if (
        "not found" in low
        or "trading account with id" in low
        or code in {"NotFoundError", "E_NOT_FOUND", "E_BAD_ACCOUNT_ID"}
    ):
        return (
            "حساب MetaApi السحابي غير موجود أو تالف. "
            "اضغط «إعادة ربط كامل» من تبويب الربط ليُنشأ من جديد."
        )
    if code == "E_PROVISION_PENDING" or "قيد التجهيز" in msg or "جاري تجهيز" in msg:
        return "الطرفية السحابية قيد التجهيز — انتظر نصف دقيقة ثم اضغط «تحديث / إعادة ربط»."
    if code in {"E_AUTH"} or "authenticate" in low or "invalid account" in low or "wrong password" in low:
        return "رفض Exness بيانات الدخول — تحقق من الرقم وكلمة مرور التداول (وليس Investor) والسيرفر (مثل Exness-MT5Trial15)."
    if "investor" in low:
        return "كلمة مرور Investor لا تكفي — استخدم كلمة مرور التداول من Exness."
    if "server" in low and ("not found" in low or "unknown" in low or "invalid" in low):
        return "اسم السيرفر غير مطابق — انسخه حرفياً من Exness (مثال Exness-MT5Trial15)."
    if code == "NO_TOKEN" or "metaapi_token" in low or ("لا يوجد" in msg and "token" in low) or "unauthorized" in low:
        return "توكن MetaApi غير صالح أو غير محفوظ — الصقه مجدداً من تبويب الربط أو شاشة الدخول."
    if "timeout" in low or code == "NETWORK":
        return "انتهت مهلة الاتصال بـ MetaApi — أعد المحاولة بعد ثوانٍ."
    if "password" in low and "change" in low:
        return "Exness يطلب تغيير كلمة المرور — غيّرها من التطبيق الرسمي ثم أعد الربط."
    if "resource" in low or code == "E_RESOURCE_SLOTS":
        return "حساب MetaApi يحتاج موارد إضافية — أعد المحاولة أو رقِّ خطة MetaApi."
    return f"تعذّر الربط السحابي: {msg}"

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


def _load_stored_token() -> str:
    """Env first, then encrypted token saved from the app UI."""
    env = (settings.metaapi_token or "").strip()
    if env:
        return env
    try:
        from goldbot.auth.users import auth
        from goldbot.storage.state import store

        enc = store.get_kv("metaapi_token_enc")
        if not enc:
            return ""
        return auth._decrypt(str(enc)).strip()
    except Exception as e:
        log.warning("metaapi token load failed: %s", e)
        return ""


def save_stored_token(token: str) -> None:
    """Persist MetaApi token encrypted so Render env is optional."""
    from goldbot.auth.users import auth
    from goldbot.storage.state import store

    clean = (token or "").strip()
    if not clean:
        raise MetaApiError("التوكن فارغ", code="EMPTY_TOKEN")
    store.set_kv("metaapi_token_enc", auth._encrypt(clean))
    settings.metaapi_token = clean


class MetaApiCloud:
    """Thin REST client for MetaApi cloud G2 accounts."""

    def __init__(
        self,
        token: str | None = None,
        region: str | None = None,
        magic: int | None = None,
        http: Callable[..., dict | list | None] | None = None,
    ) -> None:
        # token=None means resolve from env/store; token="" means explicitly empty (tests)
        if token is None:
            self.token = _load_stored_token()
        else:
            self.token = str(token).strip()
        self.region = (region if region is not None else settings.metaapi_region).strip() or "new-york"
        self.magic = int(magic if magic is not None else settings.metaapi_magic)
        self._http = http or self._default_http

    @property
    def configured(self) -> bool:
        if not self.token:
            self.refresh_token()
        return bool(self.token)

    def set_token(self, token: str) -> None:
        self.token = (token or "").strip()
        settings.metaapi_token = self.token

    def refresh_token(self) -> str:
        self.token = _load_stored_token()
        return self.token

    def validate_token(self) -> dict:
        """Light check that the token works against Provisioning API."""
        if not self.configured:
            raise MetaApiError("لا يوجد METAAPI_TOKEN", code="NO_TOKEN", status=503)
        accounts = self.list_accounts()
        return {"ok": True, "accounts": len(accounts), "region": self.region}

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
        aid = normalize_account_id(account_id)
        if not aid:
            raise MetaApiError(
                f"معرّف حساب MetaApi غير صالح: {account_id!r}",
                code="E_BAD_ACCOUNT_ID",
                status=400,
            )
        data = self._http("GET", self._prov_url(f"/users/current/accounts/{aid}"))
        if not isinstance(data, dict):
            raise MetaApiError("invalid account response", code="BAD_RESPONSE")
        # Never accept numeric error-shaped payloads as accounts
        if data.get("error") and not is_metaapi_account_id(str(data.get("id") or "")):
            raise MetaApiError(
                data.get("message") or "MetaApi account error",
                code=str(data.get("error")),
                status=404,
                details=data,
            )
        return data

    def find_account_by_login(self, login: str, server: str | None = None) -> dict | None:
        login_s = str(login).strip()
        server_s = (server or "").strip().lower()
        for acc in self.list_accounts():
            if not isinstance(acc, dict):
                continue
            acc_id = normalize_account_id(str(acc.get("id") or acc.get("accountId") or ""))
            if not acc_id:
                continue
            if str(acc.get("login") or "").strip() != login_s:
                continue
            if server_s and str(acc.get("server") or "").strip().lower() != server_s:
                continue
            acc = dict(acc)
            acc["id"] = acc_id
            return acc
        # Fallback: match login only (server name variants)
        for acc in self.list_accounts():
            if not isinstance(acc, dict):
                continue
            if str(acc.get("login") or "").strip() != login_s:
                continue
            acc_id = normalize_account_id(str(acc.get("id") or acc.get("accountId") or ""))
            if not acc_id:
                continue
            acc = dict(acc)
            acc["id"] = acc_id
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
        fast: bool = False,
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
        attempts = 3 if fast else 8
        for attempt in range(attempts):
            try:
                data = self._http(
                    "POST",
                    self._prov_url("/users/current/accounts"),
                    body,
                    transaction_id=tx,
                    timeout=35 if fast else 90,
                )
                if isinstance(data, dict) and is_metaapi_account_id(str(data.get("id") or "")):
                    data = dict(data)
                    data["id"] = normalize_account_id(str(data["id"]))
                    return data
                # Reject numeric error ids (e.g. ValidationError id: 3 / 1215)
                if isinstance(data, dict) and data.get("error"):
                    raise MetaApiError(
                        data.get("message") or "create failed",
                        code=str(data.get("error")),
                        status=400,
                        details=data,
                    )
                raise MetaApiError("create returned no valid account id", details=data)
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
                # Hard fail fast on credential / server problems — do not spin for minutes
                msg = (e.message or "").lower()
                if e.code in {"E_AUTH", "UnauthorizedError"} or any(
                    x in msg for x in ("wrong password", "invalid password", "authenticate", "investor password")
                ):
                    raise
                if e.code == "ACCEPTED" or e.status == 202:
                    wait = (3 + attempt * 2) if fast else (12 + attempt * 6)
                    log.info("metaapi create accepted, retry in %ss", wait)
                    time.sleep(wait)
                    # After 202, account may already exist — try find before retry POST
                    found = self.find_account_by_login(login, server)
                    if found and is_metaapi_account_id(str(found.get("id") or "")):
                        return found
                    continue
                if "retry" in msg or "in progress" in msg or "detection" in msg:
                    time.sleep((4 + attempt * 2) if fast else (15 + attempt * 5))
                    found = self.find_account_by_login(login, server)
                    if found and is_metaapi_account_id(str(found.get("id") or "")):
                        return found
                    continue
                raise
        # Last chance: broker detection may have created it despite timeout
        found = self.find_account_by_login(login, server)
        if found and is_metaapi_account_id(str(found.get("id") or "")):
            return found
        raise last_err or MetaApiError("create account timed out")

    def deploy(self, account_id: str) -> dict:
        data = self._http("POST", self._prov_url(f"/users/current/accounts/{account_id}/deploy"), {}, transaction=True)
        return data if isinstance(data, dict) else {"ok": True}

    def ensure_deployed(self, account_id: str, *, max_wait: float = 60.0) -> dict:
        acc = self.get_account(account_id)
        state = str(acc.get("state") or "").upper()
        if state != "DEPLOYED":
            try:
                self.deploy(account_id)
            except MetaApiError as e:
                # already deploying / deployed is fine
                if "already" not in (e.message or "").lower():
                    log.warning("deploy: %s", e.message)
            deadline = time.time() + max(0.0, float(max_wait))
            while time.time() < deadline:
                time.sleep(2 if max_wait <= 12 else 5)
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
            time.sleep(3)
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
        fast: bool = False,
        deploy_wait: float | None = None,
    ) -> dict:
        """Find or create cloud account; optionally wait until CONNECTED.

        Use fast=True for HTTP login paths (Render/Safari kill long requests).
        """
        if not self.configured:
            raise MetaApiError(
                "METAAPI_TOKEN غير مضبوط — أضفه في التطبيق لربط Exness من السحابة بدون Windows",
                code="NO_TOKEN",
                status=503,
            )

        acc = None
        existing = normalize_account_id(existing_id) if is_metaapi_account_id(existing_id) else ""
        if existing_id and not existing:
            log.warning("ignoring invalid metaapi_account_id=%r", existing_id)
        if existing:
            try:
                acc = self.get_account(existing)
            except MetaApiError as e:
                log.warning("stale metaapi account %s: %s — will recreate", existing, e.message)
                acc = None
        if not acc:
            acc = self.find_account_by_login(login, server)
        if not acc:
            created = self.create_account(login, password, server, symbol=symbol, fast=fast)
            account_id = normalize_account_id(str(created["id"]))
            if not account_id:
                raise MetaApiError("MetaApi أعاد معرّفاً غير صالح بعد الإنشاء", code="E_BAD_ACCOUNT_ID")
            try:
                acc = self.get_account(account_id)
            except MetaApiError as e:
                # Race: account created but not yet readable — use create payload
                if "not found" in (e.message or "").lower():
                    acc = {"id": account_id, "state": created.get("state") or "DEPLOYED", "login": login, "server": server}
                else:
                    raise
        else:
            account_id = normalize_account_id(str(acc.get("id") or ""))
            if not account_id:
                raise MetaApiError("الحساب الموجود بلا معرّف UUID صالح", code="E_BAD_ACCOUNT_ID")
            try:
                self._http(
                    "PUT",
                    self._prov_url(f"/users/current/accounts/{account_id}/password"),
                    {"password": password},
                    transaction=True,
                )
            except MetaApiError as e:
                log.info("password update skipped: %s", e.message)

        deploy_budget = deploy_wait if deploy_wait is not None else (8.0 if fast else 60.0)
        try:
            acc = self.ensure_deployed(account_id, max_wait=deploy_budget)
        except MetaApiError as e:
            if "not found" in (e.message or "").lower():
                # Force fresh create once
                created = self.create_account(login, password, server, symbol=symbol, fast=fast)
                account_id = normalize_account_id(str(created["id"]))
                acc = self.ensure_deployed(account_id, max_wait=deploy_budget)
            else:
                raise

        connected = False
        if wait:
            wait_timeout = 25.0 if fast else float(settings.metaapi_connect_timeout)
            acc = self.wait_connected(account_id, timeout=wait_timeout)
            status = str(acc.get("connectionStatus") or "").upper()
            replicas = acc.get("accountReplicas") or acc.get("replicas") or []
            if not status and isinstance(replicas, list):
                for r in replicas:
                    if isinstance(r, dict) and str(r.get("connectionStatus") or "").upper() == "CONNECTED":
                        status = "CONNECTED"
                        break
            connected = status == "CONNECTED"
        else:
            status = str(acc.get("connectionStatus") or "").upper()
            connected = status == "CONNECTED" and str(acc.get("state") or "").upper() == "DEPLOYED"

        region = str(acc.get("region") or self.region)
        if region:
            self.region = region
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
            "healed": bool(existing_id and existing_id != account_id),
            "pending": not connected,
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
        from goldbot.mt5.symbols import symbol_candidates

        last_err: Exception | None = None
        for sym in symbol_candidates(symbol):
            try:
                data = self._http(
                    "GET",
                    self._client_url(f"/users/current/accounts/{account_id}/symbols/{sym}/current-price", region),
                    timeout=20,
                )
                if isinstance(data, dict) and (data.get("bid") or data.get("ask") or data.get("price")):
                    data = dict(data)
                    data["symbol"] = sym
                    return data
            except Exception as e:
                last_err = e
                continue
        if last_err:
            log.warning("symbol_price failed: %s", last_err)
        return {}

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
        from goldbot.mt5.symbols import symbol_candidates

        action = "ORDER_TYPE_BUY" if side.lower() == "buy" else "ORDER_TYPE_SELL"
        last: dict = {"ok": False, "error": "no symbol worked", "mode": "metaapi"}
        for sym in symbol_candidates(symbol):
            payload: dict[str, Any] = {
                "actionType": action,
                "symbol": sym,
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
                last = {"ok": False, "error": e.message, "code": e.code, "mode": "metaapi", "details": e.details, "symbol": sym}
                # Unknown symbol → try next candidate
                msg = (e.message or "").lower()
                if "symbol" in msg or e.code in {"E_SYMBOL", "ValidationError"}:
                    continue
                return last

            numeric = resp.get("numericCode")
            string_code = str(resp.get("stringCode") or "")
            ok = (numeric in SUCCESS_CODES) or (string_code in SUCCESS_STRINGS)
            if not ok and isinstance(resp.get("numericCode"), (int, float)):
                ok = int(resp["numericCode"]) in SUCCESS_CODES
            ticket = resp.get("orderId") or resp.get("positionId") or 0
            try:
                ticket_i = int(ticket) if ticket not in (None, "") else 0
            except (TypeError, ValueError):
                ticket_i = 0
            last = {
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
                "symbol": sym,
                "comment": comment,
                "error": None if ok else (resp.get("message") or string_code or "trade failed"),
                "raw": resp,
            }
            if ok:
                # remember working Exness symbol for the desk
                try:
                    from goldbot.config import settings as _settings

                    _settings.symbol = sym
                except Exception:
                    pass
                return last
            # MARKET_UNKNOWN_SYMBOL style → try next
            if string_code in {"MARKET_UNKNOWN_SYMBOL", "TRADE_RETCODE_INVALID_FILL"} or "symbol" in (
                resp.get("message") or ""
            ).lower():
                continue
            return last
        return last

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
        aid = normalize_account_id(account_id)
        if not aid:
            return {
                "connected": False,
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "currency": "USD",
                "server": "",
                "login": 0,
                "detail": "معرّف حساب MetaApi تالف — أعد الربط الكامل",
                "error": "E_BAD_ACCOUNT_ID",
                "stale": True,
            }
        try:
            info = self.account_information(aid, region=region)
        except MetaApiError as e:
            stale = "not found" in (e.message or "").lower() or e.status == 404
            return {
                "connected": False,
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "currency": "USD",
                "server": "",
                "login": 0,
                "detail": arabic_metaapi_error(e),
                "error": e.code or ("E_NOT_FOUND" if stale else "ERROR"),
                "stale": stale,
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
