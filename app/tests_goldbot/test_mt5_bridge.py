"""Legacy Windows bridge endpoints still work as optional fallback."""
from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.mt5.remote_hub import RemoteHub


def test_windows_bridge_agent_protocol(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    monkeypatch.setenv("METAAPI_TOKEN", "")
    monkeypatch.setenv("AURUM_PREFER_METAAPI", "0")

    from goldbot.config import settings

    settings.metaapi_token = ""
    settings.prefer_metaapi = False

    users = UserAuth(tmp_path / "users.sqlite3")
    hub = RemoteHub(tmp_path / "hub.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.hub", hub)
    # Force api.metaapi.configured False
    from goldbot.mt5.metaapi_cloud import MetaApiCloud

    monkeypatch.setattr("goldbot.api.metaapi", MetaApiCloud(token=""))

    client = TestClient(app)
    servers = client.get("/api/broker/servers")
    assert servers.status_code == 200
    assert "FPMarkets-Demo" in servers.json()["servers"]

    login = client.post(
        "/api/auth/mt5-login",
        json={
            "mt5_login": "55667788",
            "mt5_password": "TradePass1",
            "mt5_server": "FPMarkets-Demo",
            "symbol": "XAUUSD",
            "auto_start": False,
        },
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["ok"] is True
    assert body["user"]["settings"]["mt5_login"] == "55667788"
    uid = body["user"]["id"]

    # Issue bridge token manually (legacy path)
    token = hub.issue_token(uid)

    hb = client.post(
        "/api/bridge/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "info": {"agent": "test"},
            "account": {
                "balance": 5000,
                "equity": 5000,
                "margin": 0,
                "free_margin": 5000,
                "currency": "USD",
                "server": "FPMarkets-Demo",
                "login": 55667788,
            },
        },
    )
    assert hb.status_code == 200

    creds = client.get("/api/bridge/credentials", headers={"Authorization": f"Bearer {token}"})
    assert creds.status_code == 200
    assert creds.json()["login"] == 55667788
    assert creds.json()["password"] == "TradePass1"

    from goldbot.mt5.bridge import bridge

    bridge.bind_remote_user(uid)
    bridge.mode = "mt5"
    bridge.execution = "windows_bridge"
    bridge.metaapi_account_id = ""
    enq = hub.enqueue(uid, "order_market", {"side": "buy", "lot": 0.01, "sl": 1, "tp": 2, "symbol": "XAUUSD"})
    assert enq["ok"] is True
    polled = client.get("/api/bridge/poll", headers={"Authorization": f"Bearer {token}"})
    assert polled.status_code == 200
    cmds = polled.json()["commands"]
    assert len(cmds) == 1
    done = client.post(
        "/api/bridge/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"command_id": cmds[0]["id"], "result": {"ok": True, "ticket": 99, "price": 4100, "mode": "mt5"}},
    )
    assert done.status_code == 200


def test_mt5_mode_never_paper_fills_without_executor(monkeypatch):
    """Live MT5 mode must refuse orders instead of faking paper fills."""
    from goldbot.mt5.bridge import bridge
    from goldbot.config import settings

    monkeypatch.setenv("METAAPI_TOKEN", "")
    settings.metaapi_token = ""
    settings.prefer_metaapi = True
    settings.prefer_mt5_linux = False
    bridge.mode = "mt5"
    bridge.execution = ""
    bridge.metaapi_account_id = ""
    bridge.remote_user_id = None
    bridge._mt5 = None

    result = bridge.order_market("buy", 0.01, 2600, 2700, comment="NO-FAKE")
    assert result["ok"] is False
    assert result.get("error") == "no_live_executor"
    assert result.get("mode") == "mt5"
    assert "وهمي" in (result.get("detail") or "") or "حقيقي" in (result.get("detail") or "")
