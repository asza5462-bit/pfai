from fastapi.testclient import TestClient

from goldbot.api import app
from goldbot.auth.users import UserAuth


def test_register_login_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COOKIE_SECURE", "0")
    # isolate auth db
    isolated = UserAuth(tmp_path / "users.sqlite3")
    monkeypatch.setattr("goldbot.api.auth", isolated)
    monkeypatch.setattr("goldbot.auth.users.auth", isolated)

    client = TestClient(app)
    st = client.get("/api/auth/status")
    assert st.status_code == 200
    assert st.json()["needs_setup"] is True

    reg = client.post(
        "/api/auth/register",
        json={"username": "owner1", "password": "Secret123", "password_confirm": "Secret123"},
    )
    assert reg.status_code == 200, reg.text
    assert reg.json()["user"]["username"] == "owner1"
    assert "aurum_session" in reg.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "owner1"

    # protected scan works with cookie
    scan = client.post("/api/scan")
    assert scan.status_code == 200
    assert "signal" in scan.json()

    client.post("/api/auth/logout")
    denied = client.post("/api/scan")
    assert denied.status_code == 401

    login = client.post("/api/auth/login", json={"username": "owner1", "password": "Secret123"})
    assert login.status_code == 200
    assert login.json()["ok"] is True
