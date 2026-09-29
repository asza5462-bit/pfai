"""PFAI 8.6 — legendary memory + deep comprehension + elite replies."""
import hashlib
import os
import tempfile
import unittest

from pfai.deep_comprehension import comprehend, comprehension_block
from pfai.command_memory import CommandMemoryService
from pfai.memory import MemoryStore
from pfai.model_mock import MockCommandProvider


class TestDeepComprehension(unittest.TestCase):
    def test_elite_desire_intent(self):
        u = comprehend("اريده في الردود الشات يتفوق علي اقوا الذكاءات ويملك ذاكرة اسطورية وفهم عالي جدا")
        self.assertEqual(u["intent"], "memory_mind")
        self.assertIn("elite_quality_bar", u["goals"])
        self.assertTrue(u["latent_need"])
        block = comprehension_block(u, language="ar")
        self.assertIn("النية=", block)


class TestLegendaryMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        mem = MemoryStore(f"{self.tmp.name}/m.sqlite3")
        self.svc = CommandMemoryService(mem, chat_db_path=f"{self.tmp.name}/c.sqlite3")

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    def test_ingest_and_recall(self):
        cid = self.svc.create_conversation()
        out = self.svc.ingest_user_turn(
            "أريد رداً بفهم عالي جداً وذاكرة أسطورية",
            conversation_id=cid,
        )
        self.assertGreaterEqual(out["stored"], 1)
        ctx = self.svc.legendary_context("ذاكرة فهم", conversation_id=cid, limit=8)
        self.assertIn("Legendary Memory", ctx)
        self.assertNotEqual(ctx, "(no durable memory hits)")

    def test_facts_roundtrip(self):
        self.svc.remember_fact("user", "desires", "elite chat replies", confidence=0.9)
        facts = self.svc.recall_facts("elite chat")
        self.assertTrue(facts)
        self.assertEqual(facts[0]["predicate"], "desires")


class TestEliteCompose(unittest.TestCase):
    def test_reply_leads_with_understanding(self):
        m = MockCommandProvider()
        u = comprehend("أريد ذاكرة أسطورية وفهم عالي جدا في الشات")
        reply = m.compose_reply(
            "أريد ذاكرة أسطورية وفهم عالي جدا في الشات",
            [{"ok": True, "tool": "unified_brain_pulse", "result": {"ok": True, "snapshot": {"health": "ok"}, "elapsed_ms": 5}}],
            "## Legendary Memory\n- [user_desire|id=1] ذاكرة أسطورية",
            language="ar",
            understanding=u,
        )
        self.assertTrue(reply.strip())
        self.assertNotIn('"active_facts"', reply)
        self.assertNotIn("الفهم: النية=", reply)
        # Natural elite prose — memory desire still visible in lead or next move
        self.assertTrue(
            ("ذاكرة" in reply) or ("نبضة" in reply) or ("فهمت" in reply),
            reply,
        )


class TestLegendaryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_UNIFIED_BRAIN"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, CONTINUOUS
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)
        cls.CONTINUOUS = CONTINUOUS

    @classmethod
    def tearDownClass(cls):
        try:
            cls.CONTINUOUS.stop("test")
        except Exception:
            pass

    def test_chat_returns_understanding(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8."))
        r = self.client.post("/chat/message", json={
            "message": "اريده في الردود يتفوق ويملك ذاكرة اسطورية وفهم عالي جدا",
            "language": "ar",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "completed")
        self.assertIn("understanding", body)
        self.assertEqual((body.get("understanding") or {}).get("intent"), "memory_mind")
        reply = body.get("reply") or ""
        self.assertTrue(reply.strip())
        self.assertNotIn('"active_facts"', reply)
        self.assertNotIn("الفهم: النية=", reply)


if __name__ == "__main__":
    unittest.main()
