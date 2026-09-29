"""PFAI 8.12 — elite natural replies: no JSON fog, real memory answers."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from pfai.elite_reply import (
    compose_elite,
    empty_name_reply,
    is_name_question,
    memory_direct_reply,
    remember_confirm_reply,
)
from pfai.model_mock import MockCommandProvider
from pfai.command_memory import CommandMemoryService
from pfai.memory import MemoryStore


class TestEliteReplyUnit(unittest.TestCase):
    def test_no_json_dump_from_memory_tools(self):
        reply = compose_elite(
            "ما اسمي؟",
            [
                {
                    "ok": True,
                    "tool": "memory_audit",
                    "result": {
                        "ok": True,
                        "active_facts": 0,
                        "conflicts": [],
                        "secret_hits": [],
                    },
                },
                {
                    "ok": True,
                    "tool": "memory_status",
                    "result": {"ok": True, "active_facts": 0, "version": "8.12.0"},
                },
            ],
            "(no durable memory hits)",
            language="ar",
            understanding={"intent": "memory_mind", "latent_need": "recall"},
        )
        self.assertNotIn("active_facts", reply)
        self.assertNotIn("secret_hits", reply)
        self.assertNotIn("{", reply)
        self.assertIn("اسمك", reply)

    def test_direct_name_is_natural(self):
        reply = memory_direct_reply("ar", "اسمك الذي أتذكره هو: فهد.")
        self.assertIn("فهد", reply)
        self.assertNotIn("بدون تعارض", reply)
        self.assertNotIn("الحاجة الكامنة", reply)

    def test_remember_confirm_short(self):
        reply = remember_confirm_reply(
            language="ar",
            facts_stored=[{"predicate": "name_is", "object": "فهد"}],
            message="تذكر اسمي فهد",
        )
        self.assertIn("فهد", reply)
        self.assertNotIn("memory_status", reply)
        self.assertLess(len(reply), 220)

    def test_empty_name_honest(self):
        self.assertTrue(is_name_question("ما اسمي"))
        r = empty_name_reply("ar")
        self.assertIn("اسمك", r)

    def test_provider_brand(self):
        self.assertEqual(MockCommandProvider().name, "pfai-brain")

    def test_compose_skips_comprehension_block(self):
        m = MockCommandProvider()
        reply = m.compose_reply(
            "راجع حالة النظام",
            [{"ok": True, "tool": "system_status", "result": {"ok": True, "status": "healthy"}}],
            "",
            language="ar",
            understanding={"intent": "ops_status", "latent_need": "ops"},
        )
        self.assertNotIn("الفهم: النية=", reply)
        self.assertNotIn("أبقى دقيقاً", reply)
        self.assertNotIn("الخطوة التالية: قل الخطوة", reply)


class TestEliteChatFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._env_prev = {
            k: os.environ.get(k)
            for k in (
                "PFAI_OWNER_USERNAME",
                "PFAI_OWNER_PASSWORD_HASH",
                "PFAI_PUBLIC_ACCESS_MODE",
                "PFAI_OPEN_CHAT_TOOLS",
                "ANTHROPIC_API_KEY",
            )
        }
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, COMMAND_MEMORY
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)
        cls.agent = COMMAND_AGENT
        cls.mem = COMMAND_MEMORY

    @classmethod
    def tearDownClass(cls):
        for k, v in (cls._env_prev or {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_version_812(self):
        from pfai import __version__
        self.assertEqual(__version__, "8.12.0")
        self.assertEqual(self.client.get("/health").json().get("version"), "8.12.0")

    def test_provider_pfai_brain(self):
        self.assertEqual(self.agent.provider_name(), "pfai-brain")

    def test_remember_then_name_natural(self):
        cid = f"elite-{os.getpid()}"
        r1 = self.client.post("/chat/message", json={
            "message": "تذكر أن اسمي فهد",
            "conversation_id": cid,
            "language": "ar",
        })
        self.assertEqual(r1.status_code, 200)
        b1 = r1.json()
        self.assertEqual(b1.get("status"), "completed")
        self.assertIn("فهد", b1.get("reply") or "")
        self.assertNotIn("active_facts", b1.get("reply") or "")
        self.assertNotIn("memory_audit", b1.get("reply") or "")

        r2 = self.client.post("/chat/message", json={
            "message": "ما اسمي؟",
            "conversation_id": cid,
            "language": "ar",
        })
        self.assertEqual(r2.status_code, 200)
        b2 = r2.json()
        reply = b2.get("reply") or ""
        self.assertIn("فهد", reply)
        self.assertNotIn("active_facts", reply)
        self.assertNotIn("الفهم: النية=", reply)
        self.assertNotIn("{", reply)
        self.assertEqual(b2.get("provider"), "pfai-brain")

    def test_empty_name_no_json_isolated(self):
        """Isolated agent — shared prod memory may already hold a public name."""
        from pfai.command_agent import CommandAgent
        from pfai.command_audit import CommandAuditLog
        from pfai.tool_router import ToolRouter
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mem = CommandMemoryService(
            MemoryStore(f"{tmp.name}/m.sqlite3"),
            chat_db_path=f"{tmp.name}/c.sqlite3",
        )
        self.addCleanup(mem.close)
        agent = CommandAgent(ToolRouter({}), mem, CommandAuditLog(f"{tmp.name}/a.jsonl"))
        out = agent.handle("ما اسمي؟", conversation_id="iso-empty", owner="nobody", language="ar")
        reply = out.get("reply") or ""
        self.assertNotIn("active_facts", reply)
        self.assertNotIn("memory_status", reply)
        self.assertNotIn("{", reply)
        self.assertTrue("اسمك" in reply or "محفوظ" in reply)


class TestIngestNamePatterns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = CommandMemoryService(
            MemoryStore(f"{self.tmp.name}/m.sqlite3"),
            chat_db_path=f"{self.tmp.name}/c.sqlite3",
        )

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    def test_ismi_huwa(self):
        out = self.svc.ingest_user_turn("اسمي هو سارة", owner="o1")
        self.assertGreaterEqual(out["stored"], 1)
        ans = self.svc.direct_answer("ما اسمي؟", owner="o1", language="ar")
        self.assertIn("سارة", ans or "")


if __name__ == "__main__":
    unittest.main()
