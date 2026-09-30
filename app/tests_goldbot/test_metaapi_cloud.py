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
        self.migrated = False
        self.create_calls = 0

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
            if "/historical-market-data/" in url and "/candles" in url:
                import time as _t

                base = int(_t.time()) - 15 * 60 * 80
                out = []
                px = 2650.0
                for i in range(80):
                    o = px
                    c = px + (0.3 if i % 2 == 0 else -0.2)
                    out.append(
                        {
                            "time": base + i * 900,
                            "open": o,
                            "high": max(o, c) + 0.4,
                            "low": min(o, c) - 0.4,
                            "close": c,
                            "tickVolume": 100 + i,
                        }
                    )
                    px = c
                return out
            acc_id = url.rstrip("/").split("/")[-1]
            if acc_id in self.accounts:
                return self.accounts[acc_id]
        if method == "POST" and url.endswith("/users/current/accounts"):
            # Simulate MetaApi "login already exists" when an account is present
            login = str((body or {}).get("login") or "")
            for acc in self.accounts.values():
                if str(acc.get("login")) == login:
                    raise MetaApiError(
                        "Account with this login already exists",
                        code="E_ACCOUNT_EXISTS",
                        status=400,
                    )
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
            self.create_calls += 1
            return {"id": acc_id, "state": "DEPLOYED"}
        if method == "POST" and url.endswith("/deploy"):
            acc_id = url.split("/accounts/")[1].split("/")[0]
            if acc_id in self.accounts:
                self.accounts[acc_id]["state"] = "DEPLOYED"
                self.accounts[acc_id]["connectionStatus"] = "CONNECTED"
            return {"ok": True}
        if method == "POST" and url.endswith("/undeploy"):
            acc_id = url.split("/accounts/")[1].split("/")[0]
            if acc_id in self.accounts:
                self.accounts[acc_id]["state"] = "UNDEPLOYED"
                self.accounts[acc_id]["connectionStatus"] = "DISCONNECTED"
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
        if method == "PUT" and "/users/current/accounts/" in url and not url.endswith("/password"):
            acc_id = url.rstrip("/").split("/")[-1]
            if acc_id not in self.accounts:
                raise MetaApiError("not found", code="NotFoundError", status=404)
            if body and body.get("server"):
                self.accounts[acc_id]["server"] = body["server"]
                self.migrated = True
            if body and body.get("name"):
                self.accounts[acc_id]["name"] = body["name"]
            self.accounts[acc_id]["state"] = "UNDEPLOYED"
            return dict(self.accounts[acc_id])
        if method == "DELETE" and "/users/current/accounts/" in url:
            acc_id = url.split("/accounts/")[1].split("?")[0].rstrip("/")
            self.accounts.pop(acc_id, None)
            return {"ok": True, "deleted": True, "id": acc_id}
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


def test_arabic_validation_failed_message():
    from goldbot.mt5.metaapi_cloud import MetaApiError, arabic_metaapi_error, is_validation_failed_error

    err = MetaApiError(
        "Validation failed (b68bf70cc3c140d5b4c5f3855561d3b7)",
        code="ValidationError",
    )
    assert is_validation_failed_error(err) is True
    ar = arabic_metaapi_error(err)
    assert "مصادقة" in ar or "رفض" in ar
    assert "كلمة مرور التداول" in ar
    assert "Exness-MT5Real32" in ar


def test_prepare_bound_account_ready(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Real32",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "new-york",
    }
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.prepare_bound_account(FAKE_ACCOUNT_ID, wait=True)
    assert out["ok"] is True
    assert out["bound"] is True
    assert out["connected"] is True
    assert out["account_id"] == FAKE_ACCOUNT_ID
    assert int(out["login"]) == 55667788


def test_cloud_bind_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "unit-test-token")
    monkeypatch.setattr("time.sleep", lambda *_: None)
    from goldbot.config import settings
    from goldbot.storage.state import DeskStore

    settings.metaapi_token = "unit-test-token"
    settings.prefer_metaapi = True
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Real32",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "new-york",
    }
    cloud = MetaApiCloud(token="unit-test-token", region="new-york", http=fake)
    monkeypatch.setattr("goldbot.api.metaapi", cloud)
    monkeypatch.setattr("goldbot.mt5.metaapi_cloud.metaapi", cloud)
    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)
    bridge.metaapi_account_id = ""
    bridge.execution = ""
    bridge.mode = "paper"
    client = TestClient(app)
    reg = client.post(
        "/api/auth/register",
        json={"username": "binder1", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200
    listed = client.get("/api/cloud/accounts")
    assert listed.status_code == 200
    assert listed.json()["ready_count"] >= 1
    bound = client.post("/api/cloud/bind", json={"account_id": FAKE_ACCOUNT_ID})
    assert bound.status_code == 200, bound.text
    body = bound.json()
    assert body["ok"] is True
    assert body["bound"] is True
    assert body["live_execution"] is True
    assert body["cloud"]["account_id"] == FAKE_ACCOUNT_ID


def test_force_new_deletes_stuck_account_then_recreates(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    stuck_id = FAKE_ACCOUNT_ID
    fake.accounts[stuck_id] = {
        "id": stuck_id,
        "login": "55667788",
        "server": "Exness-MT5Real32",
        "state": "DEPLOYED",
        "connectionStatus": "DISCONNECTED",
        "connectionError": "Validation failed (b68bf70cc3c140d5b4c5f3855561d3b7)",
        "region": "new-york",
    }
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account(
        "55667788",
        "TradePass1",
        "Exness-MT5Real32",
        existing_id=stuck_id,
        wait=True,
        force_new=True,
    )
    assert out["ok"] is True
    assert out["recreated"] is True
    assert out["connected"] is True
    assert stuck_id in fake.accounts  # recreated with same id in fake, but delete was called
    assert fake.create_calls >= 1
    # After purge+create there should be exactly one account for login
    assert len(client.find_accounts_by_login("55667788")) == 1


def test_metaapi_candles_and_bridge_feed(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Real32",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "new-york",
    }
    cloud = MetaApiCloud(token="test-token", region="new-york", http=fake)
    bars = cloud.candles(FAKE_ACCOUNT_ID, "XAUUSDm", "M15", count=80)
    assert len(bars) >= 50
    assert "close" in bars[0]

    from goldbot.config import settings
    from goldbot.mt5.bridge import Bridge

    settings.mode = "mt5"
    settings.prefer_metaapi = True
    settings.symbol = "XAUUSDm"
    monkeypatch.setattr("goldbot.mt5.metaapi_cloud.metaapi", cloud)
    b = Bridge()
    b.mode = "mt5"
    b.execution = "metaapi"
    b.metaapi_account_id = FAKE_ACCOUNT_ID
    b.metaapi_region = "new-york"
    candles = b.fetch_candles(count=60)
    assert len(candles) >= 50
    assert b._feed_source == "metaapi"


def test_force_cannot_bypass_risk_halt(monkeypatch):
    from goldbot.execution.desk import TradingDesk

    desk = TradingDesk()
    desk.risk.state.halted = True
    desk.risk.state.halt_reason = "daily_loss_cap"
    # Avoid network in scan
    monkeypatch.setattr(desk, "scan", lambda full=True: {
        "signal": {"action": "buy", "stop": 1, "take": 2, "confluence": 0.8, "quality": "A", "narrative": "x", "entry": 10},
        "execution_gate": {"allowed": True, "reason": "ok", "lot": 0.01},
        "pulse_confirm": True,
    })
    out = desk.execute_signal(force=True)
    assert out["ok"] is False
    assert out["error"] == "daily_loss_cap"


def test_find_account_by_login_rejects_cross_server():
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Trial15",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "new-york",
    }
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    assert client.find_account_by_login("55667788", "Exness-MT5Real32") is None
    assert client.find_account_by_login("55667788", "Exness-MT5Trial15")["id"] == FAKE_ACCOUNT_ID
    assert client.find_account_by_login("55667788")["server"] == "Exness-MT5Trial15"


def test_ensure_account_migrates_trial_to_real32(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Trial15",
        "state": "DEPLOYED",
        "connectionStatus": "DISCONNECTED",
        "region": "new-york",
    }
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account(
        "55667788",
        "TradePass1",
        "Exness-MT5Real32",
        wait=True,
        fast=False,
    )
    assert out["ok"] is True
    assert out["migrated"] is True
    assert out["connected"] is True
    assert fake.migrated is True
    assert fake.create_calls == 0
    assert fake.accounts[FAKE_ACCOUNT_ID]["server"] == "Exness-MT5Real32"


def test_ensure_account_migrates_existing_id_wrong_server(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Trial15",
        "state": "DEPLOYED",
        "connectionStatus": "CONNECTED",
        "region": "new-york",
    }
    client = MetaApiCloud(token="test-token", region="new-york", http=fake)
    out = client.ensure_account(
        "55667788",
        "TradePass1",
        "Exness-MT5Real32",
        existing_id=FAKE_ACCOUNT_ID,
        wait=True,
    )
    assert out["ok"] is True
    assert out["migrated"] is True
    assert fake.accounts[FAKE_ACCOUNT_ID]["server"] == "Exness-MT5Real32"


def test_cloud_diagnose_server_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "unit-test-token")
    monkeypatch.setenv("AURUM_PREFER_METAAPI", "1")
    monkeypatch.setattr("time.sleep", lambda *_: None)

    from goldbot.config import settings
    from goldbot.storage.state import DeskStore

    settings.metaapi_token = "unit-test-token"
    settings.prefer_metaapi = True

    fake = FakeMetaHttp()
    fake.accounts[FAKE_ACCOUNT_ID] = {
        "id": FAKE_ACCOUNT_ID,
        "login": "55667788",
        "server": "Exness-MT5Trial15",
        "state": "DEPLOYED",
        "connectionStatus": "DISCONNECTED",
        "region": "new-york",
    }
    cloud = MetaApiCloud(token="unit-test-token", region="new-york", http=fake)
    monkeypatch.setattr("goldbot.api.metaapi", cloud)
    monkeypatch.setattr("goldbot.mt5.metaapi_cloud.metaapi", cloud)

    users = UserAuth(tmp_path / "users.sqlite3")
    store = DeskStore(tmp_path / "desk.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.store", store)
    monkeypatch.setattr("goldbot.storage.state.store", store)
    monkeypatch.setattr("goldbot.auth.users.auth", users)

    bridge.metaapi_account_id = ""
    bridge.metaapi_region = ""
    bridge.execution = ""
    bridge.remote_user_id = None
    bridge.mode = "paper"

    client = TestClient(app)
    # Register then save MT5 secrets pointing at Real32 while MetaApi still has Trial
    reg = client.post(
        "/api/auth/register",
        json={"username": "diag1", "password": "password12", "password_confirm": "password12"},
    )
    assert reg.status_code == 200
    uid = reg.json()["user"]["id"]
    users.update_settings(
        uid,
        {
            "mt5_login": "55667788",
            "mt5_password": "TradePass1",
            "mt5_server": "Exness-MT5Real32",
            "metaapi_account_id": FAKE_ACCOUNT_ID,
            "mode": "mt5",
        },
    )
    # update_settings may not accept password plaintext the same way — use login_with_mt5 path
    users.login_with_mt5("55667788", "TradePass1", "Exness-MT5Real32", "XAUUSDm")

    diag = client.get("/api/cloud/diagnose")
    assert diag.status_code == 200, diag.text
    body = diag.json()
    assert body["ok"] is True
    assert body["requested_server"] == "Exness-MT5Real32"
    assert any(i.get("code") == "E_SERVER_MISMATCH" for i in body.get("issues") or [])
    assert body["error_code"] == "E_SERVER_MISMATCH"
