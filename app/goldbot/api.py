"""AURUM FastAPI control plane — auth + elite gold desk."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from goldbot import PRODUCT_NAME, PRODUCT_TAGLINE, __version__
from goldbot.auth.users import SESSION_COOKIE, AuthError, auth
from goldbot.config import settings
from goldbot.execution.desk import desk
from goldbot.mt5.bridge import bridge
from goldbot.mt5.metaapi_cloud import MetaApiError, metaapi
from goldbot.mt5.mt5_linux import Mt5LinuxError, mt5_linux
from goldbot.mt5.remote_hub import EXNESS_SERVERS, hub
from goldbot.storage.state import store

log = logging.getLogger("aurum.api")
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load MetaApi token / Linux executor from env or app-saved store
    metaapi.refresh_token()
    mt5_linux.refresh()
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
    symbol: str = "XAUUSD"
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
    settings.symbol = secrets["symbol"] or "XAUUSD"
    settings.mt5_login = secrets["login"]
    settings.mt5_password = secrets["password"]
    settings.mt5_server = secrets["server"]
    bridge.bind_remote_user(user["id"])

    cloud: dict = {"ok": False, "configured": metaapi.configured}
    message = ""
    if metaapi.configured and settings.prefer_metaapi:
        try:
            cloud = metaapi.ensure_account(
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                symbol=settings.symbol,
                existing_id=secrets.get("metaapi_account_id") or None,
                wait=True,
            )
            auth.update_settings(
                user["id"],
                {
                    "metaapi_account_id": cloud["account_id"],
                    "metaapi_region": cloud.get("region") or settings.metaapi_region,
                    "execution": "metaapi",
                    "mode": "mt5",
                },
            )
            bridge.bind_metaapi(cloud["account_id"], cloud.get("region"))
            if cloud.get("connected"):
                message = "تم الربط السحابي المباشر بـ Exness عبر MetaApi — التنفيذ الحقيقي من التطبيق بدون Windows."
            else:
                message = (
                    "تم إنشاء الطرفية السحابية. الاتصال بالوسيط قيد التثبيت — "
                    "حدّث الحالة خلال دقيقة ثم ابدأ التداول."
                )
        except MetaApiError as e:
            cloud = {"ok": False, "configured": True, "error": e.message, "code": e.code, "details": e.details}
            # Map broker auth errors clearly
            if e.code in {"E_AUTH", "ValidationError"} or "authenticate" in (e.message or "").lower():
                message = "رفض الوسيط بيانات Exness — تحقق من الرقم وكلمة المرور والسيرفر."
            elif e.code == "NO_TOKEN":
                message = e.message
            else:
                message = f"تعذّر الربط السحابي: {e.message}"
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
    account_id = secrets.get("metaapi_account_id") or bridge.metaapi_account_id
    region = secrets.get("metaapi_region") or bridge.metaapi_region or settings.metaapi_region
    metaapi.refresh_token()
    mt5_linux.refresh()
    if account_id and metaapi.configured:
        if bridge.metaapi_account_id != account_id:
            bridge.bind_metaapi(account_id, region)
        snap = metaapi.snapshot(account_id, region=region or None)
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
    st = hub.status_for_user(user_id)
    st = dict(st)
    st.setdefault("execution", "windows_bridge" if st.get("online") else "pending")
    st.setdefault("provider", "windows_bridge")
    st.setdefault("windows_required", False)
    st.setdefault(
        "detail",
        st.get("detail")
        or "اختر: توكن MetaApi (سحابة) أو عنوان منفّذ Linux Docker — كلاهما بدون Windows",
    )
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
    checks = {
        "service_up": True,
        "product_aurum": True,
        "price_live": bid >= 3000,
        "feed_ok": feed_ok,
        "candles_ok": int(snap.get("candle_count") or 0) >= 50,
        "auto_trade": bool(snap.get("auto_trade")),
        "risk_active": not bool((snap.get("risk") or {}).get("halted")),
        "mt5_live": (snap.get("account") or {}).get("mode") == "mt5",
        "mt5_connected": bool((snap.get("account") or {}).get("connected")),
        "metaapi_configured": metaapi.configured,
        "cloud_execution": bridge.execution == "metaapi",
        "auth_configured": auth.user_count() > 0,
    }
    paper_ready = all(checks[k] for k in ("service_up", "price_live", "feed_ok", "candles_ok", "risk_active", "auth_configured"))
    live_ready = paper_ready and checks["mt5_live"] and checks["mt5_connected"]
    grade = "live_ready" if live_ready else "paper_ready" if paper_ready else "not_ready"
    return {
        "grade": grade,
        "paper_ready": paper_ready,
        "exness_mt5_ready": live_ready,
        "checks": checks,
        "summary_ar": (
            "جاهز للتداول الورقي على الذهب"
            if grade == "paper_ready"
            else "جاهز للتنفيذ السحابي على Exness"
            if grade == "live_ready"
            else "أكمل تسجيل Exness من التطبيق"
        ),
        "next_for_exness": [
            "أدخل رقم حساب Exness/MT5 + كلمة المرور + السيرفر من التطبيق",
            "تأكد أن METAAPI_TOKEN مضبوط على Render",
            "انتظر حالة «متصل سحابياً» ثم ابدأ التداول",
            "ابدأ بـ Demo (Exness-MT5Trial) قبل Real",
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
        if secrets.get("metaapi_account_id"):
            bridge.bind_metaapi(secrets["metaapi_account_id"], secrets.get("metaapi_region"))
        desk.account = bridge.connect()
    if desk.risk.state.halted:
        return {
            "ok": False,
            "error": "risk_halted",
            "message": "التداول متوقف لحد الخسارة اليومي. اضغط «إعادة تعيين المخاطر» للمتابعة.",
            "risk": desk.risk.state.to_dict(),
        }
    out = desk.start_desk()
    out["bridge"] = _cloud_status_for_user(user["id"])
    out["execution"] = bridge.execution
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
    desk.set_auto_trade(body.enabled)
    desk.armed = bool(body.enabled)
    return {"ok": True, "auto_trade": desk.auto_trade, "armed": desk.armed}


@app.post("/api/execute")
async def execute(body: ExecuteBody = ExecuteBody(), authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    require_user(authorization, aurum_session)
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
    return {
        "ok": True,
        "metaapi_configured": metaapi.configured,
        "mt5_linux_configured": mt5_linux.configured,
        "region": settings.metaapi_region,
        "bridge": st,
        "account": desk.account.to_dict(),
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
            cloud = metaapi.ensure_account(
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                symbol=settings.symbol,
                existing_id=secrets.get("metaapi_account_id") or None,
                wait=True,
            )
            auth.update_settings(
                user["id"],
                {
                    "metaapi_account_id": cloud["account_id"],
                    "metaapi_region": cloud.get("region") or settings.metaapi_region,
                    "execution": "metaapi",
                    "mode": "mt5",
                },
            )
            bridge.bind_metaapi(cloud["account_id"], cloud.get("region"))
            desk.account = bridge.connect()
            if desk.account.connected:
                if desk.risk.state.halted:
                    desk.risk.reset_day(desk.account.equity or settings.paper_balance, note="token_auto_reconnect")
                started = desk.start_desk()
        except MetaApiError as e:
            store.log_event("metaapi_auto_reconnect_error", {"error": e.message})

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


@app.post("/api/cloud/reconnect")
async def cloud_reconnect(authorization: str | None = Header(default=None), aurum_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
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
        bridge.bind_remote_user(user["id"])

    cloud = None
    if metaapi.configured and secrets.get("login") and secrets.get("password"):
        try:
            cloud = metaapi.ensure_account(
                str(secrets["login"]),
                secrets["password"],
                secrets["server"],
                symbol=secrets.get("symbol") or "XAUUSD",
                existing_id=secrets.get("metaapi_account_id") or None,
                wait=True,
            )
            auth.update_settings(
                user["id"],
                {
                    "metaapi_account_id": cloud["account_id"],
                    "metaapi_region": cloud.get("region") or settings.metaapi_region,
                    "execution": "metaapi",
                    "mode": "mt5",
                },
            )
            bridge.bind_metaapi(cloud["account_id"], cloud.get("region"))
        except MetaApiError as e:
            # try Linux path before failing hard
            if not mt5_linux.configured:
                raise HTTPException(400, e.message)
            store.log_event("metaapi_reconnect_error", {"error": e.message})

    desk.account = bridge.connect()
    if not desk.account.connected and not metaapi.configured and not mt5_linux.configured:
        raise HTTPException(503, "فعّل MetaApi أو منفّذ Linux Docker من تبويب الربط")
    return {
        "ok": True,
        "cloud": cloud,
        "bridge": _cloud_status_for_user(user["id"]),
        "account": desk.account.to_dict(),
        "user": auth.public_user(user["id"]),
        "message": (
            "متصل للتنفيذ الحقيقي"
            if desk.account.connected
            else "الربط محفوظ — أكمل تسجيل Exness على المنفّذ (VNC) أو انتظر MetaApi"
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
