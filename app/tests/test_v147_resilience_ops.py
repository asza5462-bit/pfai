"""PFAI 8.14 — cold-start resilience + Claude-grade ops status."""
from __future__ import annotations

import hashlib
import os
import unittest

from pfai.ops_pulse import is_ops_status_question, ops_status_reply


class TestOpsPulse(unittest.TestCase):
    def test_detect_ar(self):
        self.assertTrue(is_ops_status_question("كيف حالة النظام الان"))
        self.assertTrue(is_ops_status_question("حالة النظام"))
        self.assertTrue(is_ops_status_question("system status now"))

    def test_natural_reply(self):
        r = ops_status_reply(
            language="ar",
            health={"status": "ok", "version": "8.14.0"},
            continuous={"worker_alive": True, "pending_examples": 2},
            monitor={"alive": True, "pulses": 5},
            evolution={"alive": True, "minute_ticks": 3},
            version="8.14.0",
        )
        self.assertIn("PFAI 8.14.0", r)
        self.assertIn("24/7", r)
        self.assertIn("المراقب الحي", r)
        self.assertNotIn("{", r)
        self.assertNotIn("active_facts", r)


class TestOpsChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for k in ("PFAI_PUBLIC_ACCESS_MODE", "PFAI_OPEN_CHAT_TOOLS"):
            os.environ.pop(k, None)

    def test_version_81x(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.1"))
        self.assertEqual(self.client.get("/health").json().get("version"), __version__)

    def test_system_status_natural(self):
        r = self.client.post("/chat/message", json={
            "message": "كيف حالة النظام الان",
            "language": "ar",
            "conversation_id": f"ops-{os.getpid()}",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        reply = body.get("reply") or ""
        self.assertEqual(body.get("status"), "completed")
        self.assertNotIn("تعذر الاتصال", reply)
        self.assertNotIn("active_facts", reply)
        self.assertNotIn("continue prior", reply)
        self.assertTrue(
            any(x in reply for x in ("النظام", "PFAI", "مستمر", "مراقب")),
            reply,
        )

    def test_assets_have_wake_retry(self):
        html = self.client.get("/").text
        self.assertIn("wakeBackend", html)
        self.assertRegex(html, r"8\.1\d\.0")
        js = self.client.get("/assets/chat.js").text
        self.assertIn("PFAI Brain", js)


if __name__ == "__main__":
    unittest.main()
