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

# Simple process-wide circuit breaker for MetaApi Client calls
_cb_failures = 0
_cb_open_until = 0.0
_CB_THRESHOLD = 6
_CB_COOLDOWN_SEC = 45.0


def _circuit_allow() -> bool:
    return time.time() >= _cb_open_until


def _circuit_success() -> None:
    global _cb_failures
    _cb_failures = 0


def _circuit_fail() -> None:
    global _cb_failures, _cb_open_until
    _cb_failures += 1
    if _cb_failures >= _CB_THRESHOLD:
        _cb_open_until = time.time() + _CB_COOLDOWN_SEC
        log.error("MetaApi circuit OPEN for %.0fs after %s failures", _CB_COOLDOWN_SEC, _cb_failures)
        _cb_failures = 0


_TF_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}


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


def is_validation_cooldown_error(exc: MetaApiError | Exception | str) -> bool:
    msg = str(getattr(exc, "message", None) or exc).lower()
    return "rejected too many times" in msg or "retry in 1 hour" in msg or "validation for trading account" in msg and "rejected" in msg


def normalize_exness_server(server: str | None) -> str:
    """Normalize Exness MT5 server names (trim, collapse spaces, fix common typos)."""
    s = str(server or "").strip()
    if not s:
        return ""
    # Common paste variants: spaces / underscores → Exness-MT5Real32
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    # ExnessMT5Real32 / exnessmt5real32
    s = re.sub(r"(?i)^exness-?mt5-?", "Exness-MT5", s)
    low = s.lower()
    if low.startswith("exness-mt5"):
        tail = s[len("Exness-MT5") :]
        # Drop leftover hyphen after MT5
        if tail.startswith("-"):
            tail = tail[1:]
        if tail.lower().startswith("trial"):
            num = re.sub(r"(?i)^trial-?", "", tail)
            return "Exness-MT5Trial" + num
        if tail.lower().startswith("real"):
            num = re.sub(r"(?i)^real-?", "", tail)
            return "Exness-MT5Real" + num
        return "Exness-MT5" + tail
    return s.replace("-", "") if " " in str(server or "") else s


def servers_compatible(a: str | None, b: str | None) -> bool:
    """True when two Exness server strings refer to the same terminal host."""
    na = normalize_exness_server(a) or str(a or "").strip()
    nb = normalize_exness_server(b) or str(b or "").strip()
    if not na or not nb:
        return False
    if na.lower() == nb.lower():
        return True
    return na.lower().replace("-", "") == nb.lower().replace("-", "")


def _suggested_servers_from_error(details: Any) -> list[str]:
    """Pull MetaApi E_SRV_NOT_FOUND suggested server names."""
    out: list[str] = []
    if not isinstance(details, dict):
        return out
    nested = details.get("details") if isinstance(details.get("details"), dict) else details
    if not isinstance(nested, dict):
        return out
    by_broker = nested.get("serversByBrokers") or {}
    if isinstance(by_broker, dict):
        for names in by_broker.values():
            if isinstance(names, list):
                for n in names:
                    if n and str(n) not in out:
                        out.append(str(n))
    for n in nested.get("suggestedServerNames") or nested.get("servers") or []:
        if n and str(n) not in out:
            out.append(str(n))
    return out


def arabic_metaapi_error(exc: MetaApiError | Exception) -> str:
    msg = str(getattr(exc, "message", None) or exc)
    code = str(getattr(exc, "code", "") or "")
    low = msg.lower()
    details = getattr(exc, "details", None)
    # Rate-limited by MetaApi after repeated bad credentials / wrong server
    if is_validation_cooldown_error(exc) or code == "E_VALIDATION_COOLDOWN":
        return (
            "MetaApi أوقف التحقق من هذا الحساب مؤقتاً بعد محاولات فاشلة كثيرة. "
            "تأكد من: كلمة مرور التداول (ليس Investor) + السيرفر حرفياً من Exness "
            "(مثل Exness-MT5Real32) ثم انتظر ساعة كاملة قبل «إعادة ربط كامل»."
        )
    if code == "E_SRV_NOT_FOUND" or ".dat file for server" in low:
        suggestions = _suggested_servers_from_error(details)
        hint = (" المقترحات: " + "، ".join(suggestions[:6])) if suggestions else ""
        return (
            "اسم السيرفر غير موجود في MetaApi — انسخه حرفياً من تطبيق Exness "
            f"(مثال Exness-MT5Real32).{hint}"
        )
    if code in {"E_AUTH", "UnauthorizedError"} or "authenticate" in low or "invalid account" in low or "wrong password" in low:
        return (
            "رفض Exness بيانات الدخول — تحقق من: رقم الحساب + كلمة مرور التداول "
            "(وليس Investor) + السيرفر حرفياً (مثل Exness-MT5Real32)."
        )
    if code == "ERR_OTP_REQUIRED" or "one-time password" in low or "otp" in low:
        return "الحساب يطلب OTP — عطّل كلمة المرور لمرة واحدة من تطبيق MetaTrader ثم أعد الربط."
    if code == "E_TRADING_ACCOUNT_DISABLED" or "account is disabled" in low:
        return "الوسيط يقول إن الحساب معطّل — فعّله من Exness أو استخدم حساباً آخر."
    if code == "E_PASSWORD_CHANGE_REQUIRED" or ("password" in low and "change" in low):
        return "Exness يطلب تغيير كلمة المرور — غيّرها من التطبيق الرسمي ثم أعد الربط."
    if code == "E_SERVER_TIMEZONE" or "retrieve server settings" in low:
        return "تعذّر اكتشاف إعدادات السيرفر — أعد المحاولة بعد دقيقة أو تحقق من اسم السيرفر."
    if code == "E_NO_SYMBOLS" or "no symbols" in low:
        return "لا رموز تداول على هذا الحساب — تأكد أنه حساب MT5 نشط لدى Exness."
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
    if code == "E_NOT_CONNECTED":
        return (
            "الطرفية السحابية أُنشئت لكن لم تتصل بـ Exness. "
            "غالباً كلمة مرور التداول أو السيرفر (مثل Exness-MT5Real32) غير صحيحة — صحّحها ثم «إعادة ربط كامل»."
        )
    if code == "E_SERVER_MISMATCH":
        return (
            "حساب MetaApi ما زال مربوطاً بسيرفر قديم (مثل Trial) بينما طلبت Real. "
            "اضغط «إعادة ربط كامل» ليُحدَّث السيرفر إلى Exness-MT5Real32."
        )
    if code == "E_PROVISION_PENDING" or "قيد التجهيز" in msg or "جاري تجهيز" in msg:
        return "الطرفية السحابية قيد التجهيز — انتظر دقيقة ثم اضغط «تحديث / إعادة ربط»."
    if "investor" in low:
        return "كلمة مرور Investor لا تكفي — استخدم كلمة مرور التداول من Exness."
    if "server" in low and ("not found" in low or "unknown" in low or "invalid" in low):
        return "اسم السيرفر غير مطابق — انسخه حرفياً من Exness (مثال Exness-MT5Real32)."
    if code == "NO_TOKEN" or "metaapi_token" in low or ("لا يوجد" in msg and "token" in low) or "unauthorized" in low:
        return "توكن MetaApi غير صالح أو غير محفوظ — الصقه مجدداً من تبويب الربط أو شاشة الدخول."
    if "timeout" in low or code == "NETWORK":
        return "انتهت مهلة الاتصال بـ MetaApi — أعد المحاولة بعد ثوانٍ."
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
            err = MetaApiError(
                payload.get("message") or payload.get("error") or f"MetaApi HTTP {e.code}",
                code=str(code) if code else payload.get("error"),
                status=int(e.code),
                details=payload,
            )
            log.error(
                "MetaApi HTTP %s %s → %s code=%s msg=%s",
                method.upper(),
                url.split("?")[0][-80:],
                e.code,
                err.code,
                (err.message or "")[:220],
            )
            raise err
        except urllib.error.URLError as e:
            log.error("MetaApi network error %s %s: %s", method.upper(), url.split("?")[0][-80:], e.reason)
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

    def find_accounts_by_login(self, login: str) -> list[dict]:
        login_s = str(login).strip()
        out: list[dict] = []
        for acc in self.list_accounts():
            if not isinstance(acc, dict):
                continue
            if str(acc.get("login") or "").strip() != login_s:
                continue
            acc_id = normalize_account_id(str(acc.get("id") or acc.get("accountId") or ""))
            if not acc_id:
                continue
            row = dict(acc)
            row["id"] = acc_id
            out.append(row)
        return out

    def find_account_by_login(self, login: str, server: str | None = None) -> dict | None:
        """Find MetaApi account for login.

        Prefer exact/normalized server match. Do NOT silently reuse a Trial account
        when the user switched to Real32 (that caused false «تعذّر الربط»).
        """
        login_s = str(login).strip()
        matches = self.find_accounts_by_login(login_s)
        if not matches:
            return None
        if server:
            for acc in matches:
                if servers_compatible(str(acc.get("server") or ""), server):
                    return acc
            # Different server for same login — return None so caller can migrate/update
            return None
        return matches[0]

    def update_account_server_password(
        self,
        account_id: str,
        *,
        password: str,
        server: str,
        name: str | None = None,
    ) -> dict:
        """Point an existing MetaApi terminal at a new Exness server + trading password."""
        aid = normalize_account_id(account_id)
        if not aid:
            raise MetaApiError(f"معرّف حساب MetaApi غير صالح: {account_id!r}", code="E_BAD_ACCOUNT_ID")
        server_n = normalize_exness_server(server) or str(server).strip()
        body: dict[str, Any] = {
            "password": str(password),
            "server": server_n,
            "name": name or f"AURUM-{server_n}",
        }
        # Undeploy first so MetaApi accepts server change on a live terminal
        try:
            self.undeploy(aid)
            time.sleep(1.5)
        except Exception as e:
            log.info("undeploy before server update: %s", e)
        data = self._http(
            "PUT",
            self._prov_url(f"/users/current/accounts/{aid}"),
            body,
            transaction=True,
            timeout=60,
        )
        return data if isinstance(data, dict) else {"ok": True}

    def migrate_account_server(
        self,
        account: dict,
        *,
        login: str,
        password: str,
        server: str,
        deploy_wait: float = 45.0,
    ) -> dict:
        """Move an existing MetaApi terminal from Trial/old server → requested server."""
        aid = normalize_account_id(str(account.get("id") or ""))
        if not aid:
            raise MetaApiError("لا يوجد معرّف للحساب عند ترحيل السيرفر", code="E_BAD_ACCOUNT_ID")
        old = str(account.get("server") or "")
        server_n = normalize_exness_server(server) or str(server).strip()
        log.warning(
            "metaapi migrate login=%s account=%s server %s → %s",
            login,
            aid,
            old,
            server_n,
        )
        self.update_account_server_password(
            aid,
            password=password,
            server=server_n,
            name=f"AURUM-{login}-{server_n}",
        )
        acc = self.redeploy(aid, wait=deploy_wait)
        # Prefer fresh read
        try:
            acc = self.get_account(aid)
        except Exception:
            pass
        if not servers_compatible(str(acc.get("server") or ""), server_n):
            # Some MetaApi responses omit server until deploy settles — patch locally
            acc = dict(acc)
            acc["server"] = server_n
            acc["id"] = aid
        return acc

    def create_account(
        self,
        login: str,
        password: str,
        server: str,
        *,
        name: str | None = None,
        symbol: str = "XAUUSDm",
        keywords: list[str] | None = None,
        resource_slots: int | None = None,
        fast: bool = False,
    ) -> dict:
        """Create cloud-g2 MT5 account with retries for broker detection / 202."""
        server_n = normalize_exness_server(server) or str(server).strip()
        body: dict[str, Any] = {
            "login": str(login).strip(),
            "password": str(password),
            "name": name or f"AURUM-{login}",
            "server": server_n,
            "platform": "mt5",
            "magic": self.magic,
            "type": "cloud-g2",
            "region": self.region,
            "reliability": "high",
            "manualTrades": False,
            "keywords": keywords
            or [
                "Exness",
                "Exness Technologies",
                "Exness Technologies Ltd",
                "Exness Ltd",
            ],
            "metadata": {"product": "AURUM", "symbol": symbol},
        }
        if resource_slots:
            body["resourceSlots"] = int(resource_slots)

        tx = secrets.token_hex(16)
        last_err: MetaApiError | None = None
        attempts = 4 if fast else 10
        tried_servers = {server_n.lower()}
        for attempt in range(attempts):
            try:
                data = self._http(
                    "POST",
                    self._prov_url("/users/current/accounts"),
                    body,
                    transaction_id=tx,
                    timeout=40 if fast else 100,
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
                # Auto-correct server from MetaApi suggestions (Exness Real32 etc.)
                if e.code == "E_SRV_NOT_FOUND" or ".dat file for server" in (e.message or "").lower():
                    for sug in _suggested_servers_from_error(e.details):
                        sug_n = normalize_exness_server(sug) or sug
                        if sug_n.lower() in tried_servers:
                            continue
                        if "exness" not in sug_n.lower():
                            continue
                        log.warning("metaapi server suggest %s → %s", body["server"], sug_n)
                        body["server"] = sug_n
                        tried_servers.add(sug_n.lower())
                        tx = secrets.token_hex(16)
                        break
                    else:
                        raise MetaApiError(e.message, code="E_SRV_NOT_FOUND", status=400, details=e.details) from e
                    continue
                # Hard fail fast on credential / server problems — do not spin for minutes
                msg = (e.message or "").lower()
                if is_validation_cooldown_error(e):
                    try:
                        from goldbot.storage.state import store

                        key = f"metaapi_cooldown:{str(login).strip()}:{str(body['server']).strip().lower()}"
                        store.set_kv(
                            key,
                            {
                                "until": time.time() + 3600,
                                "login": str(login).strip(),
                                "server": str(body["server"]).strip(),
                                "error": e.message,
                            },
                        )
                    except Exception:
                        pass
                    raise MetaApiError(e.message, code="E_VALIDATION_COOLDOWN", status=429, details=e.details) from e
                if e.code in {
                    "E_AUTH",
                    "UnauthorizedError",
                    "ERR_OTP_REQUIRED",
                    "E_TRADING_ACCOUNT_DISABLED",
                    "E_PASSWORD_CHANGE_REQUIRED",
                    "E_NO_SYMBOLS",
                } or any(
                    x in msg
                    for x in (
                        "wrong password",
                        "invalid password",
                        "authenticate",
                        "investor password",
                        "one-time password",
                        "account is disabled",
                    )
                ):
                    raise
                if e.code == "ACCEPTED" or e.status == 202:
                    wait = (3 + attempt * 2) if fast else (12 + attempt * 6)
                    log.info("metaapi create accepted, retry in %ss", wait)
                    time.sleep(wait)
                    # After 202, account may already exist — try find before retry POST
                    found = self.find_account_by_login(login, body["server"])
                    if found and is_metaapi_account_id(str(found.get("id") or "")):
                        return found
                    continue
                if "retry" in msg or "in progress" in msg or "detection" in msg:
                    time.sleep((4 + attempt * 2) if fast else (15 + attempt * 5))
                    found = self.find_account_by_login(login, body["server"])
                    if found and is_metaapi_account_id(str(found.get("id") or "")):
                        return found
                    continue
                raise
        # Last chance: broker detection may have created it despite timeout
        found = self.find_account_by_login(login, body.get("server") or server)
        if found and is_metaapi_account_id(str(found.get("id") or "")):
            return found
        raise last_err or MetaApiError("create account timed out")

    def deploy(self, account_id: str) -> dict:
        data = self._http("POST", self._prov_url(f"/users/current/accounts/{account_id}/deploy"), {}, transaction=True)
        return data if isinstance(data, dict) else {"ok": True}

    def undeploy(self, account_id: str) -> dict:
        try:
            data = self._http(
                "POST",
                self._prov_url(f"/users/current/accounts/{account_id}/undeploy"),
                {},
                transaction=True,
            )
            return data if isinstance(data, dict) else {"ok": True}
        except MetaApiError as e:
            if "already" in (e.message or "").lower():
                return {"ok": True}
            raise

    def redeploy(self, account_id: str, *, wait: float = 45.0) -> dict:
        """Undeploy then deploy — heals stuck DISCONNECTED Exness terminals."""
        try:
            self.undeploy(account_id)
            time.sleep(2)
        except Exception as e:
            log.info("undeploy before redeploy: %s", e)
        try:
            self.deploy(account_id)
        except MetaApiError as e:
            if "already" not in (e.message or "").lower():
                log.warning("redeploy deploy: %s", e.message)
        return self.ensure_deployed(account_id, max_wait=wait)

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
        symbol: str = "XAUUSDm",
        existing_id: str | None = None,
        wait: bool = True,
        fast: bool = False,
        deploy_wait: float | None = None,
        force_new: bool = False,
    ) -> dict:
        """Find or create cloud account; optionally wait until CONNECTED.

        Use fast=True for HTTP login paths (Render/Safari kill long requests).
        force_new=True skips find-by-login so «إعادة ربط كامل» creates a fresh terminal.
        """
        if not self.configured:
            raise MetaApiError(
                "METAAPI_TOKEN غير مضبوط — أضفه في التطبيق لربط Exness من السحابة بدون Windows",
                code="NO_TOKEN",
                status=503,
            )

        server = normalize_exness_server(server) or str(server).strip()
        login = str(login).strip()

        # Honor MetaApi "retry in 1 hour" lockout — per login+server only
        try:
            from goldbot.storage.state import store

            cool_key = f"metaapi_cooldown:{login}:{server.lower()}"
            cool = store.get_kv(cool_key) or {}
            until = float((cool or {}).get("until") or 0)
            if until > time.time():
                mins = max(1, int((until - time.time()) / 60))
                raise MetaApiError(
                    f"MetaApi ما زال يمنع التحقق من الحساب — انتظر حوالي {mins} دقيقة ثم أعد المحاولة بعد تصحيح كلمة المرور/السيرفر.",
                    code="E_VALIDATION_COOLDOWN",
                    status=429,
                    details=cool,
                )
        except MetaApiError:
            raise
        except Exception:
            pass

        acc = None
        migrated = False
        deploy_budget = deploy_wait if deploy_wait is not None else (10.0 if fast else 75.0)
        existing = "" if force_new else (normalize_account_id(existing_id) if is_metaapi_account_id(existing_id) else "")
        if existing_id and not force_new and not existing:
            log.warning("ignoring invalid metaapi_account_id=%r", existing_id)
        if existing:
            try:
                acc = self.get_account(existing)
            except MetaApiError as e:
                log.warning("stale metaapi account %s: %s — will recreate", existing, e.message)
                acc = None
            if acc and not servers_compatible(str(acc.get("server") or ""), server):
                try:
                    acc = self.migrate_account_server(
                        acc,
                        login=login,
                        password=password,
                        server=server,
                        deploy_wait=min(60.0, deploy_budget + 15),
                    )
                    migrated = True
                except MetaApiError as e:
                    log.error(
                        "existing-id server migrate failed %s→%s: %s — drop stale binding",
                        acc.get("server"),
                        server,
                        e.message,
                    )
                    acc = None
        if not acc and not force_new:
            acc = self.find_account_by_login(login, server)
        if not acc and not force_new:
            # Same login exists on a DIFFERENT server (Trial→Real32) — migrate, don't create
            siblings = self.find_accounts_by_login(login)
            if siblings:
                candidate = siblings[0]
                try:
                    acc = self.migrate_account_server(
                        candidate,
                        login=login,
                        password=password,
                        server=server,
                        deploy_wait=min(60.0, deploy_budget + 15),
                    )
                    migrated = True
                except MetaApiError as e:
                    log.error(
                        "sibling server migrate failed login=%s from=%s to=%s: %s",
                        login,
                        candidate.get("server"),
                        server,
                        e.message,
                    )
                    # Fall through to create — may hit "account already exists"
        if not acc:
            try:
                created = self.create_account(login, password, server, symbol=symbol, fast=fast)
            except MetaApiError as create_err:
                # Duplicate login / force_new race: reuse existing terminal + refresh password
                found = self.find_account_by_login(login, server)
                if found and is_metaapi_account_id(str(found.get("id") or "")):
                    acc = found
                    created = None
                else:
                    siblings = self.find_accounts_by_login(login)
                    if siblings and is_metaapi_account_id(str(siblings[0].get("id") or "")):
                        try:
                            acc = self.migrate_account_server(
                                siblings[0],
                                login=login,
                                password=password,
                                server=server,
                                deploy_wait=min(60.0, deploy_budget + 15),
                            )
                            migrated = True
                            created = None
                        except MetaApiError as e:
                            log.error("post-create migrate failed: %s", e.message)
                            raise create_err from e
                    else:
                        raise
            if not acc:
                account_id = normalize_account_id(str(created["id"]))
                if not account_id:
                    raise MetaApiError("MetaApi أعاد معرّفاً غير صالح بعد الإنشاء", code="E_BAD_ACCOUNT_ID")
                try:
                    acc = self.get_account(account_id)
                except MetaApiError as e:
                    # Race: account created but not yet readable — use create payload
                    if "not found" in (e.message or "").lower():
                        acc = {
                            "id": account_id,
                            "state": created.get("state") or "DEPLOYED",
                            "login": login,
                            "server": server,
                        }
                    else:
                        raise

        account_id = normalize_account_id(str((acc or {}).get("id") or ""))
        if not account_id:
            raise MetaApiError("الحساب الموجود بلا معرّف UUID صالح", code="E_BAD_ACCOUNT_ID")
        # Prefer region from the account itself (critical for client API)
        if acc.get("region"):
            self.region = str(acc["region"]).strip()
        # Password already set during migrate; still refresh on normal reuse
        if not migrated:
            try:
                self._http(
                    "PUT",
                    self._prov_url(f"/users/current/accounts/{account_id}/password"),
                    {"password": password},
                    transaction=True,
                )
            except MetaApiError as e:
                log.info("password update skipped: %s", e.message)

        deploy_budget = deploy_wait if deploy_wait is not None else (10.0 if fast else 75.0)
        try:
            acc = self.ensure_deployed(account_id, max_wait=deploy_budget)
        except MetaApiError as e:
            if "not found" in (e.message or "").lower():
                created = self.create_account(login, password, server, symbol=symbol, fast=fast)
                account_id = normalize_account_id(str(created["id"]))
                acc = self.ensure_deployed(account_id, max_wait=deploy_budget)
            else:
                raise

        # Heal stuck DISCONNECTED terminals (common after bad password / server switch)
        status0 = str(acc.get("connectionStatus") or "").upper()
        if status0 in {"DISCONNECTED", "DEPLOYING", ""} and not fast:
            try:
                acc = self.redeploy(account_id, wait=min(60.0, deploy_budget + 20))
            except Exception as e:
                log.warning("redeploy heal failed: %s", e)

        connected = False
        if wait:
            # Real servers often need longer than Trial to reach CONNECTED
            is_real = "real" in server.lower()
            wait_timeout = (35.0 if is_real else 25.0) if fast else float(
                settings.metaapi_connect_timeout if not is_real else max(settings.metaapi_connect_timeout, 150)
            )
            acc = self.wait_connected(account_id, timeout=wait_timeout)
            status = str(acc.get("connectionStatus") or "").upper()
            replicas = acc.get("accountReplicas") or acc.get("replicas") or []
            if not status and isinstance(replicas, list):
                for r in replicas:
                    if isinstance(r, dict) and str(r.get("connectionStatus") or "").upper() == "CONNECTED":
                        status = "CONNECTED"
                        break
            connected = status == "CONNECTED"
            # Full wait finished but still disconnected → surface real failure (not soft pending)
            if not connected and not fast:
                detail = (
                    acc.get("connectionError")
                    or acc.get("error")
                    or acc.get("message")
                    or "الطرفية السحابية لم تتصل بـ Exness"
                )
                raise MetaApiError(
                    str(detail),
                    code="E_NOT_CONNECTED",
                    status=400,
                    details=acc,
                )
        else:
            status = str(acc.get("connectionStatus") or "").upper()
            connected = status == "CONNECTED" and str(acc.get("state") or "").upper() == "DEPLOYED"

        region = str(acc.get("region") or self.region)
        if region:
            self.region = region
        # Clear cooldown on successful create/bind path
        if connected:
            try:
                from goldbot.storage.state import store

                store.set_kv(f"metaapi_cooldown:{login}:{server.lower()}", {"until": 0})
            except Exception:
                pass
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
            "healed": bool(existing_id and existing_id != account_id) or migrated,
            "migrated": migrated,
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

        if not _circuit_allow():
            raise MetaApiError("MetaApi circuit open — temporary backoff", code="E_CIRCUIT", status=503)
        last_err: Exception | None = None
        for sym in symbol_candidates(symbol):
            try:
                data = self._http(
                    "GET",
                    self._client_url(f"/users/current/accounts/{account_id}/symbols/{sym}/current-price", region),
                    timeout=12,
                )
                if isinstance(data, dict) and (data.get("bid") or data.get("ask") or data.get("price")):
                    data = dict(data)
                    data["symbol"] = sym
                    _circuit_success()
                    return data
            except Exception as e:
                last_err = e
                continue
        _circuit_fail()
        if last_err:
            log.warning("symbol_price failed: %s", last_err)
        return {}

    def candles(
        self,
        account_id: str,
        symbol: str,
        timeframe: str = "M15",
        *,
        count: int = 200,
        region: str | None = None,
    ) -> list[dict]:
        """Broker OHLC from MetaApi historical market data (not Yahoo/paper)."""
        from datetime import datetime, timedelta, timezone
        from urllib.parse import quote, urlencode

        from goldbot.mt5.symbols import symbol_candidates

        if not _circuit_allow():
            raise MetaApiError("MetaApi circuit open — temporary backoff", code="E_CIRCUIT", status=503)

        tf = _TF_MAP.get((timeframe or "M15").upper(), "15m")
        # Request a window large enough for `count` bars
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(tf, 15)
        start = datetime.now(timezone.utc) - timedelta(minutes=max(count + 5, 30) * minutes)
        start_s = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        limit = max(10, min(int(count), 1000))
        last_err: Exception | None = None
        for sym in symbol_candidates(symbol):
            qs = urlencode({"startTime": start_s, "limit": str(limit)})
            path = (
                f"/users/current/accounts/{account_id}/historical-market-data/"
                f"symbols/{quote(sym, safe='')}/timeframes/{tf}/candles?{qs}"
            )
            try:
                data = self._http("GET", self._client_url(path, region), timeout=25)
                if isinstance(data, list) and data:
                    _circuit_success()
                    return data
                if isinstance(data, dict) and isinstance(data.get("candles"), list) and data["candles"]:
                    _circuit_success()
                    return list(data["candles"])
            except Exception as e:
                last_err = e
                continue
        _circuit_fail()
        if last_err:
            raise MetaApiError(str(getattr(last_err, "message", last_err)), code=getattr(last_err, "code", "E_CANDLES"))
        return []

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
        symbol: str = "XAUUSDm",
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
            # Prefer positionId for closes; keep orderId separately
            pos_raw = resp.get("positionId") or resp.get("orderId") or 0
            ord_raw = resp.get("orderId")
            try:
                ticket_i = int(pos_raw) if pos_raw not in (None, "") else 0
            except (TypeError, ValueError):
                ticket_i = 0
            # Resolve fill / open price so desk never stores null entry
            fill_price = 0.0
            for key in ("openPrice", "price", "averagePrice", "fillPrice", "currentPrice"):
                if resp.get(key) not in (None, ""):
                    try:
                        fill_price = float(resp[key])
                        break
                    except (TypeError, ValueError):
                        pass
            if ok and fill_price <= 0:
                try:
                    pos_id = resp.get("positionId") or resp.get("orderId")
                    if pos_id:
                        for p in self.positions(account_id, region=region):
                            if str(p.get("id") or p.get("positionId") or "") == str(pos_id):
                                fill_price = float(p.get("openPrice") or p.get("price") or 0)
                                break
                    if fill_price <= 0:
                        px = self.symbol_price(account_id, sym, region=region)
                        fill_price = float(px.get("ask") or px.get("bid") or px.get("price") or 0)
                except Exception:
                    pass
            if ok and fill_price <= 0:
                # Broker may have filled — do not store entry=0 (breaks R / exits)
                last = {
                    "ok": False,
                    "mode": "metaapi",
                    "execution": "metaapi",
                    "side": side,
                    "lot": float(lot),
                    "price": 0.0,
                    "entry": 0.0,
                    "sl": float(sl or 0),
                    "tp": float(tp or 0),
                    "ticket": ticket_i,
                    "order_id": ord_raw,
                    "position_id": resp.get("positionId"),
                    "retcode": numeric,
                    "string_code": string_code,
                    "symbol": sym,
                    "comment": comment,
                    "error": "filled_no_price",
                    "detail": "تم التنفيذ على الوسيط لكن تعذّر قراءة سعر الدخول — راجع الصفقات في Exness",
                    "raw": resp,
                }
                return last
            last = {
                "ok": ok,
                "mode": "metaapi",
                "execution": "metaapi",
                "side": side,
                "lot": float(lot),
                "price": fill_price,
                "entry": fill_price,
                "sl": float(sl or 0),
                "tp": float(tp or 0),
                "ticket": ticket_i,
                "order_id": ord_raw,
                "position_id": resp.get("positionId") or (str(pos_raw) if pos_raw else None),
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

    def close_position(
        self,
        account_id: str,
        position_id: str | int,
        region: str | None = None,
        volume: float | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"actionType": "POSITION_CLOSE_ID", "positionId": str(position_id)}
        if volume is not None and float(volume) > 0:
            payload["volume"] = float(volume)
        try:
            resp = self.trade(account_id, payload, region=region)
        except MetaApiError as e:
            msg = (e.message or "").lower()
            # Broker already closed (SL/TP) — treat as success so local book can settle
            if "not found" in msg or "does not exist" in msg or e.code in {"NotFoundError", "E_POSITION_NOT_FOUND"}:
                return {"ok": True, "already_closed": True, "error": None, "code": e.code}
            return {"ok": False, "error": e.message, "code": e.code}
        numeric = resp.get("numericCode")
        string_code = str(resp.get("stringCode") or "")
        ok = (numeric in SUCCESS_CODES) or (string_code in SUCCESS_STRINGS)
        msg = str(resp.get("message") or "").lower()
        if not ok and ("not found" in msg or "does not exist" in msg):
            return {"ok": True, "already_closed": True, "raw": resp, "error": None}
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
