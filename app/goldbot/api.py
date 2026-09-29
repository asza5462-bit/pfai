"""AURUM FastAPI control plane — auth + elite gold desk."""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
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
    metaapi,
    normalize_account_id,
)
from goldbot.mt5.mt5_linux import Mt5LinuxError, mt5_linux
from goldbot.mt5.remote_hub import EXNESS_SERVERS, hub
from goldbot.storage.state import store

log = logging.getLogger("aurum.api")
STATIC = Path(__file__).resolve().parent / "static"
_bg_lock = threading.Lock()
_bg_jobs: set[str] = set()


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
    bridge.bind_metaapi(cloud["account_id"], cloud.get("region"))


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
            _set_provision_state("pending", "جاري إكمال اتصال MetaApi بـ Exness…", login=login, server=server)
            cloud = metaapi.ensure_account(
                str(login),
                password,
                server,
                symbol=symbol or "XAUUSDm",
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
                    "متصل بسحابة Exness — التنفيذ الحقيقي جاهز",
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
                symbol=symbol or "XAUUSDm",
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
                    "تم إنشاء الطرفية — جاري الاتصال بـ Exness…"
                    if not cloud.get("connected")
                    else "متصل بسحابة Exness — التنفيذ الحقيقي جاهز"
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
                        symbol=symbol or "XAUUSDm",
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
                            "متصل بسحابة Exness — التنفيذ الحقيقي جاهز"
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
    # Load MetaApi token / Linux executor from env or app-saved store
    metaapi.refresh_token()
    mt5_linux.refresh()
    # Always disarm on boot — user must press «ابدأ» after live connect.
    # Prevents KV auto_trade=True + AURUM_MODE=paper from paper-filling after redeploy.
    try:
        store.set_kv("auto_trade", False)
    except Exception:
        pass
    desk.armed = False
    desk.start_background()
    log.info(
        "AURUM desk online mode=%s symbol=%s metaapi=%s mt5_linux=%s",
        settings.mode,
        settings.symbol,
        metaapi.configured,
        mt5_linux.configured,
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
    mt5_server: str = "Exness-MT5Trial15"
    symbol: str = "XAUUSDm"
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


@app.get("/aurum_exness_agent.py")
async def download_agent():
    path = STATIC / "aurum_exness_agent.py"
    return FileResponse(path, filename="aurum_exness_agent.py", media_type="text/x-python")


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    metaapi.refresh_token()
    mt5_linux.refresh()
    live = bridge.is_live_execution() and desk.account.connected and desk.account.mode == "mt5"
    return {
        "ok": True,
        "product": PRODUCT_NAME,
        "version": __version__,
        "symbol": settings.symbol,
        "mode": desk.account.mode,
        "auto_trade": desk.auto_trade,
        "state": desk.state,
        "tick_seconds": settings.tick_seconds,
        "metaapi_configured": metaapi.configured,
        "mt5_linux_configured": mt5_linux.configured,
        "execution": bridge.execution or desk.account.mode,
        "live_execution": live,
        "real_orders_only": True,
        "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count()},
    }


@app.get("/api/setup-next")
async def setup_next():
    """Public next-step guide for first-time Exness cloud connect."""
    metaapi.refresh_token()
    mt5_linux.refresh()
    if desk.account.connected and desk.account.mode == "mt5":
        step = "ready"
        next_ar = "الحساب متصل — اضغط «ابدأ التداول» من المكتب."
    elif metaapi.configured:
        step = "exness_login"
        next_ar = "التوكن محفوظ. أدخل رقم Exness + كلمة المرور + السيرفر (مثل Exness-MT5Trial15) ثم ارتباط."
    elif mt5_linux.configured:
        step = "exness_vnc_or_login"
        next_ar = "منفّذ Linux مضبوط. سجّل Exness عبر VNC إن لزم، ثم ادخل من شاشة MT5."
    else:
        step = "metaapi_token"
        next_ar = "الخطوة التالية: افتح رابط توليد التوكن، انسخه، والصقه في الحقل الأول ثم أدخل بيانات Exness."
    return {
        "ok": True,
        "step": step,
        "next_ar": next_ar,
        "metaapi_configured": metaapi.configured,
        "mt5_linux_configured": mt5_linux.configured,
        "token_url": "https://app.metaapi.cloud/api-access/generate-token",
        "default_server": "Exness-MT5Trial15",
        "default_symbol": "XAUUSDm",
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
async def register(body: RegisterBody, response: Response):
    try:
        result = auth.register(body.username, body.password, body.password_confirm)
    except AuthError as e:
        raise HTTPException(e.code, e.message)
    _set_session(response, result["token"])
    store.log_event("auth_register", {"username": result["user"]["username"], "role": result["user"]["role"]})
    return {"ok": True, **result}


@app.post("/api/auth/login")
async def login(body: LoginBody, response: Response):
    try:
        result = auth.login(body.username, body.password)
    except AuthError as e:
        raise HTTPException(e.code, e.message)
    _set_session(response, result["token"])
    store.log_event("auth_login", {"username": result["user"]["username"]})
    return {"ok": True, **result}


@app.get("/api/exness/servers")
async def exness_servers():
    from goldbot.mt5.symbols import EXNESS_GOLD_SYMBOLS

    return {
        "servers": EXNESS_SERVERS,
        "default": "Exness-MT5Trial15",
        "allow_custom": True,
        "hint_ar": "انسخ اسم السيرفر حرفياً من منطقة العميل في Exness (مثل Exness-MT5Trial15).",
        "symbols": list(EXNESS_GOLD_SYMBOLS),
        "default_symbol": "XAUUSDm",
    }


@app.post("/api/auth/mt5-login")
async def mt5_login(body: Mt5LoginBody, response: Response):
    """Login with Exness/MT5 — provision MetaApi cloud terminal (no Windows)."""
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
    settings.symbol = secrets["symbol"] or "XAUUSDm"
    settings.mt5_login = secrets["login"]
    settings.mt5_password = secrets["password"]
    settings.mt5_server = secrets["server"]
    bridge.bind_remote_user(user["id"])

    cloud: dict = {"ok": False, "configured": metaapi.configured}
    message = ""
    if metaapi.configured and settings.prefer_metaapi:
        try:
            cloud = _provision_cloud_fast(
                user["id"],
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                settings.symbol,
                secrets.get("metaapi_account_id") or None,
                timeout_sec=22.0,
            )
            if cloud.get("connected"):
                message = "تم الربط السحابي المباشر بـ Exness عبر MetaApi — التنفيذ الحقيقي من التطبيق بدون Windows."
            else:
                message = (
                    "تم حفظ الحساب وبدء الطرفية السحابية. الاتصال بالوسيط يكتمل خلال أقل من دقيقة — "
                    "لا تغلق الصفحة، حدّث من تبويب الربط إن لزم."
                )
        except MetaApiError as e:
            # Clear corrupt MetaApi ids (e.g. numeric 1215) so next attempt recreates
            if "not found" in (e.message or "").lower() or e.code in {"E_BAD_ACCOUNT_ID", "NotFoundError"}:
                auth.update_settings(user["id"], {"metaapi_account_id": "", "execution": ""})
                bridge.metaapi_account_id = ""
            if e.code == "E_PROVISION_PENDING":
                cloud = {"ok": True, "configured": True, "pending": True, "code": e.code}
                message = e.message
                # The same provision thread is still running — do not start a duplicate job
            else:
                cloud = {"ok": False, "configured": True, "error": e.message, "code": e.code, "details": e.details}
                message = arabic_metaapi_error(e)
                store.set_kv("metaapi_last_error", {"error": e.message, "code": e.code, "ts": __import__("time").time()})
            store.log_event("metaapi_login_error", {"user": user["username"], "error": e.message, "code": e.code})
    else:
        message = (
            "حساب Exness محفوظ. للصق توكن MetaApi من تبويب «ربط Exness السحابي» "
            "أو من حقل التوكن في شاشة الدخول — بعدها يبدأ التنفيذ الحقيقي بدون Windows."
        )

    desk.account = bridge.connect()
    # Refresh public user with metaapi fields
    result["user"] = auth.public_user(user["id"])

    started = None
    if body.auto_start and desk.account.connected:
        if desk.risk.state.halted:
            desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="mt5_login_reset")
        started = desk.start_desk()
    elif body.auto_start and not desk.account.connected:
        # Arm later — still allow start attempt after cloud connects
        pass

    store.log_event(
        "mt5_login",
        {
            "user": user["username"],
            "login": secrets["login"],
            "server": secrets["server"],
            "execution": bridge.execution or "pending",
            "metaapi_account_id": bridge.metaapi_account_id,
            "connected": desk.account.connected,
        },
    )
    cloud_status = _cloud_status_for_user(user["id"])
    return {
        "ok": True,
        **result,
        "cloud": cloud,
        "bridge": cloud_status,  # UI uses this pill — now cloud-first
        "account": desk.account.to_dict(),
        "started": started,
        "execution": bridge.execution or ("metaapi" if bridge.metaapi_account_id else "pending"),
        "message": message,
    }


def _cloud_status_for_user(user_id: int) -> dict:
    secrets = auth.mt5_secrets(user_id)
    raw_id = secrets.get("metaapi_account_id") or bridge.metaapi_account_id
    account_id = normalize_account_id(raw_id) if is_metaapi_account_id(raw_id) else ""
    if raw_id and not account_id:
        # Heal corrupt ids like "1215" immediately
        auth.update_settings(user_id, {"metaapi_account_id": ""})
        bridge.metaapi_account_id = ""
    region = secrets.get("metaapi_region") or bridge.metaapi_region or settings.metaapi_region
    metaapi.refresh_token()
    mt5_linux.refresh()
    if account_id and metaapi.configured:
        if bridge.metaapi_account_id != account_id:
            bridge.bind_metaapi(account_id, region)
        snap = metaapi.snapshot(account_id, region=region or None)
        if snap.get("stale"):
            auth.update_settings(user_id, {"metaapi_account_id": ""})
            bridge.metaapi_account_id = ""
            return {
                "online": False,
                "execution": "pending",
                "provider": "metaapi",
                "account_id": "",
                "stale": True,
                "detail": snap.get("detail") or "معرّف الحساب تالف — أعد الربط الكامل",
                "windows_required": False,
            }
        online = bool(snap.get("connected"))
        if online or not mt5_linux.configured:
            return {
                "online": online,
                "execution": "metaapi",
                "provider": "metaapi",
                "account_id": account_id,
                "region": region,
                "account": snap,
                "detail": snap.get("detail") or ("متصل سحابياً" if online else "غير متصل"),
                "windows_required": False,
            }
    if mt5_linux.configured:
        snap = mt5_linux.snapshot()
        online = bool(snap.get("connected"))
        if online:
            bridge.execution = "mt5_linux"
            bridge.mode = "mt5"
        return {
            "online": online,
            "execution": "mt5_linux",
            "provider": "mt5_linux",
            "base_url": mt5_linux.base_url,
            "account": snap,
            "detail": snap.get("detail") or ("متصل عبر Linux Docker" if online else "منفّذ Linux غير متصل"),
            "windows_required": False,
        }
    # MetaApi token present but cloud account not bound yet — never show Windows-agent copy
    if metaapi.configured and settings.prefer_metaapi:
        prov = _get_provision_state()
        detail = (
            (prov.get("message") if prov.get("status") in {"pending", "error"} else None)
            or "توكن MetaApi جاهز — أعد إدخال بيانات Exness أو اضغط «إعادة ربط كامل»"
        )
        return {
            "online": False,
            "execution": "pending",
            "provider": "metaapi",
            "account_id": "",
            "detail": detail,
            "windows_required": False,
            "provision": prov,
        }
    st = hub.status_for_user(user_id)
    st = dict(st)
    # Rewrite legacy Windows-agent wording when MetaApi is the product path
    detail = st.get("detail") or ""
    if "وكيل" in detail or "Windows" in detail:
        detail = "اختر مسار MetaApi السحابي (بدون Windows) من الأعلى"
    st["detail"] = detail or "فعّل توكن MetaApi ثم اربط حساب Exness"
    st.setdefault("execution", "pending")
    st.setdefault("provider", "metaapi" if metaapi.configured else "none")
    st.setdefault("windows_required", False)
    return st


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
        or feed in {"mt5", "metaapi"}
        or feed.endswith("_live")
        or feed.endswith("_synth")
    )
    acc = snap.get("account") or {}
    live_exec = bridge.is_live_execution() and acc.get("mode") == "mt5" and bool(acc.get("connected"))
    checks = {
        "service_up": True,
        "product_aurum": True,
        "price_live": bid >= 1000,  # gold can print below 3000; reject only absurd feeds
        "feed_ok": feed_ok,
        "candles_ok": int(snap.get("candle_count") or 0) >= 50,
        "auto_trade": bool(snap.get("auto_trade")),
        "risk_active": not bool((snap.get("risk") or {}).get("halted")),
        "mt5_live": acc.get("mode") == "mt5",
        # Paper "connected" must NOT count as live Exness
        "mt5_connected": live_exec,
        "metaapi_configured": metaapi.configured,
        "cloud_execution": bridge.execution == "metaapi" and live_exec,
        "auth_configured": auth.user_count() > 0,
        "real_orders_only": True,
    }
    paper_ready = all(checks[k] for k in ("service_up", "price_live", "feed_ok", "candles_ok", "risk_active", "auth_configured"))
    live_ready = paper_ready and live_exec and checks["metaapi_configured"]
    grade = "live_ready" if live_ready else "paper_ready" if paper_ready else "not_ready"
    return {
        "grade": grade,
        "paper_ready": paper_ready,
        "exness_mt5_ready": live_ready,
        "live_execution": live_exec,
        "checks": checks,
        "summary_ar": (
            "متصل للتنفيذ الحقيقي على Exness (ليس ورقي)"
            if grade == "live_ready"
            else "وضع ورقي للتجربة فقط — أكمل ربط Exness للتنفيذ الحقيقي"
            if grade == "paper_ready"
            else "أكمل توكن MetaApi + حساب Exness من شاشة الدخول"
        ),
        "next_for_exness": [
            "الصق توكن MetaApi (ويفضّل أيضاً METAAPI_TOKEN في Render حتى لا يُمسح بعد النشر)",
            "أدخل رقم Exness + كلمة مرور التداول + السيرفر (مثل Exness-MT5Trial15)",
            "انتظر «MetaApi: متصل Exness» والرصيد الحقيقي (ليس 10000 ورقي)",
            "ثم اضغط ابدأ التداول — لن تُفتح صفقات وهمية",
        ],
    }


@app.get("/api/status")
async def status():
    snap = desk.last or desk.scan(full=True)
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": __version__,
        "disclaimer": (
            "التداول ينطوي على مخاطر. لا يوجد بوت معتمد يضمن الربح. "
            "AURUM منصة تنفيذ وإدارة مخاطر حقيقية — النتائج غير مضمونة."
        ),
        "readiness": _readiness(snap),
        "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count()},
        **snap,
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
    if secrets.get("mode") == "mt5" and secrets.get("login"):
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
        # Auto-heal: stale MetaApi id cleared by connect → fast re-provision
        if not desk.account.connected and metaapi.configured and secrets.get("password"):
            try:
                cloud = _provision_cloud_fast(
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
    # Hard gate: MT5 users cannot arm until MetaApi/Linux is truly connected
    if settings.mode == "mt5" and not (bridge.is_live_execution() and desk.account.connected):
        return {
            "ok": False,
            "error": "not_live",
            "message": (
                "الحساب غير متصل بسحابة Exness بعد — لن نبدأ تداولاً وهمياً. "
                "من تبويب الربط اضغط «إعادة ربط كامل» وانتظر الرصيد الحقيقي."
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
                "لا يمكن تفعيل التداول التلقائي قبل اتصال Exness الحقيقي عبر MetaApi.",
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
    """Research-backed real paths to trade Exness without Windows."""
    metaapi.refresh_token()
    mt5_linux.refresh()
    return {
        "ok": True,
        "finding_ar": (
            "Exness لا توفّر REST API عام للأفراد. التنفيذ الحقيقي يتم فقط عبر طرفية MetaTrader 5. "
            "بدون Windows يتوفر مساران مؤكدان."
        ),
        "ways": [
            {
                "id": "metaapi",
                "title_ar": "MetaApi سحابي (الأسهل)",
                "windows_required": False,
                "cost": "حساب MT واحد مجاني تقريباً + تجربة",
                "ready": metaapi.configured,
                "steps_ar": [
                    "سجّل في app.metaapi.cloud وانسخ API token",
                    "الصقه في AURUM",
                    "أدخل رقم Exness — التطبيق يفتح طرفية سحابية وينفّذ",
                ],
                "signup": "https://app.metaapi.cloud/api-access/generate-token",
            },
            {
                "id": "mt5_linux",
                "title_ar": "MT5 على Linux Docker/Wine (بدون نظام Windows)",
                "windows_required": False,
                "cost": "VPS لينكس رخيص أو مجاني (Oracle/…) + Docker",
                "ready": mt5_linux.configured,
                "steps_ar": [
                    "شغّل docker compose من مجلد deploy/mt5-linux على سيرفر Linux",
                    "افتح VNC مرة واحدة وسجّل دخول Exness",
                    "الصق رابط الـ API (منفذ 5001) في AURUM",
                ],
                "repo": "https://github.com/thanderoy/headless-mt5",
            },
        ],
        "rejected_ar": [
            "لا يوجد توكن Exness رسمي للتداول بالـ REST للأفراد",
            "أتمتة واجهة المتصفح غير موثوقة ومخالفة لشروط الاستخدام",
        ],
        "metaapi_configured": metaapi.configured,
        "mt5_linux_configured": mt5_linux.configured,
        "servers": EXNESS_SERVERS,
    }


@app.get("/api/connect-guide")
async def connect_guide():
    ways = await execution_ways()
    return {
        "title": "طرق التنفيذ الحقيقي بدون Windows",
        "steps": ways["ways"][0]["steps_ar"] + ["أو استخدم مسار Linux Docker من /api/ways"],
        "metaapi_configured": ways["metaapi_configured"],
        "mt5_linux_configured": ways["mt5_linux_configured"],
        "warning": ways["finding_ar"],
        "servers": EXNESS_SERVERS,
        "metaapi_signup": "https://app.metaapi.cloud/api-access/generate-token",
        "ways": ways["ways"],
    }


def _bridge_auth(authorization: str | None) -> dict:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    row = hub.resolve(token)
    if not row:
        raise HTTPException(401, "invalid bridge token")
    return row


@app.post("/api/bridge/heartbeat")
async def bridge_heartbeat(body: BridgeHeartbeatBody, authorization: str | None = Header(default=None)):
    row = _bridge_auth(authorization)
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
        "symbol": secrets.get("symbol") or "XAUUSDm",
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


@app.get("/api/bridge/status")
async def bridge_status(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(authorization, aurum_session)
    metaapi.refresh_token()
    st = _cloud_status_for_user(user["id"])
    return {
        "ok": True,
        "bridge": st,
        "cloud": st,
        "execution": st.get("execution"),
        "metaapi_configured": metaapi.configured,
        "windows_required": bool(st.get("windows_required")),
    }


@app.get("/api/cloud/status")
async def cloud_status(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(authorization, aurum_session)
    metaapi.refresh_token()
    mt5_linux.refresh()
    st = _cloud_status_for_user(user["id"])
    last_err = store.get_kv("metaapi_last_error")
    provision = _get_provision_state()
    live = bridge.is_live_execution() and desk.account.connected and desk.account.mode == "mt5"
    if live and provision.get("status") != "ok":
        _set_provision_state("ok", "متصل بسحابة Exness — التنفيذ الحقيقي جاهز", connected=True)
        provision = _get_provision_state()
    secrets = auth.mt5_secrets(user["id"])
    cooldown = None
    try:
        login = str(secrets.get("login") or "").strip()
        server = str(secrets.get("server") or "").strip()
        if login and server:
            cool = store.get_kv(f"metaapi_cooldown:{login}:{server.lower()}") or {}
            until = float((cool or {}).get("until") or 0)
            if until > time.time():
                mins = max(1, int((until - time.time()) / 60))
                cooldown = {
                    "until": until,
                    "minutes_left": mins,
                    "login": login,
                    "server": server,
                    "message": (
                        f"MetaApi يمنع التحقق مؤقتاً — انتظر حوالي {mins} دقيقة "
                        "بعد تصحيح كلمة مرور التداول/السيرفر."
                    ),
                }
                if provision.get("status") != "error":
                    provision = {
                        **provision,
                        "status": "error",
                        "message": cooldown["message"],
                        "code": "E_VALIDATION_COOLDOWN",
                    }
    except Exception:
        pass
    return {
        "ok": True,
        "metaapi_configured": metaapi.configured,
        "mt5_linux_configured": mt5_linux.configured,
        "region": settings.metaapi_region,
        "bridge": st,
        "account": desk.account.to_dict(),
        "live_execution": live,
        "real_orders_only": True,
        "provision": provision,
        "cooldown": cooldown,
        "last_error": last_err,
        "signup_url": "https://app.metaapi.cloud/api-access/generate-token",
    }


@app.post("/api/cloud/token")
async def cloud_save_token(
    body: MetaApiTokenBody,
    authorization: str | None = Header(default=None),
    aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    """Save MetaApi token from the app (encrypted), validate, and auto-reconnect Exness."""
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

    # Auto-provision Exness cloud terminal if credentials already saved
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
            cloud = _provision_cloud_fast(
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
            "تم التفعيل — متصل بـ Exness وجاهز للتداول"
            if connected
            else "تم حفظ التوكن. إن كان حساب Exness محفوظاً سيكتمل الربط خلال ثوانٍ — وإلا سجّل الدخول من شاشة MT5."
        ),
    }


class CloudReconnectBody(BaseModel):
    force_new: bool = False  # drop saved MetaApi account id and recreate


@app.post("/api/cloud/reset")
async def cloud_reset(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
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
            cloud = _provision_cloud_fast(
                user["id"],
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                secrets.get("symbol") or "XAUUSDm",
                existing_id,
                timeout_sec=22.0,
                force_new=bool(body.force_new),
            )
        except MetaApiError as e:
            if "not found" in (e.message or "").lower() or e.code in {"E_BAD_ACCOUNT_ID", "NotFoundError"}:
                auth.update_settings(user["id"], {"metaapi_account_id": ""})
                bridge.metaapi_account_id = ""
                try:
                    cloud = _provision_cloud_fast(
                        user["id"],
                        str(secrets["login"]),
                        secrets["password"],
                        secrets["server"],
                        secrets.get("symbol") or "XAUUSDm",
                        None,
                        timeout_sec=22.0,
                        force_new=True,
                    )
                except MetaApiError as e2:
                    if e2.code == "E_PROVISION_PENDING":
                        cloud = {"ok": True, "pending": True, "code": e2.code}
                    elif not mt5_linux.configured:
                        raise HTTPException(400, arabic_metaapi_error(e2))
            elif e.code == "E_PROVISION_PENDING":
                cloud = {"ok": True, "pending": True, "code": e.code}
            elif not mt5_linux.configured:
                raise HTTPException(400, arabic_metaapi_error(e))
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
        "message": (
            "متصل للتنفيذ الحقيقي على Exness"
            if desk.account.connected
            else "الربط جارٍ في الخلفية — حدّث خلال 30 ثانية أو اضغط «إعادة ربط كامل»"
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
        "message": "تم حفظ منفّذ Linux — سجّل Exness عبر VNC مرة واحدة إن لم يكن متصلاً بعد",
    }


@app.exception_handler(Exception)
async def _unhandled(_, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"ok": False, "error": exc.detail, "detail": exc.detail}, status_code=exc.status_code)
    log.exception("unhandled: %s", exc)
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
