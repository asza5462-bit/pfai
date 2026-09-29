"""MetaApi cloud path — direct Exness without Windows."""
from __future__ import annotations

from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.mt5.bridge import bridge
from goldbot.mt5.metaapi_cloud import MetaApiCloud, MetaApiError


FAKE_ACCOUNT_ID = "b3cd8053-0252-4dd8-a5aa-e4e4491e211f"


class FakeMetaHttp:
    def __init__(self):
        self.accounts = {}
        self.created = False

    def __call__(self, method, url, body=None, **kwargs):
        method = method.upper()
        if method == "GET" and url.endswith("/users/current/accounts"):
            return list(self.accounts.values())
        if method == "GET" and "/users/current/accounts/" in url and url.count("/") >= 5:
            # get account / account-information / positions / price
            if url.endswith("/account-information"):
                acc_id = url.split("/accounts/")[1].split("/")[0]
                acc = self.accounts[acc_id]
                return {
                    "balance": 5000.0,
                    "equity": 5012.5,
                    "margin": 100.0,
                    "freeMargin": 4912.5,
                    "currency": "USD",
                    "server": acc["server"],
                    "login": int(acc["login"]),
                    "tradeAllowed": True,
                }
            if url.endswith("/positions"):
                return []
            if "/symbols/" in url and url.endswith("/current-price"):
                return {"bid": 2655.1, "ask": 2655.35}
            acc_id = url.rstrip("/").split("/")[-1]
            if acc_id in self.accounts:
                return self.accounts[acc_id]
        if method == "POST" and url.endswith("/users/current/accounts"):
            acc_id = FAKE_ACCOUNT_ID
            self.accounts[acc_id] = {
                "id": acc_id,
                "login": body["login"],
                "server": body["server"],
                "state": "DEPLOYED",
                "connectionStatus": "CONNECTED",
                "region": "new-york",
            }
            self.created = True
            return {"id": acc_id, "state": "DEPLOYED"}
        if method == "POST" and url.endswith("/deploy"):
            return {"ok": True}
        if method == "POST" and url.endswith("/trade"):
            return {
                "numericCode": 10009,
                "stringCode": "TRADE_RETCODE_DONE",
                "message": "Done",
                "orderId": "77881",
                "positionId": "77881",
            }
        if method == "PUT" and url.endswith("/password"):
            return {"ok": True}
        raise MetaApiError(f"unexpected {method} {url}", code="TEST")


def test_account_id_validation():
    from goldbot.mt5.metaapi_cloud import is_metaapi_account_id, normalize_account_id

    assert is_metaapi_account_id("1215") is False
    assert is_metaapi_account_id("55667788") is False
    assert is_metaapi_account_id("b3cd805302524dd8a5aae4e4491e211f") is True
    assert is_metaapi_account_id("b3cd8053-0252-4dd8-a5aa-e4e4491e211f") is True
    assert normalize_account_id("b3cd805302524dd8a5aae4e4491e211f") == "b3cd8053-0252-4dd8-a5aa-e4e4491e211f"
    assert normalize_account_id("1215") == ""


def test_normalize_exness_server_real32():
    from goldbot.mt5.metaapi_cloud import normalize_exness_server

    assert normalize_exness_server("Exness-MT5Real32") == "Exness-MT5Real32"
    assert normalize_exness_server("exness-mt5real32") == "Exness-MT5Real32"
    assert normalize_exness_server("Exness MT5 Real32") == "Exness-MT5Real32"


def test_ensure_account_real32_server(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account(
        "55667788",
        "TradePass1",
        "Exness MT5 Real32",
        wait=True,
    )
    assert out["ok"] is True
    assert out["connected"] is True
    assert fake.accounts[FAKE_ACCOUNT_ID]["server"] == "Exness-MT5Real32"


def test_ensure_account_ignores_stale_numeric_id(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account(
        "55667788",
        "TradePass1",
        "Exness-MT5Trial15",
        existing_id="1215",  # corrupt id from production bug
        wait=True,
    )
    assert out["ok"] is True
    assert out["account_id"] == FAKE_ACCOUNT_ID
    assert out["connected"] is True


def test_metaapi_ensure_and_order(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account("55667788", "TradePass1", "Exness-MT5Trial", wait=True)
    assert out["ok"] is True
    assert out["account_id"] == FAKE_ACCOUNT_ID
    assert out["connected"] is True
    assert fake.created is True

    snap = client.snapshot(FAKE_ACCOUNT_ID)
    assert snap["connected"] is True
    assert snap["equity"] == 5012.5

    order = client.order_market(FAKE_ACCOUNT_ID, "buy", 0.01, 2600.0, 2700.0, symbol="XAUUSD")
    assert order["ok"] is True
    assert order["ticket"] == 77881
    assert order["mode"] == "metaapi"


def test_save_metaapi_token_from_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "")
    from goldbot.config import settings
    from goldbot.storage.state import DeskStore

    settings.metaapi_token = ""
    settings.prefer_metaapi = True
    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    fake = FakeMetaHttp()
    cloud = MetaApiCloud(token="", region="new-york", http=fake)
    monkeypatch.setattr("goldbot.api.metaapi", cloud)
    monkeypatch.setattr("goldbot.mt5.metaapi_cloud.metaapi", cloud)

    client = TestClient(app)
    reg = client.post(
        "/api/auth/register",
        json={"username": "owner1", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200

    saved = client.post("/api/cloud/token", json={"token": "my-real-metaapi-token-abc", "check_token": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["metaapi_configured"] is True
    assert cloud.configured is True
    assert store.get_kv("metaapi_token_enc")


def test_mt5_login_uses_metaapi_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "unit-test-token")
    monkeypatch.setenv("AURUM_PREFER_METAAPI", "1")
    monkeypatch.setattr("time.sleep", lambda *_: None)

    # Reload settings fields used by metaapi singleton
    from goldbot.config import settings

    settings.metaapi_token = "unit-test-token"
    settings.prefer_metaapi = True

    fake = FakeMetaHttp()
    cloud = MetaApiCloud(token="unit-test-token", region="new-york", http=fake)
    monkeypatch.setattr("goldbot.api.metaapi", cloud)
    monkeypatch.setattr("goldbot.mt5.metaapi_cloud.metaapi", cloud)

    users = UserAuth(tmp_path / "users.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)

    # reset bridge cloud binding
    bridge.metaapi_account_id = ""
    bridge.metaapi_region = ""
    bridge.execution = ""
    bridge.remote_user_id = None
    bridge.mode = "paper"

    client = TestClient(app)
    login = client.post(
        "/api/auth/mt5-login",
        json={
            "mt5_login": "55667788",
            "mt5_password": "TradePass1",
            "mt5_server": "Exness-MT5Trial",
            "symbol": "XAUUSD",
            "auto_start": False,
        },
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["ok"] is True
    assert body["execution"] == "metaapi"
    assert body["cloud"]["account_id"] == FAKE_ACCOUNT_ID
    assert body["account"]["connected"] is True
    assert body["user"]["settings"]["metaapi_account_id"] == FAKE_ACCOUNT_ID
    assert "بدون Windows" in (body.get("message") or "") or body["account"]["connected"]

    # Order goes through MetaApi
    bridge.bind_metaapi(FAKE_ACCOUNT_ID, "new-york")
    result = bridge.order_market("buy", 0.02, 2600, 2720, comment="TEST")
    assert result["ok"] is True
    assert result["execution"] == "metaapi"
    assert result["ticket"] == 77881

    st = client.get("/api/bridge/status")
    assert st.status_code == 200
    assert st.json()["bridge"]["online"] is True
    assert st.json()["bridge"]["provider"] == "metaapi"
    assert st.json()["windows_required"] is False
