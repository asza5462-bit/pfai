"""AURUM FastAPI control plane."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from goldbot import PRODUCT_NAME, PRODUCT_TAGLINE, __version__
from goldbot.config import settings
from goldbot.execution.desk import desk
from goldbot.storage.state import store

log = logging.getLogger("aurum.api")
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_trade:
        desk.start_desk()
    else:
        desk.start_background()
    log.info("AURUM desk online mode=%s symbol=%s auto=%s", settings.mode, settings.symbol, desk.auto_trade)
    yield
    desk.stop_background()
    from goldbot.mt5.bridge import bridge

    bridge.shutdown()


app = FastAPI(title=PRODUCT_NAME, version=__version__, description=PRODUCT_TAGLINE, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")


class AutoTradeBody(BaseModel):
    enabled: bool = False


class ExecuteBody(BaseModel):
    force: bool = Field(False, description="Bypass auto_trade flag (still respects risk halt)")


def _auth(authorization: str | None) -> None:
    token = settings.owner_token
    if not token:
        return  # open desk when no token configured (demo)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    if authorization.removeprefix("Bearer ").strip() != token:
        raise HTTPException(403, "invalid token")


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
    }


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
    }
    paper_ready = all(checks[k] for k in ("service_up", "price_live", "feed_ok", "candles_ok", "risk_active"))
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
            else "غير جاهز — راجع الفحوصات"
        ),
        "next_for_exness": [
            "Windows VPS + MetaTrader 5",
            "حساب Exness Demo أولاً",
            "AURUM_MODE=mt5 + MT5_LOGIN/PASSWORD/SERVER",
        ],
    }


@app.get("/api/status")
async def status():
    snap = desk.last or desk.scan()
    ready = _readiness(snap)
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": __version__,
        "disclaimer": (
            "التداول ينطوي على مخاطر. لا يمكن لأي بوت ضمان ربح أو خسارة صفر. "
            "AURUM يقلّل المخاطرة بإدارة رأس مال صارمة وفلاتر تقارب — وليس سحراً."
        ),
        "readiness": ready,
        **snap,
    }


@app.get("/api/ready")
async def ready():
    snap = desk.last or desk.scan()
    ready = _readiness(snap)
    return {"ok": ready["paper_ready"], **ready, "version": __version__, "mode": (snap.get("account") or {}).get("mode")}


@app.post("/api/scan")
async def scan():
    return desk.scan()


@app.post("/api/start")
async def start_desk(authorization: str | None = Header(default=None)):
    """Arm desk: enable auto-trade and begin live scan/execute loop."""
    _auth(authorization)
    return desk.start_desk()


@app.post("/api/stop")
async def stop_desk(authorization: str | None = Header(default=None)):
    _auth(authorization)
    desk.set_auto_trade(False)
    desk.armed = False
    store.log_event("desk_stop", {"armed": False})
    return {"ok": True, "armed": False, "auto_trade": False, "message": "توقف التنفيذ التلقائي — المسح اليدوي ما زال متاحاً."}


@app.post("/api/auto-trade")
async def auto_trade(body: AutoTradeBody, authorization: str | None = Header(default=None)):
    _auth(authorization)
    desk.set_auto_trade(body.enabled)
    desk.armed = bool(body.enabled)
    return {"ok": True, "auto_trade": desk.auto_trade, "armed": desk.armed}


@app.post("/api/execute")
async def execute(body: ExecuteBody = ExecuteBody(), authorization: str | None = Header(default=None)):
    _auth(authorization)
    return desk.execute_signal(force=body.force)


@app.get("/api/trades")
async def trades(limit: int = Query(40, ge=1, le=200)):
    return {"trades": store.recent_trades(limit)}


@app.get("/api/events")
async def events(limit: int = Query(40, ge=1, le=200)):
    return {"events": store.recent_events(limit)}


@app.get("/api/schools")
async def schools():
    snap = desk.scan()
    return {
        "schools": snap["signal"]["schools"],
        "institutional": snap["signal"]["institutional"],
        "structure": snap["signal"]["structure"],
        "narrative": snap["signal"]["narrative"],
    }


@app.get("/api/connect-guide")
async def connect_guide():
    return {
        "title": "ربط Exness عبر MetaTrader 5",
        "steps": [
            "أنشئ حساب Demo أو Real في Exness وفعّل تداول XAUUSD.",
            "ثبّت MetaTrader 5 على Windows VPS قريب من سيرفر الوسيط.",
            "سجّل دخول الحساب في MT5 (السيرفر مثل Exness-MT5Real / Exness-MT5Trial).",
            "اضبط المتغيرات: AURUM_MODE=mt5, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH.",
            "شغّل AURUM على نفس جهاز Windows (حزمة MetaTrader5 تعمل على Windows).",
            "لوحة Render/Web يمكن أن تبقى للعرض والتحكم؛ التنفيذ الحي من جسر MT5.",
            "ابدأ بـ Demo وAURUM_AUTO_TRADE=false ثم فعّل التداول بعد مراجعة الإشارات.",
        ],
        "env": {
            "AURUM_MODE": "mt5",
            "AURUM_SYMBOL": "XAUUSD",
            "MT5_LOGIN": "<account_number>",
            "MT5_PASSWORD": "<investor_or_trading_password>",
            "MT5_SERVER": "Exness-MT5Real",
            "AURUM_RISK_PCT": "0.35",
            "AURUM_MAX_DAILY_LOSS_PCT": "1.25",
            "AURUM_AUTO_TRADE": "false",
        },
        "warning": "لا تشارك كلمة مرور الحساب في الشات. استخدم متغيرات بيئة سرية فقط.",
    }


@app.exception_handler(Exception)
async def _unhandled(_, exc: Exception):
    log.exception("unhandled: %s", exc)
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
