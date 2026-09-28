"""System integrity: cohesive plane, no stacked web stalls, core paths green."""
import os
import unittest
from unittest import mock

from pfai.model_mock import MockCommandProvider


class TestWebPlannerLatencyGuard(unittest.TestCase):
    def test_web_query_is_single_path(self):
        m = MockCommandProvider()
        allowed = [
            "web_status", "web_research", "web_search", "web_fetch",
            "coding_teach", "coding_tracks", "system_status", "app_control_status",
        ]
        tools = [t["tool"] for t in m.plan_tools("ابحث في الويب عن FastAPI best practices", allowed)]
        self.assertEqual(tools.count("web_search"), 1)
        self.assertNotIn("web_research", tools)
        self.assertTrue(set(tools).issubset({"web_status", "web_search"}))
        deep = [t["tool"] for t in m.plan_tools("deep research Python typing on the web", allowed)]
        self.assertIn("web_research", deep)
        self.assertNotIn("web_search", deep)


class TestWebTimeoutHelper(unittest.TestCase):
    def test_timeout_returns_honest_failure_without_hang(self):
        os.environ.setdefault("PFAI_PUBLIC_ACCESS_MODE", "0")
        from pfai.api import _run_with_timeout
        import time

        def slow():
            time.sleep(3)
            return {"ok": True}

        t0 = time.time()
        out = _run_with_timeout(slow, timeout_s=0.25, label="unit")
        elapsed = time.time() - t0
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "unit_timeout")
        self.assertFalse(out.get("fabricated_results"))
        # Must not wait for the orphaned worker (was ~timeout+sleep before)
        self.assertLess(elapsed, 1.5)


class TestIntegrityAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import hashlib
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_CONTINUOUS_TRAINING_ENABLED"] = "true"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, CONTINUOUS
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.CONTINUOUS = CONTINUOUS

    @classmethod
    def tearDownClass(cls):
        try:
            cls.CONTINUOUS.stop("test")
        except Exception:
            pass
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"

    def test_cohesive_core(self):
        h = self.client.get("/health").json()
        self.assertEqual(h.get("status"), "ok")
        self.assertTrue(str(h.get("version")).startswith("8."))
        tools = self.client.get("/chat/tools").json()
        self.assertTrue(tools.get("open_chat_tools"))
        self.assertEqual(tools.get("locked_count"), 0)
        names = {t["name"] for t in tools["tools"]}
        for n in ("app_control_status", "web_research", "coding_exercise_submit", "continuous_tick", "training_cycle_start"):
            self.assertIn(n, names)
        cont = self.client.get("/continuous/status").json()
        self.assertIn("worker_alive", cont)
        web = self.client.get("/platform/web/status").json()
        self.assertIn(web.get("WEB_FABRIC_STATUS"), {"READY", "CONFIGURED", "NOT_CONFIGURED", "TEST_ONLY"})


if __name__ == "__main__":
    unittest.main()
