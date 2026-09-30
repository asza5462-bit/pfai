from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.brain.confluence import build_signal
from goldbot.market.candles import Candle, detect_patterns
from goldbot.risk.manager import RiskManager


def _candles(n=80, start=2300.0):
    out = []
    px = start
    for i in range(n):
        o = px
        c = px + (1.2 if i % 5 else -0.8)
        h = max(o, c) + 1.5
        l = min(o, c) - 1.5
        out.append(Candle(time=1_700_000_000 + i * 900, open=o, high=h, low=l, close=c, volume=1000 + i))
        px = c
    return out


def test_patterns_and_signal():
    cs = _candles()
    last = cs[-1]
    cs[-1] = Candle(last.time, last.close + 2, last.close + 2.2, last.close - 6, last.close + 1.5, 2000)
    assert isinstance(detect_patterns(cs), list)
    sig = build_signal(cs, spread_points=10)
    assert sig.action in {"buy", "sell", "flat"}
    assert 0 <= sig.confluence <= 1
    assert hasattr(sig, "quality")


def test_vol_veto_uses_tradable_not_neutral_bias():
    cs = _candles(n=100, start=4100)
    sig = build_signal(cs, spread_points=10)
    assert "volatility_regime_blocked" not in sig.vetoes or any(
        (s.get("detail") or {}).get("tradable") is False for s in sig.schools if s["school"].startswith("Volatility")
    )


def test_risk_halt():
    rm = RiskManager()
    rm.roll_day(10_000)
    rm.register_close(-200)
    assert rm.state.halted is True
    ok, reason = rm.allow_trade(9800, "buy")
    assert ok is False
    assert "daily_loss" in reason or reason
    reset = rm.reset_day(9800)
    assert reset["ok"] is True
    assert rm.state.halted is False


def test_api_health_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    isolated = UserAuth(tmp_path / "users.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", isolated)

    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["product"] == "AURUM"
    assert "auth" in h.json()

    s = client.get("/api/status")
    assert s.status_code == 200
    pub = s.json()
    # Anonymous status is redacted (no full signal dump)
    assert pub.get("auth", {}).get("authenticated") is False
    assert "signal" not in pub

    # protected routes require auth
    assert client.post("/api/start").status_code == 401
    assert client.get("/api/pulse").status_code == 401

    reg = client.post(
        "/api/auth/register",
        json={"username": "trader_x", "password": "Secret123", "password_confirm": "Secret123"},
    )
    assert reg.status_code == 200

    s2 = client.get("/api/status")
    assert s2.status_code == 200
    assert "signal" in s2.json()
    assert s2.json().get("auth", {}).get("authenticated") is True

    start = client.post("/api/start")
    assert start.status_code == 200
    body = start.json()
    assert body.get("ok") is True or body.get("error") in {"risk_halted", "not_live"}

    stop = client.post("/api/stop")
    assert stop.status_code == 200

    pulse = client.get("/api/pulse")
    assert pulse.status_code == 200
    assert "pulse" in pulse.json()

    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert "checks" in ready.json()
