"""PFAI 8.6 — unified super brain: one mind, parallel lanes, low lag."""
import hashlib
import os
import unittest

from pfai.model_mock import MockCommandProvider
from pfai.unified_brain import UnifiedBrain, unified_brain_enabled
from pfai.command_agent import _budget_plan


class TestUnifiedUnit(unittest.TestCase):
    def test_pulse_parallel_and_soft(self):
        brain = UnifiedBrain(
            health_fn=lambda: {"ok": True, "status": "ok"},
            continuous_fn=lambda: {"ok": True, "worker_alive": True},
            advanced_fn=lambda: {"ok": True, "maturity": {"stage": "advanced"}},
            autonomy_fn=lambda: {"ok": True},
            web_fn=lambda: {"ok": True, "WEB_FABRIC_STATUS": "READY"},
            academy_fn=lambda: {"ok": True, "tracks": 8},
            improve_fn=lambda: {"ok": True, "check_ok": True},
            develop_fn=lambda: {"ok": True, "ran": True, "solved": True},
        )
        out = brain.pulse(action="status", include_action=False)
        self.assertTrue(out["unified"])
        self.assertEqual(out["mind"], "one_brain")
        self.assertLess(out["elapsed_ms"], 2000)
        self.assertEqual(out["weight_promotion"], "never_auto")

    def test_budget_prefers_pulse(self):
        planned = [
            {"tool": "unified_brain_pulse", "args": {}},
            {"tool": "system_status", "args": {}},
            {"tool": "health_check", "args": {}},
            {"tool": "advanced_self_develop", "args": {}},
        ]
        out = _budget_plan(planned)
        self.assertEqual(out[0]["tool"], "unified_brain_pulse")
        self.assertLessEqual(len(out), 2)

    def test_planner_one_mind(self):
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        m = MockCommandProvider()
        tools = [t["tool"] for t in m.plan_tools(
            "طوره واجعل كل شيء يعمل كعقل واحد بسلاسة وسرعة بدون اخطاء",
            ["unified_brain_pulse", "app_control_status", "system_status", "advanced_self_develop"],
        )]
        self.assertEqual(tools, ["unified_brain_pulse"])


class TestUnifiedAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_UNIFIED_BRAIN"] = "1"
        os.environ["PFAI_CONTINUOUS_TRAINING_ENABLED"] = "true"
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

    def test_tools_and_version(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.6"))
        self.assertTrue(unified_brain_enabled())
        names = {t["name"] for t in self.client.get("/chat/tools").json()["tools"]}
        self.assertIn("unified_brain_pulse", names)
        self.assertIn("unified_brain_status", names)

    def test_chat_one_mind_fast(self):
        import time
        t0 = time.time()
        r = self.client.post("/chat/message", json={
            "message": "اجعل كل شيء يعمل كعقل واحد بسلاسة وسرعة بدون اخطاء",
            "language": "ar",
        })
        ms = int((time.time() - t0) * 1000)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "completed")
        tools = [t.get("tool") for t in (body.get("tools") or [])]
        self.assertIn("unified_brain_pulse", tools)
        # Local pulse should stay snappy in tests
        self.assertLess(ms, 15000)


if __name__ == "__main__":
    unittest.main()
