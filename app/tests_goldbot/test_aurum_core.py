from fastapi.testclient import TestClient

from goldbot.api import app
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
    # force a hammer-like last bar
    last = cs[-1]
    cs[-1] = Candle(last.time, last.close + 2, last.close + 2.2, last.close - 6, last.close + 1.5, 2000)
    assert isinstance(detect_patterns(cs), list)
    sig = build_signal(cs, spread_points=10)
    assert sig.action in {"buy", "sell", "flat"}
    assert 0 <= sig.confluence <= 1
    assert hasattr(sig, "quality")


def test_vol_veto_uses_tradable_not_neutral_bias():
    """Regression: flat trend must not block when ATR regime is tradable."""
    cs = _candles(n=100, start=4100)
    sig = build_signal(cs, spread_points=10)
    assert "volatility_regime_blocked" not in sig.vetoes or any(
        (s.get("detail") or {}).get("tradable") is False for s in sig.schools if s["school"].startswith("Volatility")
    )


def test_risk_halt():
    rm = RiskManager()
    rm.roll_day(10_000)
    rm.register_close(-200)  # 2% > 1.25% default
    assert rm.state.halted is True
    ok, reason = rm.allow_trade(9800, "buy")
    assert ok is False
    assert "daily_loss" in reason or reason


def test_api_health_and_status():
    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["product"] == "AURUM"
    s = client.get("/api/status")
    assert s.status_code == 200
    body = s.json()
    assert "signal" in body
    assert "disclaimer" in body
    g = client.get("/api/connect-guide")
    assert g.status_code == 200
    assert "MT5" in g.json()["title"] or "MetaTrader" in g.json()["title"]
    start = client.post("/api/start")
    assert start.status_code == 200
    assert start.json()["auto_trade"] is True
    stop = client.post("/api/stop")
    assert stop.status_code == 200
    assert stop.json()["auto_trade"] is False
    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert "paper_ready" in ready.json()
    assert "checks" in ready.json()
    pulse = client.get("/api/pulse")
    assert pulse.status_code == 200
    body = pulse.json()
    assert "pulse" in body
    assert "elapsed_ms" in body
    assert "state" in body
