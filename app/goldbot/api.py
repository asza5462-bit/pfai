"""AURUM FastAPI control plane — auth + elite gold desk."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from goldbot import PRODUCT_NAME, PRODUCT_TAGLINE, __version__
from goldbot.auth.users import SESSION_COOKIE, AuthError, auth
from goldbot.config import settings
from goldbot.execution.desk import desk
from goldbot.mt5.bridge import bridge
from goldbot.mt5.metaapi_cloud import (
    MetaApiError,
    arabic_metaapi_error,
    is_metaapi_account_id,
    is_validation_cooldown_error,
    is_validation_failed_error,
    metaapi,
    normalize_account_id,
    normalize_broker_server,
    servers_compatible,
)
from goldbot.mt5.ctrader_cloud import CTraderError, arabic_ctrader_error, ctrader
from goldbot.mt5.mt5_linux import Mt5LinuxError, mt5_linux
from goldbot.mt5.remote_hub import hub
from goldbot.mt5.broker import (
    BROKER_CLIENT_AREA,
    BROKER_ID,
    BROKER_NAME,
    BROKER_PLATFORM,
    BROKER_PORTAL,
    BROKER_SERVERS,
    DEFAULT_CTRADER_SERVER,
    DEFAULT_SERVER,
    DEFAULT_SYMBOL,
    resolve_fp_server,
)
from goldbot.storage.state import store
from goldbot.util_rate import limiter

log = logging.getLogger("aurum.api")
STATIC = Path(__file__).resolve().parent / "static"
_bg_lock = threading.Lock()
_bg_jobs: set[str] = set()


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_or_429(key: str, *, limit: int = 8, window_sec: float = 60.0) -> None:
    # Disable under pytest / explicit opt-out so unit tests don't collide on shared limiter
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("AURUM_DISABLE_RATE_LIMIT") == "1":
        return
    ok, retry = limiter.allow(key, limit=limit, window_sec=window_sec)
    if not ok:
        raise HTTPException(
            429,
            f"محاولات كثيرة — انتظر {int(retry) + 1} ثانية ثم أعد المحاولة.",
        )


async def _provision_cloud_async(
    user_id: int,
    login: str,
    password: str,
    server: str,
    symbol: str,
    existing_id: str | None,
    *,
    timeout_sec: float = 22.0,
    force_new: bool = False,
) -> dict:
    """Non-blocking wrapper — keeps uvicorn event loop responsive during MetaApi provision."""
    return await asyncio.to_thread(
        _provision_cloud_fast,
        user_id,
        login,
        password,
        server,
        symbol,
        existing_id,
        timeout_sec=timeout_sec,
        force_new=force_new,
    )


def _set_provision_state(status: str, message: str, **extra: Any) -> None:
    import time as _time

    payload = {
        "status": status,  # pending | ok | error
        "message": message,
        "ts": _time.time(),
        **extra,
    }
    store.set_kv("metaapi_provision_state", payload)
    if status == "error":
        store.set_kv("metaapi_last_error", {"error": message, "code": extra.get("code"), "ts": payload["ts"]})


def _get_provision_state() -> dict:
    import time as _time

    st = store.get_kv("metaapi_provision_state") or {}
    if not isinstance(st, dict):
        return {}
    # Stale pending older than 3 minutes → surface as error so UI is not stuck forever
    if st.get("status") == "pending" and (_time.time() - float(st.get("ts") or 0)) > 180:
        return {
            **st,
            "status": "error",
            "message": (
                st.get("message")
                or "انتهت مهلة تجهيز الطرفية السحابية. تحقق من كلمة مرور التداول والسيرفر ثم اضغط «إعادة ربط كامل»."
            ),
            "stale": True,
        }
    return st


def _apply_cloud_binding(user_id: int, cloud: dict) -> None:
    auth.update_settings(
        user_id,
        {
            "metaapi_account_id": cloud["account_id"],
            "metaapi_region": cloud.get("region") or settings.metaapi_region,
            "execution": "metaapi",
            "mode": "mt5",
        },
    )
    settings.mode = "mt5"
    if cloud.get("region"):
        settings.metaapi_region = str(cloud.get("region") or settings.metaapi_region)
    bridge.bind_metaapi(cloud["account_id"], cloud.get("region"))
    bridge.mode = "mt5"
    bridge.execution = "metaapi"


def _finish_cloud_in_background(
    user_id: int,
    login: str,
    password: str,
    server: str,
    symbol: str,
    account_id: str,
) -> None:
    """Complete MetaApi deploy/connect after the HTTP response (avoids Safari Load failed)."""
    job_key = f"{user_id}:{account_id or login}"
    with _bg_lock:
        if job_key in _bg_jobs:
            return
        _bg_jobs.add(job_key)

    def _run() -> None:
        try:
            _set_provision_state("pending", "جاري إكمال اتصال MetaApi بـ FP Markets…", login=login, server=server)
            cloud = metaapi.ensure_account(
                str(login),
                password,
                server,
                symbol=symbol or "XAUUSD",
                existing_id=account_id or None,
                wait=True,
                fast=False,
                deploy_wait=90.0,
            )
            _apply_cloud_binding(user_id, cloud)
            desk.account = bridge.connect()
            if desk.account.connected:
                _set_provision_state(
                    "ok",
                    "متصل بسحابة FP Markets — التنفيذ الحقيقي جاهز",
                    account_id=cloud["account_id"],
                    connected=True,
                )
            else:
                _set_provision_state(
                    "pending",
                    "الطرفية أُنشئت وبانتظار اتصال الوسيط — حدّث خلال 30 ثانية",
                    account_id=cloud["account_id"],
                    connected=False,
                )
            if desk.account.connected and not desk.auto_trade:
                if desk.risk.state.halted:
                    desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="bg_cloud_ready")
                try:
                    desk.start_desk()
                except Exception as e:
                    log.warning("bg start_desk: %s", e)
            store.log_event(
                "metaapi_bg_ready",
                {"user_id": user_id, "account_id": cloud["account_id"], "connected": cloud.get("connected")},
            )
        except Exception as e:
            msg = arabic_metaapi_error(e) if isinstance(e, MetaApiError) else str(e)
            log.warning("background metaapi finish failed: %s", e)
            code = getattr(e, "code", None)
            if is_validation_cooldown_error(e):
                code = "E_VALIDATION_COOLDOWN"
            _set_provision_state("error", msg, code=code, login=login, server=server)
            store.log_event("metaapi_bg_error", {"user_id": user_id, "error": str(e), "code": code})
        finally:
            with _bg_lock:
                _bg_jobs.discard(job_key)

    threading.Thread(target=_run, name=f"aurum-cloud-{user_id}", daemon=True).start()


def _provision_cloud_fast(
    user_id: int,
    login: str,
    password: str,
    server: str,
    symbol: str,
    existing_id: str | None,
    *,
    timeout_sec: float = 22.0,
    force_new: bool = False,
) -> dict:
    """Run MetaApi provisioning with a hard timeout so Render/Safari do not drop the request."""
    job_key = f"fast:{user_id}:{str(login).strip()}"
    with _bg_lock:
        if job_key in _bg_jobs:
            raise MetaApiError(
                "ربط سحابي جارٍ بالفعل لهذا الحساب — انتظر قليلاً ثم حدّث الحالة.",
                code="E_PROVISION_PENDING",
                status=202,
            )
        _bg_jobs.add(job_key)

    box: dict = {}
    _set_provision_state("pending", "جاري إنشاء الطرفية السحابية على MetaApi…", login=login, server=server)

    def _call() -> None:
        try:
            cloud = metaapi.ensure_account(
                str(login),
                password,
                server,
                symbol=symbol or "XAUUSD",
                existing_id=None if force_new else existing_id,
                wait=False,
                fast=True,
                deploy_wait=6.0,
                force_new=force_new,
            )
            _apply_cloud_binding(user_id, cloud)
            box["cloud"] = cloud
            _set_provision_state(
                "pending" if not cloud.get("connected") else "ok",
                (
                    "تم إنشاء الطرفية — جاري الاتصال بـ FP Markets…"
                    if not cloud.get("connected")
                    else "متصل بسحابة FP Markets — التنفيذ الحقيقي جاهز"
                ),
                account_id=cloud.get("account_id"),
                connected=bool(cloud.get("connected")),
            )
            if not cloud.get("connected"):
                # Same thread finishes CONNECTED so a timed-out HTTP request still completes binding
                try:
                    done = metaapi.ensure_account(
                        str(login),
                        password,
                        server,
                        symbol=symbol or "XAUUSD",
                        existing_id=cloud["account_id"],
                        wait=True,
                        fast=False,
                        deploy_wait=90.0,
                    )
                    _apply_cloud_binding(user_id, done)
                    desk.account = bridge.connect()
                    box["cloud"] = done
                    _set_provision_state(
                        "ok" if done.get("connected") or desk.account.connected else "pending",
                        (
                            "متصل بسحابة FP Markets — التنفيذ الحقيقي جاهز"
                            if done.get("connected") or desk.account.connected
                            else "الطرفية جاهزة وبانتظار اتصال الوسيط"
                        ),
                        account_id=done.get("account_id"),
                        connected=bool(done.get("connected") or desk.account.connected),
                    )
                except Exception as e:
                    msg = arabic_metaapi_error(e) if isinstance(e, MetaApiError) else str(e)
                    log.warning("post-provision connect: %s", e)
                    _set_provision_state("error", msg, code=getattr(e, "code", None))
                    box["error"] = e
        except Exception as e:
            box["error"] = e
            msg = arabic_metaapi_error(e) if isinstance(e, MetaApiError) else str(e)
            _set_provision_state("error", msg, code=getattr(e, "code", None), login=login, server=server)
        finally:
            # Always release when THIS thread ends (including after HTTP early-return pending)
            with _bg_lock:
                _bg_jobs.discard(job_key)

    t = threading.Thread(target=_call, name=f"aurum-provision-{user_id}", daemon=True)
    t.start()
    t.join(timeout=float(timeout_sec))

    if "cloud" in box:
        cloud = box["cloud"]
        if not cloud.get("connected") and t.is_alive():
            cloud = dict(cloud)
            cloud["pending"] = True
            # Thread keeps job_key until it finishes CONNECTED wait
            return cloud
        return cloud

    if t.is_alive():
        # Creation still running — do not start a second job; thread owns job_key
        raise MetaApiError(
            "جاري تجهيز الطرفية السحابية — أكملنا الحفظ وستكتمل خلال دقيقة. حدّث من تبويب الربط.",
            code="E_PROVISION_PENDING",
            status=202,
        )

    err = box.get("error")
    if isinstance(err, MetaApiError):
        raise err
    if err:
        raise MetaApiError(str(err), code="E_PROVISION")
    raise MetaApiError("تعذّر إكمال الربط السحابي", code="E_PROVISION")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load MetaApi token / Linux executor / cTrader from env or app-saved store
    metaapi.refresh_token()
    mt5_linux.refresh()
    ctrader.refresh()
    # Always disarm on boot — user must press «ابدأ» after live connect.
    # Prevents KV auto_trade=True + AURUM_MODE=paper from paper-filling after redeploy.
    try:
        store.set_kv("auto_trade", False)
    except Exception:
        pass
    desk.armed = False
    # Re-bind cTrader on boot when OAuth+account already saved (survives redeploy if disk persists)
    try:
        if settings.prefer_ctrader and ctrader.ready:
            bridge.bind_ctrader(ctrader.account_id)
            bridge.mode = "mt5"
            settings.mode = "mt5"
            desk.account = bridge.connect()
            log.info(
                "cTrader rebound on boot account=%s connected=%s",
                ctrader.account_id,
                getattr(desk.account, "connected", False),
            )
    except Exception as e:
        log.warning("ctrader boot rebind skipped: %s", e)
    if auth.using_default_secret:
        log.warning(
            "AURUM_AUTH_SECRET is default — set a strong secret in Render env before production use"
        )
    if str(settings.data_dir).startswith("/tmp") or "ephemeral" in str(settings.data_dir).lower():
        log.warning("AURUM_DATA_DIR looks ephemeral: %s", settings.data_dir)
    desk.start_background()
    log.info(
        "AURUM desk online v%s mode=%s symbol=%s primary=ctrader ctrader=%s ready=%s data=%s",
        __version__,
        settings.mode,
        settings.symbol,
        ctrader.configured,
        ctrader.ready,
        settings.data_dir,
    )
    yield
    desk.stop_background()
    bridge.shutdown()


app = FastAPI(title=PRODUCT_NAME, version=__version__, description=PRODUCT_TAGLINE, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")


class RegisterBody(BaseModel):
    username: str
    password: str
    password_confirm: str


class LoginBody(BaseModel):
    username: str
    password: str


class Mt5LoginBody(BaseModel):
    mt5_login: str
    mt5_password: str
    mt5_server: str = DEFAULT_SERVER
    symbol: str = DEFAULT_SYMBOL
    auto_start: bool = True
    metaapi_token: str | None = None  # optional — paste once to unlock cloud trading


class MetaApiTokenBody(BaseModel):
    token: str = Field(..., min_length=10, description="MetaApi auth token from app.metaapi.cloud")
    region: str | None = None
    check_token: bool = True


class Mt5LinuxBody(BaseModel):
    base_url: str = Field(..., min_length=8, description="https://your-linux-host:5001")
    token: str = ""
    probe: bool = True


class AutoTradeBody(BaseModel):
    enabled: bool = False


class ExecuteBody(BaseModel):
    force: bool = Field(False, description="Bypass auto_trade flag (still respects risk halt)")


class SettingsBody(BaseModel):
    mt5_login: str | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None
    symbol: str | None = None
    mode: str | None = None


class BridgeHeartbeatBody(BaseModel):
    info: dict = Field(default_factory=dict)
    account: dict = Field(default_factory=dict)


class BridgeCompleteBody(BaseModel):
    command_id: int
    result: dict = Field(default_factory=dict)


def _set_session(resp: Response, token: str) -> None:
    secure = os.getenv("AURUM_COOKIE_SECURE", "1") == "1"
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(os.getenv("AURUM_SESSION_TTL", "604800")),
        path="/",
    )


def _clear_session(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/")


def _token_from(authorization: str | None, cookie: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return cookie


def require_user(authorization: str | None = None, aurum_session: str | None = None) -> dict:
    token = _token_from(authorization, aurum_session)
    user = auth.user_from_token(token)
    if not user:
        raise HTTPException(401, "يلزم تسجيل الدخول")
    return user


@app.api_route("/", methods=["GET", "HEAD"])
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/aurum_fpmarkets_agent.py")
async def download_agent():
    path = STATIC / "aurum_fpmarkets_agent.py"
    return FileResponse(path, filename="aurum_fpmarkets_agent.py", media_type="text/x-python")


@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health():
    """Fast liveness — no external broker calls (avoid Render free-tier wake delays)."""
    try:
        meta_ok = bool(getattr(metaapi, "token", None) or settings.metaapi_token)
    except Exception:
        meta_ok = False
    try:
        ct_cfg = bool(ctrader.client_id and ctrader.client_secret) if hasattr(ctrader, "client_id") else False
        ct_ready = bool(ct_cfg and getattr(ctrader, "access_token", None) and getattr(ctrader, "account_id", None))
    except Exception:
        ct_cfg, ct_ready = False, False
    try:
        linux_ok = bool(getattr(mt5_linux, "base_url", None))
    except Exception:
        linux_ok = False
    live = bool(
        bridge.execution in {"metaapi", "ctrader", "mt5_linux", "windows_bridge"}
        and desk.account.connected
        and desk.account.mode == "mt5"
    )
    return {
        "ok": True,
        "degraded": False,
        "product": PRODUCT_NAME,
        "broker": BROKER_NAME,
        "broker_id": BROKER_ID,
        "broker_platform": BROKER_PLATFORM,
        "broker_portal": BROKER_PORTAL,
        "version": __version__,
        "symbol": settings.symbol,
        "mode": desk.account.mode,
        "auto_trade": desk.auto_trade,
        "state": desk.state,
        "tick_seconds": settings.tick_seconds,
        "primary": "ctrader",
        "ctrader_server": DEFAULT_CTRADER_SERVER,
        "metaapi_configured": bool(meta_ok and settings.prefer_metaapi),
        "ctrader_configured": ct_cfg,
        "ctrader_ready": ct_ready,
        "mt5_linux_configured": bool(linux_ok and settings.prefer_mt5_linux),
        "execution": bridge.execution or desk.account.mode,
        "live_execution": live,
        "real_orders_only": True,
        "auth_secret_default": bool(getattr(auth, "using_default_secret", False)),
        "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count()},
    }


@app.get("/api/setup-next")
async def setup_next():
    """Public next-step guide — cTrader Open API is the primary path."""
    ctrader.refresh()
    if desk.account.connected and desk.account.mode == "mt5" and bridge.execution == "ctrader":
        step = "ready"
        next_ar = "cTrader متصل — اضغط «ابدأ التداول» من المكتب."
    elif ctrader.ready:
        step = "ctrader_ready"
        next_ar = "cTrader جاهز — اضغط «ابدأ التداول» (حساب FP Markets على منصة cTrader)."
    elif ctrader.configured and ctrader.access_token:
        step = "ctrader_select_account"
        next_ar = "اختر حساب cTrader من تبويب الربط."
    elif ctrader.configured:
        step = "ctrader_oauth"
        next_ar = "اضغط «تفويض cTrader» ثم اختر الحساب."
    else:
        step = "ctrader_app"
        next_ar = "من تبويب الربط: احفظ Client ID/Secret من openapi.ctrader.com ثم فوّض واختر الحساب."
    return {
        "ok": True,
        "step": step,
        "next_ar": next_ar,
        "primary": "ctrader",
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "metaapi_configured": False,
        "mt5_linux_configured": False,
        "ctrader_signup": "https://openapi.ctrader.com",
        "default_symbol": DEFAULT_SYMBOL,
        "version": __version__,
    }


@app.get("/api/auth/status")
async def auth_status(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = auth.user_from_token(_token_from(authorization, aurum_session))
    return {
        "needs_setup": auth.needs_setup(),
        "open_register": os.getenv("AURUM_OPEN_REGISTER", "1") == "1" or auth.needs_setup(),
        "authenticated": bool(user),
        "user": user,
    }


@app.post("/api/auth/register")
async def register(body: RegisterBody, response: Response, request: Request):
    _rate_or_429(f"register:{_client_ip(request)}", limit=5, window_sec=300)
    try:
        result = auth.register(body.username, body.password, body.password_confirm)
    except AuthError as e:
        raise HTTPException(e.code, e.message)
    _set_session(response, result["token"])
    store.log_event("auth_register", {"username": result["user"]["username"], "role": result["user"]["role"]})
    return {"ok": True, **result}


@app.post("/api/auth/login")
async def login(body: LoginBody, response: Response, request: Request):
    _rate_or_429(f"login:{_client_ip(request)}:{body.username}", limit=10, window_sec=120)
    try:
        result = auth.login(body.username, body.password)
    except AuthError as e:
        raise HTTPException(e.code, e.message)
    _set_session(response, result["token"])
    store.log_event("auth_login", {"username": result["user"]["username"]})
    return {"ok": True, **result}


@app.get("/api/broker/servers")
async def broker_servers():
    from goldbot.mt5.symbols import GOLD_SYMBOLS

    return {
        "broker": BROKER_NAME,
        "servers": BROKER_SERVERS,
        "default": DEFAULT_SERVER,
        "allow_custom": True,
        "hint_ar": "انسخ اسم السيرفر حرفياً من بوابة FP Markets أو بريد فتح الحساب (مثل FPMarkets-Live).",
        "symbols": list(GOLD_SYMBOLS),
        "default_symbol": DEFAULT_SYMBOL,
    }


@app.post("/api/auth/mt5-login")
async def mt5_login(body: Mt5LoginBody, response: Response, request: Request):
    """Login with FP Markets/MT5 — provision MetaApi cloud terminal (no Windows)."""
    _rate_or_429(f"mt5:{_client_ip(request)}:{body.mt5_login}", limit=6, window_sec=180)
    try:
        result = auth.login_with_mt5(body.mt5_login, body.mt5_password, body.mt5_server, body.symbol)
    except AuthError as e:
        raise HTTPException(e.code, e.message)
    user = result["user"]
    _set_session(response, result["token"])

    # Optional one-shot MetaApi token from the login form
    if body.metaapi_token and body.metaapi_token.strip():
        try:
            from goldbot.mt5.metaapi_cloud import save_stored_token

            save_stored_token(body.metaapi_token.strip())
            metaapi.set_token(body.metaapi_token.strip())
            metaapi.validate_token()
        except MetaApiError as e:
            raise HTTPException(400, f"توكن MetaApi غير صالح: {e.message}")

    metaapi.refresh_token()
    secrets = auth.mt5_secrets(user["id"])
    settings.mode = "mt5"
    settings.symbol = secrets["symbol"] or "XAUUSD"
    settings.mt5_login = secrets["login"]
    settings.mt5_password = secrets["password"]
    settings.mt5_server = secrets["server"]
    bridge.bind_remote_user(user["id"])

    cloud: dict = {"ok": False, "configured": metaapi.configured}
    message = ""
    cloud_ok = False
    if metaapi.configured and settings.prefer_metaapi:
        try:
            cloud = await _provision_cloud_async(
                user["id"],
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                settings.symbol,
                secrets.get("metaapi_account_id") or None,
                timeout_sec=28.0,
            )
            if cloud.get("connected"):
                cloud_ok = True
                message = "تم الربط السحابي المباشر بـ FP Markets عبر MetaApi — التنفيذ الحقيقي من التطبيق بدون Windows."
            else:
                message = (
                    "تم حفظ الحساب وبدء الطرفية السحابية لـ "
                    f"{secrets['server']}. الاتصال بالوسيط قد يستغرق حتى دقيقتين — "
                    "لا تغلق الصفحة؛ راقب تبويب الربط."
                )
                cloud = {**cloud, "ok": True, "pending": True}
        except MetaApiError as e:
            # Clear corrupt MetaApi ids (e.g. numeric 1215) so next attempt recreates
            if "not found" in (e.message or "").lower() or e.code in {"E_BAD_ACCOUNT_ID", "NotFoundError"}:
                auth.update_settings(user["id"], {"metaapi_account_id": "", "execution": ""})
                bridge.metaapi_account_id = ""
            if e.code == "E_PROVISION_PENDING":
                cloud = {"ok": True, "configured": True, "pending": True, "code": e.code}
                message = e.message
            else:
                message = arabic_metaapi_error(e)
                log.error(
                    "metaapi login failed user=%s login=%s server=%s code=%s msg=%s",
                    user["username"],
                    secrets["login"],
                    secrets["server"],
                    e.code,
                    e.message,
                )
                cloud = {
                    "ok": False,
                    "configured": True,
                    "error": e.message,
                    "error_code": e.code,
                    "code": e.code,
                    "details": e.details,
                }
                store.set_kv(
                    "metaapi_last_error",
                    {
                        "error": message,
                        "raw": e.message,
                        "code": e.code,
                        "ts": time.time(),
                        "server": secrets["server"],
                        "login": secrets["login"],
                    },
                )
                _set_provision_state("error", message, code=e.code, login=secrets["login"], server=secrets["server"])
            store.log_event("metaapi_login_error", {"user": user["username"], "error": e.message, "code": e.code})
    else:
        message = (
            "حساب FP Markets محفوظ. للصق توكن MetaApi من تبويب «ربط FP Markets السحابي» "
            "أو من حقل التوكن في شاشة الدخول — بعدها يبدأ التنفيذ الحقيقي بدون Windows."
        )

    desk.account = bridge.connect()
    cloud_ok = cloud_ok or bool(desk.account.connected)
    # Refresh public user with metaapi fields
    result["user"] = auth.public_user(user["id"])

    started = None
    if body.auto_start and desk.account.connected:
        if desk.risk.state.halted:
            desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="mt5_login_reset")
        started = desk.start_desk()

    store.log_event(
        "mt5_login",
        {
            "user": user["username"],
            "login": secrets["login"],
            "server": secrets["server"],
            "execution": bridge.execution or "pending",
            "metaapi_account_id": bridge.metaapi_account_id,
            "connected": desk.account.connected,
            "cloud_ok": cloud_ok,
        },
    )
    cloud_status = _cloud_status_for_user(user["id"])
    return {
        "ok": True,
        "cloud_ok": cloud_ok,
        "live_execution": bool(desk.account.connected and bridge.is_live_execution()),
        **result,
        "cloud": cloud,
        "bridge": cloud_status,  # UI uses this pill — now cloud-first
        "account": desk.account.to_dict(),
        "started": started,
        "execution": bridge.execution or ("metaapi" if bridge.metaapi_account_id else "pending"),
        "message": message,
        "error_code": cloud.get("error_code") or cloud.get("code"),
        "provision": _get_provision_state(),
    }


def _ctrader_pending_status() -> dict:
    ctrader.refresh()
    detail = (
        f"احفظ Client ID/Secret من openapi.ctrader.com لربط {BROKER_NAME}"
        if not ctrader.configured
        else (
            "اضغط «تفويض cTrader» وسجّل دخول حساب FP Markets"
            if not ctrader.access_token
            else "اختر حساب FP Markets cTrader من القائمة"
        )
    )
    return {
        "online": False,
        "execution": "ctrader",
        "provider": "ctrader",
        "broker": BROKER_NAME,
        "account_id": ctrader.account_id,
        "detail": detail,
        "windows_required": False,
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": False,
        "has_token": bool(ctrader.access_token),
    }


def _cloud_status_for_user(user_id: int) -> dict:
    """Status for desk connect pill — cTrader/FP Markets is the primary product path."""
    secrets = auth.mt5_secrets(user_id)
    exec_pref = str(secrets.get("execution") or bridge.execution or "").strip()
    ctrader.refresh()

    # Live cTrader always wins
    if ctrader.ready or exec_pref == "ctrader":
        if ctrader.ready:
            try:
                snap = ctrader.snapshot()
            except CTraderError as e:
                return {
                    "online": False,
                    "execution": "ctrader",
                    "provider": "ctrader",
                    "broker": BROKER_NAME,
                    "account_id": ctrader.account_id,
                    "detail": arabic_ctrader_error(e),
                    "windows_required": False,
                    "ctrader_configured": ctrader.configured,
                    "ctrader_ready": False,
                }
            online = bool(snap.get("connected"))
            if online:
                bridge.bind_ctrader(ctrader.account_id)
                bridge.mode = "mt5"
            return {
                "online": online,
                "execution": "ctrader",
                "provider": "ctrader",
                "broker": BROKER_NAME,
                "account_id": ctrader.account_id,
                "account": snap,
                "detail": snap.get("detail")
                or (f"متصل بـ {BROKER_NAME} عبر cTrader" if online else "cTrader غير متصل"),
                "windows_required": False,
                "ctrader_configured": True,
                "ctrader_ready": online,
            }
        return _ctrader_pending_status()

    # Legacy MetaApi only when explicitly preferred/enabled
    if settings.prefer_metaapi:
        raw_id = secrets.get("metaapi_account_id") or bridge.metaapi_account_id
        account_id = normalize_account_id(raw_id) if is_metaapi_account_id(raw_id) else ""
        metaapi.refresh_token()
        if account_id and metaapi.configured:
            if bridge.metaapi_account_id != account_id:
                bridge.bind_metaapi(account_id, secrets.get("metaapi_region") or settings.metaapi_region)
            snap = metaapi.snapshot(
                account_id,
                region=(secrets.get("metaapi_region") or settings.metaapi_region) or None,
            )
            online = bool(snap.get("connected"))
            return {
                "online": online,
                "execution": "metaapi",
                "provider": "metaapi",
                "account_id": account_id,
                "account": snap,
                "detail": snap.get("detail") or ("متصل سحابياً" if online else "غير متصل"),
                "windows_required": False,
            }
        if metaapi.configured and exec_pref == "metaapi":
            return {
                "online": False,
                "execution": "pending",
                "provider": "metaapi",
                "detail": "توكن MetaApi جاهز — أعد ربط الحساب",
                "windows_required": False,
            }

    # Default product guidance: cTrader / FP Markets
    return _ctrader_pending_status()


@app.post("/api/auth/logout")
async def logout(response: Response, authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    auth.logout(_token_from(authorization, aurum_session))
    _clear_session(response)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    return {"ok": True, "user": require_user(authorization, aurum_session)}


@app.post("/api/settings")
async def save_settings(
    body: SettingsBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    try:
        updated = auth.update_settings(user["id"], body.model_dump(exclude_none=True))
    except AuthError as e:
        raise HTTPException(e.code, e.message)

    # Apply mode/symbol to live desk config for this process
    secrets = auth.mt5_secrets(user["id"])
    if secrets.get("symbol"):
        settings.symbol = secrets["symbol"]
    if secrets.get("mode") == "mt5":
        settings.mode = "mt5"
        settings.mt5_login = secrets["login"]
        settings.mt5_password = secrets["password"]
        settings.mt5_server = secrets["server"]
        settings.mt5_path = secrets["path"]
        bridge.mode = "mt5"
        snap = bridge.connect()
        desk.account = snap
    else:
        settings.mode = "paper"
        bridge.mode = "paper"
        desk.account = bridge.connect()
    store.log_event("settings_saved", {"user": user["username"], "mode": settings.mode})
    return {"ok": True, "user": updated, "account": desk.account.to_dict()}


def _readiness(snap: dict) -> dict:
    tick = snap.get("tick") or {}
    bid = float(tick.get("bid") or 0)
    feed = str(snap.get("feed") or tick.get("source") or "")
    feed_ok = (
        feed.startswith("gold_api")
        or feed.startswith("yahoo")
        or feed in {"mt5", "metaapi", "ctrader"}
        or feed.endswith("_live")
        or feed.endswith("_synth")
    )
    acc = snap.get("account") or {}
    live_exec = bridge.is_live_execution() and acc.get("mode") == "mt5" and bool(acc.get("connected"))
    ctrader.refresh()
    checks = {
        "service_up": True,
        "product_aurum": True,
        "price_live": bid >= 1000,  # gold can print below 3000; reject only absurd feeds
        "feed_ok": feed_ok,
        "candles_ok": int(snap.get("candle_count") or 0) >= 50,
        "auto_trade": bool(snap.get("auto_trade")),
        "risk_active": not bool((snap.get("risk") or {}).get("halted")),
        "mt5_live": acc.get("mode") == "mt5",
        # Paper "connected" must NOT count as live FP Markets
        "mt5_connected": live_exec,
        "metaapi_configured": metaapi.configured,
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "cloud_execution": bridge.execution in {"metaapi", "ctrader"} and live_exec,
        "auth_configured": auth.user_count() > 0,
        "real_orders_only": True,
    }
    paper_ready = all(checks[k] for k in ("service_up", "price_live", "feed_ok", "candles_ok", "risk_active", "auth_configured"))
    live_ready = paper_ready and live_exec and checks["ctrader_ready"]
    grade = "live_ready" if live_ready else "paper_ready" if paper_ready else "not_ready"
    return {
        "grade": grade,
        "paper_ready": paper_ready,
        "broker_mt5_ready": live_ready,
        "live_execution": live_exec,
        "checks": checks,
        "summary_ar": (
            "متصل للتنفيذ الحقيقي عبر cTrader على FP Markets"
            if grade == "live_ready"
            else "وضع ورقي للتجربة فقط — أكمل ربط cTrader للتنفيذ الحقيقي"
            if grade == "paper_ready"
            else "اربط cTrader Open API من تبويب الربط (حساب FP Markets cTrader)"
        ),
        "next_for_broker": [
            "أنشئ تطبيقاً على openapi.ctrader.com",
            "احفظ Client ID/Secret في تبويب الربط",
            "فوّض cTrader واختر حساب FP Markets",
            "ثم اضغط ابدأ التداول — لن تُفتح صفقات وهمية",
        ],
    }


@app.get("/api/status")
async def status(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = auth.user_from_token(_token_from(authorization, aurum_session))
    snap = desk.last or {}
    if user:
        # Full desk only for authenticated sessions — avoid sync scan on anonymous hits
        if not snap:
            snap = await asyncio.to_thread(desk.scan, True)
        return {
            "product": PRODUCT_NAME,
            "tagline": PRODUCT_TAGLINE,
            "version": __version__,
            "disclaimer": (
                "التداول ينطوي على مخاطر. لا يوجد بوت معتمد يضمن الربح. "
                "AURUM منصة تنفيذ وإدارة مخاطر حقيقية — النتائج غير مضمونة."
            ),
            "readiness": _readiness(snap),
            "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count(), "authenticated": True},
            **snap,
        }
    # Public: redacted readiness + cTrader setup hint
    ctrader.refresh()
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": __version__,
        "broker": BROKER_NAME,
        "primary": "ctrader",
        "disclaimer": (
            "التداول ينطوي على مخاطر. لا يوجد بوت معتمد يضمن الربح. "
            "AURUM منصة تنفيذ وإدارة مخاطر حقيقية — النتائج غير مضمونة."
        ),
        "mode": desk.account.mode,
        "state": desk.state,
        "live_execution": bool(bridge.is_live_execution() and desk.account.connected),
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "metaapi_configured": False,
        "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count(), "authenticated": False},
        "readiness": {
            "ok": False,
            "grade": "login_required" if not auth.needs_setup() else "register_required",
            "summary_ar": (
                "أنشئ حساب تطبيق أولاً ثم اربط FP Markets عبر cTrader"
                if auth.needs_setup()
                else "سجّل الدخول ثم أكمل ربط cTrader من تبويب الربط"
            ),
            "next_for_broker": [
                "إنشاء/دخول حساب التطبيق",
                "حفظ Client ID/Secret من openapi.ctrader.com",
                "تفويض cTrader واختيار حساب FP Markets",
                "ابدأ التداول",
            ],
        },
    }


@app.get("/api/ready")
async def ready():
    snap = desk.last or desk.scan(full=True)
    r = _readiness(snap)
    return {"ok": r["paper_ready"], **r, "version": __version__, "mode": (snap.get("account") or {}).get("mode")}


@app.post("/api/scan")
async def scan(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    return desk.scan(full=True)


@app.get("/api/pulse")
async def pulse(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    return desk.pulse_tick()


@app.post("/api/start")
async def start_desk(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(authorization, aurum_session)
    secrets = auth.mt5_secrets(user["id"])
    exec_pref = str(secrets.get("execution") or "").strip()
    # cTrader path — no MT5 login required
    if exec_pref == "ctrader" or (settings.prefer_ctrader and ctrader.ready and exec_pref in {"", "ctrader"}):
        ctrader.refresh()
        settings.mode = "mt5"
        if secrets.get("ctrader_account_id") and str(secrets["ctrader_account_id"]).isdigit():
            bridge.bind_ctrader(int(secrets["ctrader_account_id"]))
        elif ctrader.account_id:
            bridge.bind_ctrader(ctrader.account_id)
        else:
            bridge.execution = "ctrader"
            bridge.mode = "mt5"
        desk.account = await asyncio.to_thread(bridge.connect)
        if not desk.account.connected:
            return {
                "ok": False,
                "error": "ctrader",
                "message": desk.account.detail
                or "cTrader غير متصل — احفظ التطبيق وفوّض واختر حساب FP Markets cTrader.",
                "bridge": _cloud_status_for_user(user["id"]),
            }
    elif settings.prefer_ctrader and ctrader.ready:
        # Prefer cTrader even if old MT5 secrets linger
        settings.mode = "mt5"
        bridge.bind_ctrader(ctrader.account_id)
        desk.account = await asyncio.to_thread(bridge.connect)
    elif secrets.get("mode") == "mt5" and secrets.get("login") and settings.prefer_metaapi:
        settings.mode = "mt5"
        settings.mt5_login = secrets["login"]
        settings.mt5_password = secrets["password"]
        settings.mt5_server = secrets["server"]
        settings.symbol = secrets.get("symbol") or settings.symbol
        bridge.bind_remote_user(user["id"])
        raw_cloud_id = secrets.get("metaapi_account_id") or ""
        if raw_cloud_id and not is_metaapi_account_id(raw_cloud_id):
            auth.update_settings(user["id"], {"metaapi_account_id": ""})
            bridge.metaapi_account_id = ""
            raw_cloud_id = ""
        if raw_cloud_id:
            bridge.bind_metaapi(raw_cloud_id, secrets.get("metaapi_region"))
        desk.account = bridge.connect()
        if not desk.account.connected and metaapi.configured and secrets.get("password"):
            try:
                cloud = await _provision_cloud_async(
                    user["id"],
                    str(secrets["login"]),
                    secrets["password"],
                    secrets["server"],
                    secrets.get("symbol") or settings.symbol,
                    bridge.metaapi_account_id or None,
                    timeout_sec=18.0,
                )
                desk.account = bridge.connect()
                if not desk.account.connected and cloud.get("pending"):
                    return {
                        "ok": False,
                        "error": "connecting",
                        "message": "الطرفية السحابية قيد الاتصال — انتظر ثوانٍ ثم أعد «ابدأ التداول».",
                        "bridge": _cloud_status_for_user(user["id"]),
                        "cloud": cloud,
                    }
            except MetaApiError as e:
                if e.code == "E_PROVISION_PENDING":
                    return {
                        "ok": False,
                        "error": "connecting",
                        "message": e.message,
                        "bridge": _cloud_status_for_user(user["id"]),
                    }
                return {
                    "ok": False,
                    "error": e.code or "metaapi",
                    "message": arabic_metaapi_error(e),
                    "bridge": _cloud_status_for_user(user["id"]),
                }
    if desk.risk.state.halted:
        return {
            "ok": False,
            "error": "risk_halted",
            "message": "التداول متوقف لحد الخسارة اليومي. اضغط «إعادة تعيين المخاطر» للمتابعة.",
            "risk": desk.risk.state.to_dict(),
        }
    # Hard gate: live users cannot arm until cTrader/FP Markets is truly connected
    if settings.mode == "mt5" and not (bridge.is_live_execution() and desk.account.connected):
        return {
            "ok": False,
            "error": "not_live",
            "message": (
                "حساب FP Markets عبر cTrader غير متصل بعد — لن نبدأ تداولاً وهمياً. "
                "من تبويب الربط: احفظ التطبيق → تفويض → اختر الحساب ثم أعد «ابدأ التداول»."
            ),
            "bridge": _cloud_status_for_user(user["id"]),
            "account": desk.account.to_dict(),
            "execution": bridge.execution or "pending",
            "live": False,
        }
    out = desk.start_desk()
    out["bridge"] = _cloud_status_for_user(user["id"])
    out["execution"] = bridge.execution
    out["live"] = bool(out.get("live"))
    return out


@app.post("/api/stop")
async def stop_desk(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    desk.set_auto_trade(False)
    desk.armed = False
    store.log_event("desk_stop", {"armed": False})
    return {"ok": True, "armed": False, "auto_trade": False, "message": "توقف التنفيذ التلقائي."}


@app.post("/api/risk/reset")
async def risk_reset(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(authorization, aurum_session)
    equity = desk.account.equity or settings.paper_balance
    result = desk.risk.reset_day(equity, note=f"reset_by_{user['username']}")
    store.log_event("risk_reset", {"user": user["username"], **result})
    return result


@app.post("/api/auto-trade")
async def auto_trade(body: AutoTradeBody, authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    if body.enabled and settings.mode == "mt5":
        desk.account = bridge.connect()
        if not (bridge.is_live_execution() and desk.account.connected):
            desk.set_auto_trade(False)
            desk.armed = False
            raise HTTPException(
                409,
                "لا يمكن تفعيل التداول التلقائي قبل اتصال FP Markets الحقيقي عبر cTrader.",
            )
    desk.set_auto_trade(body.enabled)
    desk.armed = bool(body.enabled)
    return {"ok": True, "auto_trade": desk.auto_trade, "armed": desk.armed}


@app.post("/api/execute")
async def execute(body: ExecuteBody = ExecuteBody(), authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    if settings.mode == "mt5":
        desk.account = bridge.connect()
        if not (bridge.is_live_execution() and desk.account.connected):
            raise HTTPException(
                409,
                "التنفيذ الحقيقي غير متصل — لن نفتح صفقة وهمية. أعد الربط السحابي أولاً.",
            )
    return desk.execute_signal(force=body.force)


@app.get("/api/trades")
async def trades(limit: int = Query(40, ge=1, le=200), authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    return {"trades": store.recent_trades(limit)}


@app.get("/api/events")
async def events(limit: int = Query(40, ge=1, le=200), authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    return {"events": store.recent_events(limit)}


@app.get("/api/schools")
async def schools(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
    snap = desk.scan(full=True)
    return {
        "schools": snap["signal"]["schools"],
        "institutional": snap["signal"]["institutional"],
        "structure": snap["signal"]["structure"],
        "narrative": snap["signal"]["narrative"],
        "pulse": snap.get("pulse"),
    }


@app.get("/api/ways")
async def execution_ways():
    """Primary path: cTrader Open API for FP Markets (MT5/MetaApi removed from product)."""
    ctrader.refresh()
    return {
        "ok": True,
        "primary": "ctrader",
        "broker": BROKER_NAME,
        "broker_id": BROKER_ID,
        "broker_platform": BROKER_PLATFORM,
        "finding_ar": (
            f"AURUM مربوط بوسيط {BROKER_NAME} فقط. التنفيذ عبر cTrader Open API "
            "لحسابات FP Markets على منصة cTrader — من التطبيق مباشرة."
        ),
        "ways": [
            {
                "id": "ctrader",
                "title_ar": f"{BROKER_NAME} · cTrader Open API (النظام الأساسي)",
                "windows_required": False,
                "cost": f"مجاني — تطبيق Spotware Open API + حساب {BROKER_NAME} cTrader",
                "ready": ctrader.ready,
                "steps_ar": [
                    f"افتح حساب {BROKER_NAME} cTrader من بوابة العميل",
                    "أنشئ تطبيقاً على openapi.ctrader.com (Client ID + Secret)",
                    "احفظهما في AURUM واضغط تفويض cTrader بحساب FP Markets",
                    f"اختر حساب {BROKER_NAME} — حسابات الوسطاء الآخرين مرفوضة",
                ],
                "signup": "https://openapi.ctrader.com",
                "broker_portal": BROKER_PORTAL,
                "note_ar": f"مقفول على وسيط {BROKER_NAME} فقط.",
            },
        ],
        "rejected_ar": [
            "مسار MetaTrader 5 / MetaApi غير مفعّل",
            f"حسابات وسطاء غير {BROKER_NAME} مرفوضة عند الربط",
        ],
        "metaapi_configured": False,
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "mt5_linux_configured": False,
        "servers": BROKER_SERVERS,
        "ctrader_server": DEFAULT_CTRADER_SERVER,
    }


@app.get("/api/connect-guide")
async def connect_guide():
    ways = await execution_ways()
    return {
        "title": "ربط FP Markets عبر cTrader Open API",
        "steps": ways["ways"][0]["steps_ar"],
        "primary": "ctrader",
        "metaapi_configured": False,
        "ctrader_configured": ways["ctrader_configured"],
        "ctrader_ready": ways["ctrader_ready"],
        "mt5_linux_configured": False,
        "warning": ways["finding_ar"],
        "servers": BROKER_SERVERS,
        "ctrader_signup": "https://openapi.ctrader.com",
        "ways": ways["ways"],
    }


class CTraderAppBody(BaseModel):
    client_id: str = Field(..., min_length=4)
    client_secret: str = Field(..., min_length=4)
    live: bool = True


class CTraderTokenBody(BaseModel):
    access_token: str = Field(..., min_length=10)
    refresh_token: str | None = None


class CTraderBindBody(BaseModel):
    account_id: int = Field(..., ge=1)
    live: bool | None = None


@app.get("/api/ctrader/status")
async def ctrader_status(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    ctrader.refresh()
    return {
        "ok": True,
        "broker": BROKER_NAME,
        "broker_id": BROKER_ID,
        "broker_platform": BROKER_PLATFORM,
        "broker_portal": BROKER_PORTAL,
        "broker_client_area": BROKER_CLIENT_AREA,
        "configured": ctrader.configured,
        "ready": ctrader.ready,
        "has_token": bool(ctrader.access_token),
        "account_id": ctrader.account_id,
        "live": ctrader.live,
        "redirect_uri": ctrader.redirect_uri,
        "signup": "https://openapi.ctrader.com",
        "ctrader_server": DEFAULT_CTRADER_SERVER,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict() if desk.account else {},
        "steps_ar": [
            f"افتح حساب {BROKER_NAME} على منصة cTrader من {BROKER_CLIENT_AREA}",
            "أنشئ تطبيقاً على https://openapi.ctrader.com وانسخ Client ID و Client Secret",
            f"أضف Redirect URI: {ctrader.redirect_uri}",
            "احفظهما هنا ثم اضغط «تفويض cTrader» وسجّل دخول حساب FP Markets",
            "اختر حساب FP Markets cTrader من القائمة (حسابات وسطاء آخرين مرفوضة)",
        ],
        "note_ar": f"AURUM مربوط بوسيط {BROKER_NAME} فقط عبر cTrader Open API — حسابات MT5 أو وسطاء آخرين غير مدعومة.",
    }


@app.post("/api/ctrader/app")
async def ctrader_save_app(
    body: CTraderAppBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    ctrader.save_app(body.client_id, body.client_secret, live=body.live)
    auth.update_settings(user["id"], {"execution": "ctrader", "mode": "mt5"})
    store.log_event("ctrader_app_saved", {"user": user["username"], "live": body.live})
    return {
        "ok": True,
        "configured": ctrader.configured,
        "redirect_uri": ctrader.redirect_uri,
        "broker": BROKER_NAME,
        "message": (
            f"تم حفظ تطبيق cTrader لـ {BROKER_NAME}. "
            "انسخ Redirect URI إلى Spotware ثم اضغط «تفويض cTrader»."
        ),
        "next_ar": "نسخ Redirect URI → تفويض → اختيار حساب FP Markets → ابدأ التداول",
        "bridge": _cloud_status_for_user(user["id"]),
    }


@app.get("/api/ctrader/oauth/start")
async def ctrader_oauth_start(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    try:
        import secrets as _secrets

        state = _secrets.token_urlsafe(16)
        store.set_kv("ctrader_oauth_state", {"state": state, "user_id": user["id"], "ts": time.time()})
        url = ctrader.auth_url(state=state)
    except CTraderError as e:
        raise HTTPException(400, arabic_ctrader_error(e))
    return {"ok": True, "auth_url": url, "redirect_uri": ctrader.redirect_uri}


@app.get("/api/ctrader/oauth/callback")
async def ctrader_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Public OAuth redirect target — exchanges code then sends user back to the desk."""
    if error:
        return RedirectResponse(f"/?ctrader=error&msg={error}", status_code=302)
    if not code:
        return RedirectResponse("/?ctrader=error&msg=missing_code", status_code=302)
    saved = store.get_kv("ctrader_oauth_state") or {}
    if state and saved.get("state") and state != saved.get("state"):
        return RedirectResponse("/?ctrader=error&msg=bad_state", status_code=302)
    try:
        ctrader.exchange_code(code)
        uid = saved.get("user_id")
        if uid:
            auth.update_settings(int(uid), {"execution": "ctrader", "mode": "mt5"})
        store.log_event("ctrader_oauth_ok", {"user_id": uid})
    except CTraderError as e:
        store.log_event("ctrader_oauth_error", {"error": str(e)})
        return RedirectResponse("/?ctrader=error&msg=token", status_code=302)
    return RedirectResponse("/?ctrader=authorized", status_code=302)


@app.post("/api/ctrader/token")
async def ctrader_save_token(
    body: CTraderTokenBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    if not ctrader.configured:
        raise HTTPException(400, arabic_ctrader_error(CTraderError("missing app", code="NO_APP")))
    ctrader.save_access_token(body.access_token, body.refresh_token)
    auth.update_settings(user["id"], {"execution": "ctrader", "mode": "mt5"})
    return {
        "ok": True,
        "has_token": True,
        "message": "تم حفظ توكن cTrader — اختر الحساب من القائمة.",
        "bridge": _cloud_status_for_user(user["id"]),
    }


@app.get("/api/ctrader/accounts")
async def ctrader_list_accounts(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    require_user(authorization, aurum_session)
    ctrader.refresh()
    if not ctrader.configured or not ctrader.access_token:
        raise HTTPException(400, arabic_ctrader_error(CTraderError("missing access token", code="NO_TOKEN")))
    try:
        rows = await asyncio.to_thread(lambda: ctrader.list_accounts(fp_markets_only=True))
    except CTraderError as e:
        raise HTTPException(400, arabic_ctrader_error(e))
    return {
        "ok": True,
        "broker": BROKER_NAME,
        "broker_id": BROKER_ID,
        "accounts": rows,
        "count": len(rows),
        "hint_ar": f"تظهر فقط حسابات {BROKER_NAME} على cTrader — اختر حساباً ثم اضغط ربط.",
    }


@app.post("/api/ctrader/bind")
async def ctrader_bind(
    body: CTraderBindBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    user = require_user(authorization, aurum_session)
    ctrader.refresh()
    if not ctrader.configured or not ctrader.access_token:
        raise HTTPException(400, arabic_ctrader_error(CTraderError("missing access token", code="NO_TOKEN")))
    try:
        selected = await asyncio.to_thread(lambda: ctrader.select_account(body.account_id, live=body.live))
    except CTraderError as e:
        raise HTTPException(400, arabic_ctrader_error(e))
    settings.mode = "mt5"
    settings.mt5_server = str(selected.get("server") or DEFAULT_CTRADER_SERVER)
    auth.update_settings(
        user["id"],
        {
            "mode": "mt5",
            "execution": "ctrader",
            "ctrader_account_id": str(body.account_id),
            "mt5_server": str(selected.get("server") or DEFAULT_CTRADER_SERVER),
            "broker": BROKER_NAME,
        },
    )
    bridge.bind_ctrader(body.account_id)
    bridge.mode = "mt5"
    try:
        desk.account = await asyncio.to_thread(bridge.connect)
    except Exception as e:
        log.warning("ctrader bind connect: %s", e)
        desk.account = bridge.connect()
    online = bool(desk.account.connected)
    if online:
        _set_provision_state(
            "ok",
            f"متصل بـ {BROKER_NAME} عبر cTrader — التنفيذ الحقيقي جاهز",
            connected=True,
        )
    store.log_event(
        "ctrader_bound",
        {
            "user": user["username"],
            "account_id": body.account_id,
            "connected": online,
            "broker": BROKER_NAME,
            "server": selected.get("server"),
        },
    )
    return {
        "ok": True,
        "broker": BROKER_NAME,
        "broker_id": BROKER_ID,
        "server": selected.get("server"),
        "ready": ctrader.ready,
        "account_id": body.account_id,
        "account": desk.account.to_dict(),
        "bridge": _cloud_status_for_user(user["id"]),
        "live_execution": online and bridge.is_live_execution(),
        "message": (
            f"تم الربط بـ {BROKER_NAME} عبر cTrader — التنفيذ من التطبيق مباشرة"
            if online
            else f"تم اختيار حساب {BROKER_NAME} — إن فشل الاتصال تحقق من Live/Demo وأن الحساب cTrader."
        ),
    }


@app.post("/api/ctrader/enable")
async def ctrader_enable(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Prefer cTrader execution path for this user (after app+token+account are set)."""
    user = require_user(authorization, aurum_session)
    ctrader.refresh()
    auth.update_settings(user["id"], {"execution": "ctrader", "mode": "mt5"})
    settings.mode = "mt5"
    if ctrader.ready:
        bridge.bind_ctrader(ctrader.account_id)
        desk.account = await asyncio.to_thread(bridge.connect)
    else:
        bridge.execution = "ctrader"
        bridge.mode = "mt5"
    return {
        "ok": True,
        "ready": ctrader.ready,
        "configured": ctrader.configured,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "message": "مسار cTrader مفعّل" if ctrader.ready else "مسار cTrader مفعّل — أكمل التفويض واختيار الحساب",
    }


def _bridge_auth(authorization: str | None) -> dict:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    row = hub.resolve(token)
    if not row:
        raise HTTPException(401, "invalid bridge token")
    return row


@app.post("/api/bridge/windows-enable")
async def bridge_windows_enable(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Issue Windows MT5 agent token + command — real FP Markets via local MetaTrader 5."""
    user = require_user(authorization, aurum_session)
    secrets = auth.mt5_secrets(user["id"])
    if not secrets.get("login") or not secrets.get("password"):
        raise HTTPException(
            400,
            "احفظ بيانات FP Markets أولاً من شاشة الدخول (رقم الحساب + كلمة مرور التداول + السيرفر).",
        )
    token = hub.issue_token(user["id"])
    public = (os.getenv("AURUM_PUBLIC_URL") or "https://pfai-v8.onrender.com").rstrip("/")
    agent_cmd = (
        f"python aurum_fpmarkets_agent.py --cloud {public} --token {token}"
    )
    auth.update_settings(
        user["id"],
        {
            "mode": "mt5",
            "execution": "windows_bridge",
            # Keep metaapi id but prefer Windows until user binds MetaApi again
        },
    )
    settings.mode = "mt5"
    settings.mt5_login = secrets["login"]
    settings.mt5_password = secrets["password"]
    settings.mt5_server = secrets["server"]
    bridge.bind_remote_user(user["id"])
    bridge.execution = "windows_bridge"
    bridge.mode = "mt5"
    store.log_event("windows_bridge_enabled", {"user": user["username"], "login": secrets["login"]})
    return {
        "ok": True,
        "bridge_token": token,
        "agent_command": agent_cmd,
        "agent_download": f"{public}/aurum_fpmarkets_agent.py",
        "cloud_url": public,
        "login": secrets["login"],
        "server": secrets["server"],
        "symbol": secrets.get("symbol") or "XAUUSD",
        "steps_ar": [
            "ثبّت MetaTrader 5 من FP Markets وسجّل دخول حسابك (كلمة التداول).",
            "على ويندوز: pip install MetaTrader5 requests",
            f"حمّل الوكيل: {public}/aurum_fpmarkets_agent.py",
            f"شغّل: {agent_cmd}",
            "اترك MT5 والوكيل مفتوحين — ثم اضغط «ابدأ التداول» من AURUM.",
        ],
        "message": "تم تفعيل مسار Windows. انسخ الأمر وشغّله على جهازك مع MT5 مفتوح.",
        "bridge": _cloud_status_for_user(user["id"]),
    }


@app.post("/api/bridge/heartbeat")
async def bridge_heartbeat(body: BridgeHeartbeatBody, authorization: str | None = Header(default=None)):
    row = _bridge_auth(authorization)
    # When Windows agent heartbeats, prefer that execution path
    try:
        uid = int(row["user_id"])
        bridge.bind_remote_user(uid)
        bridge.execution = "windows_bridge"
        bridge.mode = "mt5"
        auth.update_settings(uid, {"execution": "windows_bridge", "mode": "mt5"})
        desk.account = bridge.connect()
    except Exception:
        pass
    return hub.heartbeat(row["bridge_token"], info=body.info, account=body.account)


@app.get("/api/bridge/credentials")
async def bridge_credentials(authorization: str | None = Header(default=None)):
    row = _bridge_auth(authorization)
    secrets = auth.mt5_secrets(int(row["user_id"]))
    if not secrets.get("login") or not secrets.get("password"):
        raise HTTPException(400, "mt5 credentials missing on user")
    return {
        "ok": True,
        "login": secrets["login"],
        "password": secrets["password"],
        "server": secrets["server"],
        "path": secrets.get("path") or "",
        "symbol": secrets.get("symbol") or "XAUUSD",
    }


@app.get("/api/bridge/poll")
async def bridge_poll(authorization: str | None = Header(default=None)):
    row = _bridge_auth(authorization)
    cmds = hub.poll_commands(row["bridge_token"])
    return {"ok": True, "commands": cmds}


@app.post("/api/bridge/complete")
async def bridge_complete(body: BridgeCompleteBody, authorization: str | None = Header(default=None)):
    row = _bridge_auth(authorization)
    return hub.complete_command(row["bridge_token"], int(body.command_id), body.result)


def _metaapi_disabled_http():
    if not settings.prefer_metaapi:
        raise HTTPException(
            410,
            "مسار MetaApi معطّل — استخدم تبويب ربط cTrader / FP Markets.",
        )


@app.get("/api/bridge/status")
async def bridge_status(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(authorization, aurum_session)
    ctrader.refresh()
    st = _cloud_status_for_user(user["id"])
    return {
        "ok": True,
        "bridge": st,
        "cloud": st,
        "execution": st.get("execution") or "ctrader",
        "broker": BROKER_NAME,
        "primary": "ctrader",
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "metaapi_configured": False,
        "windows_required": False,
    }


@app.get("/api/cloud/status")
async def cloud_status(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    """Compat status endpoint — reports cTrader/FP Markets connect state."""
    user = require_user(authorization, aurum_session)
    ctrader.refresh()
    st = _cloud_status_for_user(user["id"])
    live = bridge.is_live_execution() and desk.account.connected and desk.account.mode == "mt5"
    if live:
        _set_provision_state("ok", f"متصل بـ {BROKER_NAME} عبر cTrader — التنفيذ الحقيقي جاهز", connected=True)
    provision = _get_provision_state()
    if not live and not ctrader.ready:
        provision = {
            "status": "pending" if ctrader.configured else "idle",
            "message": st.get("detail") or "أكمل ربط cTrader",
            "connected": False,
        }
    return {
        "ok": True,
        "primary": "ctrader",
        "broker": BROKER_NAME,
        "metaapi_configured": False,
        "ctrader_configured": ctrader.configured,
        "ctrader_ready": ctrader.ready,
        "ctrader_account_id": ctrader.account_id,
        "mt5_linux_configured": False,
        "bridge": st,
        "account": desk.account.to_dict(),
        "live_execution": live,
        "real_orders_only": True,
        "provision": provision,
        "cooldown": None,
        "last_error": None,
        "ctrader_signup": "https://openapi.ctrader.com",
        "broker_portal": BROKER_PORTAL,
    }


@app.post("/api/cloud/token")
async def cloud_save_token(
    body: MetaApiTokenBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Save MetaApi token from the app (encrypted), validate, and auto-reconnect FP Markets."""
    _metaapi_disabled_http()
    user = require_user(authorization, aurum_session)
    from goldbot.mt5.metaapi_cloud import save_stored_token

    token = body.token.strip()
    if body.region:
        settings.metaapi_region = body.region.strip()
        store.set_kv("metaapi_region", settings.metaapi_region)
    save_stored_token(token)
    metaapi.set_token(token)
    metaapi.region = settings.metaapi_region
    validated = None
    if body.check_token:
        try:
            validated = metaapi.validate_token()
        except MetaApiError as e:
            raise HTTPException(400, f"التوكن مرفوض من MetaApi: {e.message}")
    store.log_event("metaapi_token_saved", {"ok": True, "accounts": (validated or {}).get("accounts")})

    # Auto-provision FP Markets cloud terminal if credentials already saved
    cloud = None
    started = None
    secrets = auth.mt5_secrets(user["id"])
    if secrets.get("login") and secrets.get("password"):
        try:
            settings.mode = "mt5"
            settings.mt5_login = secrets["login"]
            settings.mt5_password = secrets["password"]
            settings.mt5_server = secrets["server"]
            settings.symbol = secrets.get("symbol") or settings.symbol
            bridge.bind_remote_user(user["id"])
            cloud = await _provision_cloud_async(
                user["id"],
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                settings.symbol,
                secrets.get("metaapi_account_id") or None,
                timeout_sec=20.0,
            )
            desk.account = bridge.connect()
            if desk.account.connected:
                if desk.risk.state.halted:
                    desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="token_auto_reconnect")
                started = desk.start_desk()
        except MetaApiError as e:
            store.log_event("metaapi_auto_reconnect_error", {"error": e.message, "code": e.code})

    connected = bool(desk.account.connected and bridge.execution == "metaapi")
    return {
        "ok": True,
        "metaapi_configured": True,
        "validated": validated,
        "cloud": cloud,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "started": started,
        "message": (
            "تم التفعيل — متصل بـ FP Markets وجاهز للتداول"
            if connected
            else "تم حفظ التوكن. إن كان حساب FP Markets محفوظاً سيكتمل الربط خلال ثوانٍ — وإلا سجّل الدخول من شاشة MT5."
        ),
    }


class CloudReconnectBody(BaseModel):
    force_new: bool = False  # drop saved MetaApi account id and recreate


class CloudBindBody(BaseModel):
    """Bind an already-CONNECTED MetaApi account (created in MetaApi dashboard)."""

    account_id: str = Field(min_length=8)
    region: str | None = None


@app.get("/api/cloud/accounts")
async def cloud_list_accounts(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    _metaapi_disabled_http()
    """List MetaApi terminals under the saved token — for the guaranteed bind path."""
    require_user(authorization, aurum_session)
    metaapi.refresh_token()
    if not metaapi.configured:
        raise HTTPException(503, "الصق توكن MetaApi أولاً")
    try:
        rows = metaapi.list_accounts()
    except MetaApiError as e:
        raise HTTPException(400, arabic_metaapi_error(e))
    out = []
    for acc in rows:
        if not isinstance(acc, dict):
            continue
        aid = normalize_account_id(str(acc.get("id") or acc.get("accountId") or ""))
        if not aid:
            continue
        status = str(acc.get("connectionStatus") or "").upper()
        state = str(acc.get("state") or "").upper()
        out.append(
            {
                "id": aid,
                "login": acc.get("login"),
                "server": acc.get("server"),
                "name": acc.get("name"),
                "region": acc.get("region") or settings.metaapi_region,
                "state": state,
                "connectionStatus": status,
                "ready": state == "DEPLOYED" and status == "CONNECTED",
            }
        )
    out.sort(key=lambda r: (not r["ready"], str(r.get("login") or "")))
    return {
        "ok": True,
        "accounts": out,
        "count": len(out),
        "ready_count": sum(1 for a in out if a["ready"]),
        "dashboard_url": "https://app.metaapi.cloud/",
        "hint_ar": (
            "الطريقة المضمونة: من لوحة MetaApi أضف حساب MT5/FP Markets وانتظر Connected، "
            "ثم الصق Account ID هنا أو اختره من القائمة واضغط ربط."
        ),
    }


@app.post("/api/cloud/bind")
async def cloud_bind_account(
    body: CloudBindBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Guaranteed path: bind a MetaApi account that is already working in their dashboard."""
    _metaapi_disabled_http()
    user = require_user(authorization, aurum_session)
    _rate_or_429(f"bind:{user['id']}", limit=8, window_sec=120)
    metaapi.refresh_token()
    if not metaapi.configured:
        raise HTTPException(503, "الصق توكن MetaApi أولاً")
    if body.region:
        settings.metaapi_region = body.region.strip()
        metaapi.region = settings.metaapi_region
    try:
        cloud = await asyncio.to_thread(
            metaapi.prepare_bound_account,
            body.account_id,
            wait=True,
            wait_timeout=50.0,
            deploy_wait=35.0,
        )
    except MetaApiError as e:
        ar = arabic_metaapi_error(e)
        log.error("cloud bind failed code=%s msg=%s", e.code, e.message)
        store.set_kv(
            "metaapi_last_error",
            {"error": ar, "raw": e.message, "code": e.code, "ts": time.time()},
        )
        _set_provision_state("error", ar, code=e.code)
        raise HTTPException(400, {"error": ar, "error_code": e.code, "detail": ar})

    _apply_cloud_binding(user["id"], cloud)
    # Sync FP Markets login/server from live account when available
    patch: dict[str, Any] = {"mode": "mt5", "execution": "metaapi"}
    if cloud.get("login"):
        patch["mt5_login"] = str(cloud["login"])
        settings.mt5_login = int(cloud["login"]) if str(cloud["login"]).isdigit() else settings.mt5_login
    if cloud.get("server"):
        patch["mt5_server"] = resolve_fp_server(str(cloud.get("server") or "")) or DEFAULT_SERVER
        settings.mt5_server = patch["mt5_server"]
    auth.update_settings(user["id"], patch)
    settings.mode = "mt5"
    bridge.bind_remote_user(user["id"])
    desk.account = bridge.connect()
    started = None
    if desk.account.connected:
        _set_provision_state("ok", "متصل بسحابة FP Markets عبر حساب MetaApi جاهز", connected=True, account_id=cloud["account_id"])
        if desk.risk.state.halted:
            desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="bind_reset")
        started = desk.start_desk()
    else:
        _set_provision_state("pending", "الحساب مربوط — بانتظار اكتمال اتصال الوسيط", account_id=cloud["account_id"])
    store.log_event(
        "metaapi_bound",
        {
            "account_id": cloud["account_id"],
            "login": cloud.get("login"),
            "server": cloud.get("server"),
            "connected": desk.account.connected,
        },
    )
    return {
        "ok": True,
        "bound": True,
        "cloud": cloud,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "user": auth.public_user(user["id"]),
        "started": started,
        "live_execution": bool(desk.account.connected and bridge.is_live_execution()),
        "message": (
            f"تم الربط الحقيقي — FP Markets {cloud.get('login') or ''} على {cloud.get('server') or 'MetaApi'} · الرصيد {float(cloud.get('equity') or desk.account.equity or 0):.2f}"
            if desk.account.connected
            else "تم حفظ معرّف الحساب — أكمل Deploy في لوحة MetaApi حتى Connected ثم حدّث"
        ),
    }


class CloudCredentialsBody(BaseModel):
    """Refresh FP Markets trading password/server then force cloud reconnect."""

    mt5_password: str = Field(min_length=4)
    mt5_server: str = DEFAULT_SERVER
    mt5_login: str | None = None
    symbol: str | None = None
    force_new: bool = True


@app.post("/api/cloud/credentials")
async def cloud_update_credentials(
    body: CloudCredentialsBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Save corrected FP Markets trading password/server and re-provision MetaApi."""
    _metaapi_disabled_http()
    user = require_user(authorization, aurum_session)
    _rate_or_429(f"creds:{user['id']}", limit=6, window_sec=180)
    secrets = auth.mt5_secrets(user["id"])
    login = str(body.mt5_login or secrets.get("login") or "").strip()
    if not login:
        raise HTTPException(400, "لا يوجد رقم حساب FP Markets محفوظ — سجّل الدخول من شاشة MT5 أولاً")
    server = resolve_fp_server(body.mt5_server)
    if not server:
        raise HTTPException(400, "أدخل سيرفر FP Markets مثل FPMarkets-Live (ليس وسيطاً آخر)")
    patch = {
        "mt5_login": login,
        "mt5_password": body.mt5_password,
        "mt5_server": server,
        "mode": "mt5",
    }
    if body.symbol:
        from goldbot.mt5.symbols import normalize_symbol

        patch["symbol"] = normalize_symbol(body.symbol)
    if body.force_new:
        patch["metaapi_account_id"] = ""
        patch["execution"] = ""
        bridge.metaapi_account_id = ""
        bridge.execution = ""
    auth.update_settings(user["id"], patch)
    settings.mode = "mt5"
    settings.mt5_login = int(login) if login.isdigit() else settings.mt5_login
    settings.mt5_password = body.mt5_password
    settings.mt5_server = server
    if body.symbol:
        settings.symbol = patch["symbol"]
    # Clear prior validation cooldown for this login+server so user can retry immediately after fix
    try:
        store.set_kv(f"metaapi_cooldown:{login}:{server.lower()}", {"until": 0})
    except Exception:
        pass
    store.log_event("cloud_credentials_updated", {"login": login, "server": server, "force_new": body.force_new})
    return await cloud_reconnect(
        CloudReconnectBody(force_new=bool(body.force_new)),
        authorization,
        aurum_session,
    )


@app.get("/api/cloud/diagnose")
async def cloud_diagnose(
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    _metaapi_disabled_http()
    """Explain why MetaApi/FP Markets cloud link failed — server mismatch, cooldown, token, etc."""
    user = require_user(authorization, aurum_session)
    metaapi.refresh_token()
    secrets = auth.mt5_secrets(user["id"])
    login = str(secrets.get("login") or "").strip()
    server = resolve_fp_server(secrets.get("server") or "")
    saved_id = normalize_account_id(secrets.get("metaapi_account_id") or "")
    last_err = store.get_kv("metaapi_last_error") or {}
    provision = _get_provision_state()
    issues: list[dict] = []
    accounts_summary: list[dict] = []
    saved_account = None
    token_ok = False
    token_accounts = 0

    if not metaapi.configured:
        issues.append(
            {
                "code": "NO_TOKEN",
                "severity": True,
                "message": "توكن MetaApi غير مضبوط — الصقه من تبويب الربط أو شاشة الدخول.",
            }
        )
    else:
        try:
            validated = metaapi.validate_token()
            token_ok = True
            token_accounts = int(validated.get("accounts") or 0)
        except MetaApiError as e:
            issues.append(
                {
                    "code": e.code or "BAD_TOKEN",
                    "severity": True,
                    "message": arabic_metaapi_error(e),
                }
            )

    if login and metaapi.configured and token_ok:
        try:
            for acc in metaapi.find_accounts_by_login(login):
                row = {
                    "id": acc.get("id"),
                    "server": acc.get("server"),
                    "state": acc.get("state"),
                    "connectionStatus": acc.get("connectionStatus"),
                    "matches_requested_server": servers_compatible(str(acc.get("server") or ""), server) if server else None,
                }
                accounts_summary.append(row)
            if saved_id:
                try:
                    saved_account = metaapi.get_account(saved_id)
                except MetaApiError as e:
                    issues.append(
                        {
                            "code": e.code or "E_BAD_ACCOUNT_ID",
                            "severity": True,
                            "message": f"معرّف الطرفية المحفوظ تالف/محذوف: {arabic_metaapi_error(e)}",
                        }
                    )
                    saved_account = None
            if server and accounts_summary and not any(a.get("matches_requested_server") for a in accounts_summary):
                old = ", ".join(sorted({str(a.get("server") or "?") for a in accounts_summary}))
                issues.append(
                    {
                        "code": "E_SERVER_MISMATCH",
                        "severity": True,
                        "message": (
                            f"طرفية MetaApi لنفس الحساب ما زالت على سيرفر مختلف ({old}) "
                            f"بينما المطلوب {server}. اضغط «إعادة ربط كامل» لترحيل السيرفر."
                        ),
                        "metaapi_servers": old,
                        "requested_server": server,
                    }
                )
            if saved_account and server and not servers_compatible(str(saved_account.get("server") or ""), server):
                issues.append(
                    {
                        "code": "E_SERVER_MISMATCH",
                        "severity": True,
                        "message": (
                            f"الطرفية المحفوظة على {saved_account.get('server')} "
                            f"وليست {server} — سيتم ترحيلها عند إعادة الربط."
                        ),
                    }
                )
        except MetaApiError as e:
            log.error("diagnose list accounts failed: %s", e.message)
            issues.append({"code": e.code or "E_DIAGNOSE", "severity": True, "message": arabic_metaapi_error(e)})

    cooldown = None
    try:
        if login and server:
            cool = store.get_kv(f"metaapi_cooldown:{login}:{server.lower()}") or {}
            until = float((cool or {}).get("until") or 0)
            if until > time.time():
                mins = max(1, int((until - time.time()) / 60))
                cooldown = {"until": until, "minutes_left": mins, "login": login, "server": server}
                issues.append(
                    {
                        "code": "E_VALIDATION_COOLDOWN",
                        "severity": True,
                        "message": f"MetaApi يمنع التحقق مؤقتاً — انتظر حوالي {mins} دقيقة.",
                    }
                )
    except Exception:
        pass

    if isinstance(last_err, dict) and last_err.get("error"):
        issues.append(
            {
                "code": last_err.get("code") or "LAST_ERROR",
                "severity": False,
                "message": str(last_err.get("error")),
                "ts": last_err.get("ts"),
            }
        )
    if provision.get("status") == "error" and provision.get("message"):
        issues.append(
            {
                "code": provision.get("code") or "PROVISION_ERROR",
                "severity": True,
                "message": str(provision.get("message")),
            }
        )

    # Deduplicate by code+message
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in issues:
        key = f"{it.get('code')}|{it.get('message')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    primary = next((i for i in uniq if i.get("severity")), uniq[0] if uniq else None)
    live = bridge.is_live_execution() and desk.account.connected and desk.account.mode == "mt5"
    return {
        "ok": True,
        "version": __version__,
        "metaapi_configured": metaapi.configured,
        "token_ok": token_ok,
        "token_accounts": token_accounts,
        "login": login or None,
        "requested_server": server or None,
        "saved_account_id": saved_id or None,
        "saved_account_server": (saved_account or {}).get("server") if saved_account else None,
        "metaapi_accounts_for_login": accounts_summary,
        "live_execution": live,
        "provision": provision,
        "cooldown": cooldown,
        "last_error": last_err if isinstance(last_err, dict) else {},
        "issues": uniq,
        "error_code": (primary or {}).get("code"),
        "message": (primary or {}).get("message")
        or ("متصل وجاهز" if live else "لا مشكلة ظاهرة — جرّب «إعادة ربط كامل» إن استمر الفشل"),
        "hint_ar": (
            "إن ظهر E_SERVER_MISMATCH: اضغط «إعادة ربط كامل». "
            "إن ظهر E_VALIDATION_COOLDOWN: صحّح كلمة مرور التداول/السيرفر وانتظر انتهاء المهلة. "
            "تأكد أن السيرفر حرفياً FPMarkets-Live من تطبيق FP Markets."
        ),
    }


@app.post("/api/cloud/reset")
async def cloud_reset(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    _metaapi_disabled_http()
    """Clear corrupt MetaApi account id and force a fresh cloud terminal."""
    user = require_user(authorization, aurum_session)
    auth.update_settings(user["id"], {"metaapi_account_id": "", "execution": ""})
    bridge.metaapi_account_id = ""
    bridge.execution = ""
    return await cloud_reconnect(CloudReconnectBody(force_new=True), authorization, aurum_session)


@app.post("/api/cloud/reconnect")
async def cloud_reconnect(
    body: CloudReconnectBody = CloudReconnectBody(),
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    _metaapi_disabled_http()
    """Re-provision MetaApi and/or probe Linux MT5 executor."""
    user = require_user(authorization, aurum_session)
    metaapi.refresh_token()
    mt5_linux.refresh()
    secrets = auth.mt5_secrets(user["id"])
    settings.mode = "mt5"
    if secrets.get("login"):
        settings.mt5_login = secrets["login"]
        settings.mt5_password = secrets["password"]
        settings.mt5_server = secrets["server"]
        settings.symbol = secrets.get("symbol") or settings.symbol
        bridge.bind_remote_user(user["id"])

    existing_id = None if body.force_new else (secrets.get("metaapi_account_id") or None)
    if existing_id and not is_metaapi_account_id(existing_id):
        existing_id = None
        auth.update_settings(user["id"], {"metaapi_account_id": ""})
    if body.force_new:
        auth.update_settings(user["id"], {"metaapi_account_id": "", "execution": ""})
        bridge.metaapi_account_id = ""
        bridge.execution = ""

    cloud = None
    if metaapi.configured and secrets.get("login") and secrets.get("password"):
        try:
            cloud = await _provision_cloud_async(
                user["id"],
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                secrets.get("symbol") or "XAUUSD",
                existing_id,
                timeout_sec=22.0,
                force_new=bool(body.force_new),
            )
        except MetaApiError as e:
            soft_retry = (
                "not found" in (e.message or "").lower()
                or e.code in {"E_BAD_ACCOUNT_ID", "NotFoundError", "E_VALIDATION_FAILED"}
                or is_validation_failed_error(e)
            )
            if soft_retry and not body.force_new:
                auth.update_settings(user["id"], {"metaapi_account_id": ""})
                bridge.metaapi_account_id = ""
                try:
                    cloud = await _provision_cloud_async(
                        user["id"],
                        str(secrets["login"]),
                        secrets["password"],
                        secrets["server"],
                        secrets.get("symbol") or "XAUUSD",
                        None,
                        timeout_sec=22.0,
                        force_new=True,
                    )
                except MetaApiError as e2:
                    if e2.code == "E_PROVISION_PENDING":
                        cloud = {"ok": True, "pending": True, "code": e2.code}
                    elif not mt5_linux.configured:
                        ar = arabic_metaapi_error(e2)
                        log.error("metaapi reconnect retry failed code=%s msg=%s", e2.code, e2.message)
                        store.set_kv(
                            "metaapi_last_error",
                            {"error": ar, "raw": e2.message, "code": e2.code or "E_VALIDATION_FAILED", "ts": time.time()},
                        )
                        _set_provision_state("error", ar, code=e2.code or "E_VALIDATION_FAILED")
                        raise HTTPException(
                            400,
                            {"error": ar, "error_code": e2.code or "E_VALIDATION_FAILED", "detail": ar},
                        )
            elif e.code == "E_PROVISION_PENDING":
                cloud = {"ok": True, "pending": True, "code": e.code}
            elif not mt5_linux.configured:
                ar = arabic_metaapi_error(e)
                code = e.code or ("E_VALIDATION_FAILED" if is_validation_failed_error(e) else "E_CLOUD")
                log.error("metaapi reconnect failed code=%s msg=%s", code, e.message)
                store.set_kv(
                    "metaapi_last_error",
                    {"error": ar, "raw": e.message, "code": code, "ts": time.time()},
                )
                _set_provision_state("error", ar, code=code)
                raise HTTPException(400, {"error": ar, "error_code": code, "detail": ar})
            store.log_event("metaapi_reconnect_error", {"error": e.message, "code": e.code})

    desk.account = bridge.connect()
    if not desk.account.connected and not metaapi.configured and not mt5_linux.configured:
        raise HTTPException(503, "فعّل MetaApi أو منفّذ Linux Docker من تبويب الربط")
    started = None
    if desk.account.connected:
        if desk.risk.state.halted:
            desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="reconnect_reset")
        started = desk.start_desk()
    return {
        "ok": True,
        "cloud": cloud,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "user": auth.public_user(user["id"]),
        "started": started,
        "recreated": bool((cloud or {}).get("recreated")),
        "message": (
            "متصل للتنفيذ الحقيقي على FP Markets"
            if desk.account.connected
            else (
                "تم حذف الطرفية العالقة وإنشاء واحدة جديدة — انتظر اتصال FP Markets ثم حدّث"
                if body.force_new or (cloud or {}).get("recreated")
                else "الربط جارٍ في الخلفية — حدّث خلال 30 ثانية أو اضغط «إعادة ربط كامل»"
            )
        ),
    }


@app.post("/api/executor/linux")
async def save_linux_executor(
    body: Mt5LinuxBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Point AURUM at a Linux Docker/Wine MT5 REST executor (no Windows)."""
    user = require_user(authorization, aurum_session)
    url = body.base_url.strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "الرابط يجب أن يبدأ بـ http:// أو https://")
    mt5_linux.set_config(url, body.token.strip())
    bridge.mode = "mt5"
    bridge.execution = "mt5_linux"
    probe = None
    if body.probe:
        try:
            probe = mt5_linux.health()
            if probe.get("ok"):
                probe["account"] = mt5_linux.snapshot()
        except Mt5LinuxError as e:
            probe = {"ok": False, "error": e.message}
    desk.account = bridge.connect()
    store.log_event("mt5_linux_configured", {"url": url, "probe_ok": bool((probe or {}).get("ok"))})
    return {
        "ok": True,
        "mt5_linux_configured": True,
        "base_url": url,
        "probe": probe,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "message": "تم حفظ منفّذ Linux — سجّل FP Markets عبر VNC مرة واحدة إن لم يكن متصلاً بعد",
    }


@app.exception_handler(Exception)
async def _unhandled(_, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"ok": False, "error": exc.detail, "detail": exc.detail}, status_code=exc.status_code)
    log.exception("unhandled: %s", exc)
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
