from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_index(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["name"] == "NOVA Code"
    assert response.json()["version"] == "2.0.0"
    index = client.get("/")
    assert index.status_code == 200
    assert "NOVA Code" in index.text
    assert "cTrader" not in index.text
    assert client.head("/").status_code == 200
    assert client.head("/health").status_code == 200


def test_owner_setup_and_auth(client: TestClient):
    status = client.get("/api/auth/status").json()
    assert status["needs_setup"] is True
    setup = client.post(
        "/api/auth/setup",
        json={"username": "owner", "password": "a-strong-password", "setup_token": "test-setup-token"},
    )
    assert setup.status_code == 200
    assert setup.json()["user"]["role"] == "owner"
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_workspace_file_and_path_guards(client: TestClient):
    created = client.post(
        "/api/projects",
        json={"name": "اختبار NOVA", "description": "workspace", "template": "python"},
    )
    assert created.status_code == 200
    project_id = created.json()["project"]["id"]

    tree = client.get(f"/api/projects/{project_id}/tree")
    assert tree.status_code == 200
    assert any(node["name"] == "main.py" for node in tree.json()["tree"])

    write = client.put(
        f"/api/projects/{project_id}/file",
        json={"path": "src/hello.py", "content": "print('hello')\n"},
    )
    assert write.status_code == 200
    read = client.get(f"/api/projects/{project_id}/file", params={"path": "src/hello.py"})
    assert read.json()["content"] == "print('hello')\n"

    traversal = client.get(f"/api/projects/{project_id}/file", params={"path": "../secret"})
    assert traversal.status_code == 400

    blocked = client.post(f"/api/projects/{project_id}/command", json={"command": "bash -c env"})
    assert blocked.status_code == 403


def test_provider_secret_is_not_returned(client: TestClient):
    saved = client.put(
        "/api/provider",
        json={
            "provider": "openai",
            "model": "gpt-test",
            "api_key": "sk-example-secret-never-returned",
            "base_url": "https://example.invalid/v1",
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["configured"] is True
    assert "sk-example" not in json.dumps(payload)


def test_agent_writes_real_file(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    project_id = client.get("/api/projects").json()["projects"][0]["id"]
    conversation = client.post(
        f"/api/projects/{project_id}/conversations",
        json={"title": "Build"},
    ).json()["conversation"]

    async def fake_complete(*_args, **_kwargs):
        return json.dumps(
            {
                "message": "تم إنشاء الوحدة واختبارها.",
                "status": "complete",
                "actions": [
                    {"type": "write", "path": "src/generated.py", "content": "ANSWER = 42\n"},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.agent.complete", fake_complete)
    response = client.post(
        f"/api/projects/{project_id}/chat",
        json={
            "conversation_id": conversation["id"],
            "message": "أنشئ وحدة",
            "auto_apply": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["changed_files"] == ["src/generated.py"]
    generated = client.get(f"/api/projects/{project_id}/file", params={"path": "src/generated.py"})
    assert generated.json()["content"] == "ANSWER = 42\n"


def test_agent_commands_require_explicit_approval(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    project_id = client.get("/api/projects").json()["projects"][0]["id"]
    conversation = client.post(
        f"/api/projects/{project_id}/conversations",
        json={"title": "Approval"},
    ).json()["conversation"]

    async def fake_complete(*_args, **_kwargs):
        return json.dumps(
            {
                "message": "أحتاج تشغيل الاختبارات.",
                "status": "complete",
                "actions": [{"type": "run", "command": "pytest -q"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.agent.complete", fake_complete)
    response = client.post(
        f"/api/projects/{project_id}/chat",
        json={
            "conversation_id": conversation["id"],
            "message": "اختبر المشروع",
            "auto_apply": True,
            "allow_commands": False,
        },
    )
    assert response.status_code == 200
    command = response.json()["commands"][0]
    assert command["approval_required"] is True
