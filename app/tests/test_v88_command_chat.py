"""Command Chat integration tests: agent, memory, router, owner gate, audit, mock."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.command_audit import CommandAuditLog
from pfai.command_memory import CommandMemoryService
from pfai.command_agent import CommandAgent
from pfai.memory import MemoryStore
from pfai.model_mock import MockCommandProvider
from pfai.tool_router import ToolRouter, ToolSpec


class TestMockProvider(unittest.TestCase):
    def test_plans_health_ar_and_en(self):
        m = MockCommandProvider()
        tools = {t["tool"] for t in m.plan_tools("شغّل فحص الصحة", ["health_check", "system_status"])}
        self.assertIn("health_check", tools)
        tools = {t["tool"] for t in m.plan_tools("Run health check", ["health_check", "system_status"])}
        self.assertIn("health_check", tools)

    def test_generate_is_mock_not_secret(self):
        text = MockCommandProvider().generate("hello")
        self.assertIn("PFAI-MOCK", text)
        self.assertNotIn("sk-", text)


class TestToolRouterGate(unittest.TestCase):
    def test_sensitive_requires_approval(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            return {"started": True}

        router = ToolRouter(
            {"continuous_start": boom},
            specs=[ToolSpec("continuous_start", "start", "sensitive", True, {})],
        )
        blocked = router.execute("continuous_start", {}, approved=False)
        self.assertTrue(blocked.get("needs_approval"))
        self.assertEqual(calls["n"], 0)
        ok = router.execute("continuous_start", {}, approved=True)
        self.assertTrue(ok.get("ok"))
        self.assertEqual(calls["n"], 1)


class TestCommandMemory(unittest.TestCase):
    def test_remember_search_correct_forget(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            svc = CommandMemoryService(mem, str(Path(d) / "chat.sqlite3"))
            mid = svc.remember("preference", "Prefer Arabic replies", source="test")
            hits = svc.relevant("Arabic")
            self.assertTrue(any(h["id"] == mid for h in hits))
            self.assertTrue(svc.correct(mid, "Prefer concise Arabic replies"))
            self.assertEqual(mem.get(mid)["content"], "Prefer concise Arabic replies")
            self.assertTrue(svc.forget(mid))
            self.assertIsNone(mem.get(mid))


class TestCommandAgentFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.mem = MemoryStore(str(Path(d) / "m.sqlite3"))
        self.svc = CommandMemoryService(self.mem, str(Path(d) / "chat.sqlite3"))
        self.audit = CommandAuditLog(str(Path(d) / "audit.jsonl"))
        self.flags = {"started": False}

        def health():
            return {"status": "ok"}

        def start():
            self.flags["started"] = True
            return {"status": "running"}

        self.router = ToolRouter(
            {
                "health_check": health,
                "system_status": lambda: {"health": {"status": "ok"}},
                "metrics_snapshot": lambda: {"counters": {}},
                "continuous_status": lambda: {"service": {"status": "stopped"}},
                "continuous_start": start,
                "propose_improvement": lambda topic="": {"suggestions": ["x"], "topic": topic},
                "save_owner_correction": lambda content="": {"memory_id": self.svc.remember("correction", content)},
                "knowledge_search": lambda q="", limit=5: {"results": []},
                "memory_search": lambda q="", limit=5: {"results": self.svc.relevant(q, limit)},
                "modules_list": lambda: {"modules": ["command_chat"]},
                "deployments_list": lambda: {"items": []},
                "recovery_verify": lambda: {"valid": True},
                "research_verify": lambda: {"valid": True, "network_enabled": False, "allowed_domains": []},
                "regression_pending": lambda: {"items": []},
                "chat_audit_recent": lambda limit=20: {"items": self.audit.recent(limit)},
                "remember_knowledge": lambda kind="approved_knowledge", content="": {"memory_id": self.svc.remember(kind, content)},
                "forget_memory": lambda memory_id=0: {"forgotten": self.svc.forget(int(memory_id))},
                "correct_memory": lambda memory_id=0, content="": {"corrected": self.svc.correct(int(memory_id), content)},
                "continuous_pause": lambda: {"status": "paused"},
                "continuous_resume": lambda: {"status": "running"},
                "continuous_stop": lambda: {"status": "stopped"},
            }
        )
        self.agent = CommandAgent(self.router, self.svc, self.audit, model=None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_command_completes_with_mock(self):
        r = self.agent.handle("شغّل فحص الصحة", owner="owneruser")
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["provider"], "mock-command")
        self.assertTrue(any(s["status"] == "executing" for s in r["timeline"]))
        self.assertTrue(any(t.get("tool") == "health_check" and t.get("ok") for t in r["tools"]))

    def test_sensitive_tool_waits_for_approval(self):
        r = self.agent.handle("start continuous learning now", owner="owneruser")
        self.assertEqual(r["status"], "waiting_for_approval")
        self.assertIsNotNone(r.get("pending"))
        self.assertFalse(self.flags["started"])
        approved = self.agent.approve(r["pending"]["pending_id"], owner="owneruser")
        self.assertTrue(approved["ok"])
        self.assertTrue(self.flags["started"])
        events = self.audit.recent(10)
        self.assertTrue(any(e["status"] == "waiting_for_approval" for e in events))
        self.assertTrue(any(e.get("approved") is True for e in events))

    def test_reject_sensitive_tool(self):
        r = self.agent.handle("start continuous training", owner="owneruser")
        rejected = self.agent.reject(r["pending"]["pending_id"], owner="owneruser")
        self.assertTrue(rejected["ok"])
        self.assertFalse(self.flags["started"])


class TestChatAPIWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        runtime.agent.model = runtime.model
        if getattr(runtime.agent, "rag", None):
            runtime.agent.rag.model = runtime.model
        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_SECRET_HASH", None)

    def test_chat_requires_owner(self):
        self.assertEqual(self.client.post("/chat/message", json={"message": "health"}).status_code, 401)

    def test_chat_health_and_audit(self):
        r = self.client.post("/chat/message", json={"message": "Run health check"}, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn(body.get("status"), {"completed", "waiting_for_approval"})
        self.assertTrue(body.get("conversation_id"))
        audit = self.client.get("/chat/audit", headers=self.headers)
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(isinstance(audit.json().get("items"), list))

    def test_chat_tools_and_assets(self):
        tools = self.client.get("/chat/tools", headers=self.headers)
        self.assertEqual(tools.status_code, 200)
        self.assertIn("tools", tools.json())
        asset = self.client.get("/assets/chat.js")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("Command Chat", asset.text)

    def test_memory_remember_search_forget(self):
        w = self.client.post(
            "/chat/memory/remember",
            json={"kind": "preference", "content": "Always summarize metrics briefly"},
            headers=self.headers,
        )
        self.assertEqual(w.status_code, 200)
        mid = w.json()["memory_id"]
        s = self.client.get("/chat/memory/search?q=metrics", headers=self.headers)
        self.assertEqual(s.status_code, 200)
        self.assertTrue(any(x["id"] == mid for x in s.json()["results"]))
        f = self.client.post(f"/chat/memory/forget/{mid}", headers=self.headers)
        self.assertEqual(f.status_code, 200)

    def test_dashboard_still_serves(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("AI Command Chat", r.text)


if __name__ == "__main__":
    unittest.main()
