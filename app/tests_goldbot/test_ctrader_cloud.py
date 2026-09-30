"""cTrader Open API path — real FP Markets/cTrader from the app (no Windows)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.mt5 import ctrader_cloud as ctrader_mod
from goldbot.mt5.bridge import bridge
from goldbot.mt5.ctrader_cloud import CTraderCloud, CTraderError, arabic_ctrader_error
from goldbot.storage.state import DeskStore


def test_arabic_ctrader_errors():
    assert "openapi.ctrader.com" in arabic_ctrader_error(CTraderError("x", code="NO_APP"))
    assert "تفويض" in arabic_ctrader_error(CTraderError("x", code="NO_TOKEN"))
    assert "اختر" in arabic_ctrader_error(CTraderError("select account", code="NO_ACCOUNT"))


def test_ways_includes_ctrader(monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    client = TestClient(app)
    r = client.get("/api/ways")
    assert r.status_code == 200
    body = r.json()
    ids = [w["id"] for w in body["ways"]]
    assert "ctrader" in ids
    assert body["ways"][0]["id"] == "ctrader"


def test_ctrader_save_app_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    saved: dict = {}
    monkeypatch.setattr(ctrader_mod, "_load_kv", lambda: dict(saved))

    def _save(patch):
        saved.update({k: v for k, v in patch.items() if v is not None})
        return dict(saved)

    monkeypatch.setattr(ctrader_mod, "_save_kv", _save)
    cloud = CTraderCloud()
    monkeypatch.setattr("goldbot.api.ctrader", cloud)
    monkeypatch.setattr(ctrader_mod, "ctrader", cloud)

    client = TestClient(app)
    reg = client.post(
        "/api/auth/register",
        json={"username": "ctuser", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200, reg.text

    r = client.post(
        "/api/ctrader/app",
        json={"client_id": "cid-test", "client_secret": "secret-test", "live": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["configured"] is True
    assert "oauth/callback" in r.json()["redirect_uri"]

    st = client.get("/api/ctrader/status")
    assert st.status_code == 200
    body = st.json()
    assert body["configured"] is True
    assert body["ready"] is False
    assert body["has_token"] is False


def test_ctrader_bind_and_bridge_order(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    from goldbot.config import settings

    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    saved = {
        "client_id": "cid",
        "client_secret": "sec",
        "access_token": "tok",
        "live": "1",
    }
    monkeypatch.setattr(ctrader_mod, "_load_kv", lambda: dict(saved))

    def _save(patch):
        saved.update({k: v for k, v in patch.items() if v is not None})
        return dict(saved)

    monkeypatch.setattr(ctrader_mod, "_save_kv", _save)

    class FakeCloud(CTraderCloud):
        def snapshot(self):
            self.refresh()
            return {
                "connected": True,
                "balance": 2500.0,
                "equity": 2510.0,
                "margin": 50.0,
                "free_margin": 2460.0,
                "currency": "USD",
                "server": "cTrader-Live",
                "login": 990011,
                "detail": "test ctrader",
                "account_id": self.account_id,
            }

        def order_market(self, side, lot, sl, tp, *, symbol="XAUUSD", comment="AURUM"):
            return {
                "ok": True,
                "mode": "mt5",
                "execution": "ctrader",
                "side": side,
                "lot": lot,
                "price": 2650.5,
                "entry": 2650.5,
                "sl": sl,
                "tp": tp,
                "ticket": 42,
                "position_id": "42",
            }

        def list_accounts(self):
            return [
                {
                    "ctidTraderAccountId": 123456,
                    "isLive": True,
                    "traderLogin": 990011,
                    "brokerTitle": "FP Markets",
                    "depositCurrency": "USD",
                }
            ]

    cloud = FakeCloud()
    monkeypatch.setattr("goldbot.api.ctrader", cloud)
    monkeypatch.setattr(ctrader_mod, "ctrader", cloud)
    settings.prefer_ctrader = True

    client = TestClient(app)
    reg = client.post(
        "/api/auth/register",
        json={"username": "ctbind", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]

    accounts = client.get("/api/ctrader/accounts")
    assert accounts.status_code == 200
    assert accounts.json()["count"] == 1

    bind = client.post("/api/ctrader/bind", json={"account_id": 123456, "live": True})
    assert bind.status_code == 200, bind.text
    body = bind.json()
    assert body["ok"] is True
    assert body["account"]["connected"] is True
    assert body["bridge"]["provider"] == "ctrader"

    secrets = users.mt5_secrets(uid)
    assert secrets["execution"] == "ctrader"
    assert secrets["ctrader_account_id"] == "123456"

    bridge.bind_ctrader(123456)
    assert bridge.execution == "ctrader"
    assert bridge.is_live_execution() is True
    order = bridge.order_market("buy", 0.01, 2640.0, 2665.0)
    assert order["ok"] is True
    assert order["execution"] == "ctrader"


def test_oauth_start_requires_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    monkeypatch.setattr(ctrader_mod, "_load_kv", lambda: {})
    cloud = CTraderCloud()
    monkeypatch.setattr("goldbot.api.ctrader", cloud)

    client = TestClient(app)
    client.post(
        "/api/auth/register",
        json={"username": "ctoauth", "password": "password12", "password_confirm": "password12"},
    )
    r = client.get("/api/ctrader/oauth/start")
    assert r.status_code == 400
    assert "openapi.ctrader.com" in r.json()["detail"]
