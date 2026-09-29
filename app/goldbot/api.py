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
from goldbot.storage.state import store

log = logging.getLogger("aurum.api")
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Do not auto-trade until a user arms the desk (safer default for real product)
    desk.start_background()
    log.info("AURUM desk online mode=%s symbol=%s", settings.mode, settings.symbol)
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


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {
        "ok": True,
        "product": PRODUCT_NAME,
        "version": __version__,
        "symbol": settings.symbol,
        "mode": desk.account.mode,
        "auto_trade": desk.auto_trade,
        "state": desk.state,
        "tick_seconds": settings.tick_seconds,
        "auth": {"needs_setup": auth.needs_setup(), "users": auth.user_count()},
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
    checks = {
        "service_up": True,
        "product_aurum": True,
        "price_live": bid >= 3000,
        "feed_ok": feed.startswith("gold_api") or feed.startswith("yahoo") or feed == "mt5",
        "candles_ok": int(snap.get("candle_count") or 0) >= 50,
        "auto_trade": bool(snap.get("auto_trade")),
        "risk_active": not bool((snap.get("risk") or {}).get("halted")),
        "mt5_live": (snap.get("account") or {}).get("mode") == "mt5",
        "auth_configured": auth.user_count() > 0,
    }
    paper_ready = all(checks[k] for k in ("service_up", "price_live", "feed_ok", "candles_ok", "risk_active", "auth_configured"))
    live_ready = paper_ready and checks["mt5_live"]
    grade = "live_ready" if live_ready else "paper_ready" if paper_ready else "not_ready"
    return {
        "grade": grade,
        "paper_ready": paper_ready,
        "exness_mt5_ready": live_ready,
        "checks": checks,
        "summary_ar": (
            "جاهز للتداول الورقي على الذهب"
            if grade == "paper_ready"
            else "جاهز للتنفيذ عبر MT5/Exness"
            if grade == "live_ready"
            else "أكمل التسجيل ثم اضبط الربط/المخاطر"
        ),
        "next_for_exness": [
            "سجّل دخولاً في AURUM",
            "Windows VPS + MetaTrader 5",
            "احفظ بيانات Exness من تبويب الربط",
            "AURUM_MODE=mt5 على جهاز Windows",
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
    require_user(authorization, aurum_session)
    # If halted from prior paper day losses, require explicit reset
    if desk.risk.state.halted:
        return {
            "ok": False,
            "error": "risk_halted",
            "message": "التداول متوقف لحد الخسارة اليومي. اضغط «إعادة تعيين المخاطر» للمتابعة ورقياً.",
            "risk": desk.risk.state.to_dict(),
        }
    return desk.start_desk()


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


@app.get("/api/connect-guide")
async def connect_guide():
    return {
        "title": "ربط Exness عبر MetaTrader 5",
        "steps": [
            "أنشئ حساباً في AURUM (تسجيل) ثم سجّل الدخول.",
            "من تبويب «الربط» أدخل رقم حساب Exness / السيرفر / كلمة مرور MT5.",
            "ثبّت MetaTrader 5 على Windows VPS.",
            "اضبط الوضع mt5 ثم اختبر الاتصال.",
            "ابدأ Demo قبل Real.",
        ],
        "warning": "لا تشارك كلمة المرور في الشات. تُحفظ مشفّرة داخل حسابك فقط.",
    }


@app.exception_handler(Exception)
async def _unhandled(_, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"ok": False, "error": exc.detail, "detail": exc.detail}, status_code=exc.status_code)
    log.exception("unhandled: %s", exc)
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
