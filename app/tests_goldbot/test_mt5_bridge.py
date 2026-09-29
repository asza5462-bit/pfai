from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth
from goldbot.mt5.remote_hub import RemoteHub


def test_mt5_login_and_bridge_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    users = UserAuth(tmp_path / "users.sqlite3")
    hub = RemoteHub(tmp_path / "hub.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", users)
    monkeypatch.setattr("goldbot.api.hub", hub)

    client = TestClient(app)
    servers = client.get("/api/exness/servers")
    assert servers.status_code == 200
    assert "Exness-MT5Trial" in servers.json()["servers"]

    login = client.post(
        "/api/auth/mt5-login",
        json={
            "mt5_login": "55667788",
            "mt5_password": "TradePass1",
            "mt5_server": "Exness-MT5Trial",
            "symbol": "XAUUSD",
            "auto_start": True,
        },
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["ok"] is True
    assert body["user"]["settings"]["mt5_login"] == "55667788"
    assert body["user"]["settings"]["mode"] == "mt5"
    assert body.get("bridge_token")
    token = body["bridge_token"]

    # agent heartbeat -> online
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
                "server": "Exness-MT5Trial",
                "login": 55667788,
            },
        },
    )
    assert hb.status_code == 200

    creds = client.get("/api/bridge/credentials", headers={"Authorization": f"Bearer {token}"})
    assert creds.status_code == 200
    assert creds.json()["login"] == 55667788
    assert creds.json()["password"] == "TradePass1"

    st = client.get("/api/bridge/status")
    assert st.status_code == 200
    assert st.json()["bridge"]["online"] is True

    # enqueue order via desk bind
    from goldbot.mt5.bridge import bridge

    bridge.bind_remote_user(body["user"]["id"])
    bridge.mode = "mt5"
    enq = hub.enqueue(body["user"]["id"], "order_market", {"side": "buy", "lot": 0.01, "sl": 1, "tp": 2, "symbol": "XAUUSD"})
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
