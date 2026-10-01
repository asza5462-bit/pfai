from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body


def test_info():
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_index():
    r = client.get("/")
    assert r.status_code == 200
    assert "ORBIT" in r.text
