"""PFAI 8.11 — legendary memory: conflicts, leaks, identity, heal."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from pfai import memory_guardian as guardian
from pfai.command_memory import CommandMemoryService
from pfai.memory import MemoryStore
from pfai.model_mock import MockCommandProvider


class TestGuardianExtract(unittest.TestCase):
    def test_name_ar(self):
        facts = guardian.extract_identity_and_prefs("تذكر أن اسمي أحمد وأنني أفضل الردود بالعربية المختصرة")
        preds = {f["predicate"] for f in facts}
        self.assertIn("name_is", preds)
        self.assertTrue(any(f["object"] == "أحمد" for f in facts if f["predicate"] == "name_is"))
        self.assertIn("prefers_language", preds)

    def test_secret_redaction(self):
        cleaned, hit = guardian.redact_secrets("my api_key=sk-abcdefghijklmnop password=hunter2")
        self.assertTrue(hit)
        self.assertIn("[REDACTED]", cleaned)
        self.assertNotIn("hunter2", cleaned)


class TestConflictSupersede(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        mem = MemoryStore(f"{self.tmp.name}/m.sqlite3")
        self.svc = CommandMemoryService(mem, chat_db_path=f"{self.tmp.name}/c.sqlite3")

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    def test_name_conflict_keeps_latest(self):
        self.svc.remember_fact("user", "name_is", "سارة", owner="u1", confidence=0.9)
        self.svc.remember_fact("user", "name_is", "خالد", owner="u1", confidence=0.95)
        facts = self.svc.recall_facts("ما اسمي", owner="u1")
        names = [f for f in facts if f["predicate"] == "name_is"]
        self.assertEqual(len(names), 1)
        self.assertEqual(names[0]["object"], "خالد")
        ans = self.svc.direct_answer("ما اسمي؟", owner="u1", language="ar")
        self.assertIsNotNone(ans)
        self.assertIn("خالد", ans)

    def test_owner_isolation(self):
        self.svc.remember_fact("user", "name_is", "أحمد", owner="alice", confidence=0.9)
        self.svc.remember_fact("user", "name_is", "سارة", owner="bob", confidence=0.9)
        a = self.svc.recall_facts("اسمي", owner="alice")
        b = self.svc.recall_facts("اسمي", owner="bob")
        self.assertEqual([f["object"] for f in a if f["predicate"] == "name_is"], ["أحمد"])
        self.assertEqual([f["object"] for f in b if f["predicate"] == "name_is"], ["سارة"])

    def test_ingest_stores_identity(self):
        cid = self.svc.create_conversation(owner="u1")
        out = self.svc.ingest_user_turn(
            "تذكر أن اسمي ليلى وأفضل العربية المختصرة",
            conversation_id=cid,
            owner="u1",
        )
        self.assertGreaterEqual(out["stored"], 1)
        ans = self.svc.direct_answer("ما اسمي؟", owner="u1", language="ar")
        self.assertIn("ليلى", ans or "")

    def test_digest_strips_template(self):
        cid = self.svc.create_conversation()
        self.svc.add_message(cid, "user", "اسمي نورة")
        self.svc.add_message(
            cid, "assistant",
            "فهمتك.\nما تريده في العمق: xyz\nالفهم: النية=memory_mind\nأبقى دقيقاً: لا اختراع",
        )
        d = self.svc.update_digest(cid, self.svc.recent_dialog(cid, limit=10))
        self.assertNotIn("أبقى دقيقاً", d)
        self.assertIn("اسمي نورة", d)

    def test_heal_and_audit(self):
        # Force conflict by inserting without going through remember_fact supersede path
        self.svc.remember_fact("user", "prefers", "long answers", owner="u1")
        self.svc.remember_fact("user", "prefers", "short answers", owner="u1")
        audit = self.svc.audit(owner="u1")
        self.assertTrue(audit.get("ok") or audit.get("conflicts") == [])
        healed = self.svc.heal_conflicts(owner="u1")
        self.assertTrue(healed["ok"])
        facts = self.svc.recall_facts("prefer", owner="u1")
        prefs = [f for f in facts if f["predicate"] == "prefers"]
        self.assertEqual(len(prefs), 1)

    def test_coding_bleed_filtered(self):
        self.svc.memory.add("coding_weakness", "user fails loops", "academy", 0.5)
        self.svc.remember("preference", "likes concise Arabic", "chat", 0.9)
        hits = self.svc.relevant("ما تفضيلاتي", limit=10)
        kinds = {h.get("kind") for h in hits}
        self.assertNotIn("coding_weakness", kinds)

    def test_secret_not_stored_raw(self):
        out = self.svc.ingest_user_turn("تذكر api_key=sk-abcdefghijklmnop", owner="u1")
        self.assertTrue(out.get("redacted"))
        docs = self.svc.memory.all_documents()
        blob = " ".join(d.get("content") or "" for d in docs)
        self.assertNotIn("sk-abcdefghijklmnop", blob)


class TestComposeMemoryFirst(unittest.TestCase):
    def test_direct_answer_in_compose(self):
        m = MockCommandProvider()
        reply = m.compose_reply(
            "ما اسمي؟",
            [],
            "## Legendary Memory\nFacts:\n- (user) name_is → خالد\nDirectAnswer: اسمك الذي أتذكره هو: خالد.",
            language="ar",
            understanding={"intent": "memory_mind", "latent_need": "recall"},
        )
        self.assertIn("خالد", reply)
        self.assertNotIn("memory_audit", reply)
        self.assertNotIn('"active_facts"', reply)


class TestMemoryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        cls.mem = COMMAND_MEMORY

    def test_version_81x(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.1"))
        self.assertEqual(self.client.get("/health").json().get("version"), __version__)

    def test_chat_tools_include_memory_guardian(self):
        r = self.client.get("/chat/tools")
        names = {t["name"] for t in r.json()["tools"]}
        for n in ("memory_status", "memory_audit", "memory_heal", "memory_search"):
            self.assertIn(n, names)

    def test_chat_name_conflict_resolved(self):
        r1 = self.client.post("/chat/message", json={
            "message": "تذكر أن اسمي سارة", "language": "ar",
        })
        self.assertEqual(r1.status_code, 200)
        cid = r1.json()["conversation_id"]
        r2 = self.client.post("/chat/message", json={
            "message": "تذكر أن اسمي خالد", "language": "ar", "conversation_id": cid,
        })
        self.assertEqual(r2.status_code, 200)
        r3 = self.client.post("/chat/message", json={
            "message": "ما اسمي؟", "language": "ar", "conversation_id": cid,
        })
        self.assertEqual(r3.status_code, 200)
        reply = r3.json().get("reply") or ""
        self.assertIn("خالد", reply)
        self.assertNotIn("سارة", reply)

    def test_memory_heal_tool(self):
        from pfai.api import _tool_memory_heal, _tool_memory_audit
        a = _tool_memory_audit()
        self.assertIn("conflicts", a)
        h = _tool_memory_heal()
        self.assertTrue(h.get("ok"))


if __name__ == "__main__":
    unittest.main()
