"""Hardening: never fake-trade / fake-close on live FP Markets paths."""
from __future__ import annotations

from goldbot.execution.smart_exits import _is_live_trade
from goldbot.mt5.bridge import Bridge
from goldbot.mt5.broker import is_broker_server_suggestion, normalize_broker_server, resolve_fp_server


def test_is_live_trade_covers_all_real_executors():
    assert _is_live_trade({"mode": "mt5", "execution": "metaapi"}) is True
    assert _is_live_trade({"mode": "mt5", "execution": "ctrader"}) is True
    assert _is_live_trade({"mode": "mt5", "execution": "windows_bridge"}) is True
    assert _is_live_trade({"mode": "mt5", "execution": "mt5_linux"}) is True
    assert _is_live_trade({"mode": "ctrader", "execution": "ctrader"}) is True
    assert _is_live_trade({"mode": "paper", "execution": "paper"}) is False
    assert _is_live_trade({"mode": "paper"}) is False


def test_fp_markets_server_suggestions_reject_exness():
    assert is_broker_server_suggestion("FPMarkets-Live") is True
    assert is_broker_server_suggestion("FPTrading-Demo") is True
    assert is_broker_server_suggestion("Exness-MT5Real32") is False
    assert resolve_fp_server("Exness-MT5Real32") == ""
    assert resolve_fp_server("FPMarkets-Live") == "FPMarkets-Live"
    assert normalize_broker_server("fpmarkets live2") == "FPMarkets-Live2"


def test_mt5_mode_never_falls_back_to_paper_candles(monkeypatch):
    b = Bridge(mode="mt5", execution="ctrader")
    b._candle_cache = []
    b._candle_cache_ts = 0
    monkeypatch.setattr(b, "_fetch_paper", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paper fallback")))
    bars = b.fetch_candles(count=50)
    assert bars == []


def test_mt5_order_without_executor_is_rejected():
    b = Bridge(mode="mt5", execution="")
    b.metaapi_account_id = ""
    b.ctrader_account_id = None
    b.remote_user_id = None
    out = b.order_market("buy", 0.01, 2600, 2700)
    assert out["ok"] is False
    assert out["error"] == "no_live_executor"
    assert out["mode"] == "mt5"
