"""Linux Docker MT5 executor path (no Windows OS)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.mt5.mt5_linux import Mt5LinuxClient, Mt5LinuxError
from goldbot.storage.state import DeskStore


class FakeLinuxHttp:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None, timeout=45.0):
        self.calls.append((method, path, body))
        if path in {"/", ""}:
            return {"status": "ok"}
        if path.endswith("/connect"):
            return {"success": True, "message": "connected"}
        if path.endswith("/account"):
            return {
                "login": 55667788,
                "balance": 2500.0,
                "equity": 2510.0,
                "margin": 50.0,
                "margin_free": 2460.0,
                "currency": "USD",
                "server": "FPMarkets-Demo",
            }
        if path.endswith("/order/send"):
            return {"success": True, "order": 4242, "price": 2655.2, "retcode": 10009}
        raise Mt5LinuxError(f"unexpected {path}")


def test_mt5_linux_order_and_snapshot(monkeypatch):
    fake = FakeLinuxHttp()
    client = Mt5LinuxClient(base_url="http://linux-host:5001", token="")
    monkeypatch.setattr(client, "_req", fake)
    snap = client.snapshot()
    assert snap["connected"] is True
    assert snap["equity"] == 2510.0
    order = client.order_market("buy", 0.01, 2600, 2700, symbol="XAUUSD")
    assert order["ok"] is True
    assert order["execution"] == "mt5_linux"
    assert order["ticket"] == 4242


def test_ways_and_save_linux_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "")
    from goldbot.config import settings

    settings.metaapi_token = ""
    settings.mt5_linux_url = ""
    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    fake_client = Mt5LinuxClient(base_url="", token="")
    fake = FakeLinuxHttp()
    monkeypatch.setattr(fake_client, "_req", fake)

    def set_config(url, token=""):
        fake_client.base_url = url.rstrip("/")
        fake_client.token = token
        settings.mt5_linux_url = fake_client.base_url
        store.set_kv("mt5_linux_url", fake_client.base_url)

    monkeypatch.setattr(fake_client, "set_config", set_config)
    monkeypatch.setattr("goldbot.api.mt5_linux", fake_client)
    monkeypatch.setattr("goldbot.mt5.mt5_linux.mt5_linux", fake_client)

    client = TestClient(app)
    ways = client.get("/api/ways")
    assert ways.status_code == 200
    body = ways.json()
    assert body["ok"] is True
    assert len(body["ways"]) >= 1
    assert any(w["id"] == "ctrader" for w in body["ways"])
    assert body.get("primary") == "ctrader"

    reg = client.post(
        "/api/auth/register",
        json={"username": "traderx", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200

    saved = client.post(
        "/api/executor/linux",
        json={"base_url": "http://10.0.0.5:5001", "token": "", "probe": True},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["mt5_linux_configured"] is True
    assert store.get_kv("mt5_linux_url") == "http://10.0.0.5:5001"
