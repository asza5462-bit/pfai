"""PFAI 8.3 — careful unlock: auto-learn accept + safe self-heal + chat autonomy tools."""
import hashlib
import os
import unittest

from pfai.open_execution import auto_accept_learning, auto_safe_heal, open_chat_tools, open_execution_status
from pfai.model_mock import MockCommandProvider
from pfai.self_check import SelfCheck, SelfHeal
from pfai.interfaces.self_check import SelfCheckReport
from pfai.autonomous_improve import AutonomousImproveOrchestrator


class TestOpenAutonomyFlags(unittest.TestCase):
    def test_open_mode_unlocks_learn_and_heal_not_promote(self):
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("PFAI_AUTO_ACCEPT_LEARNING", None)
        os.environ.pop("PFAI_AUTO_SAFE_HEAL", None)
        self.assertTrue(open_chat_tools())
        self.assertTrue(auto_accept_learning())
        self.assertTrue(auto_safe_heal())
        st = open_execution_status()
        self.assertIn("model_weight_promotion", st["still_gated"])
        self.assertIn("ssrf_and_arbitrary_network", st["still_gated"])

    def test_explicit_off_keeps_gates(self):
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "0"
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"
        os.environ["PFAI_AUTO_ACCEPT_LEARNING"] = "0"
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "0"
        os.environ["PFAI_ENV"] = "test"
        self.assertFalse(open_chat_tools())
        self.assertFalse(auto_accept_learning())
        self.assertFalse(auto_safe_heal())


class TestSafeHealAutoApply(unittest.TestCase):
    def test_auto_apply_registered_safe_step(self):
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        check = SelfCheck({"flaky": lambda: {"ok": False, "error": "transient"}})
        heal = SelfHeal(check)
        called = {"n": 0}

        def fix():
            called["n"] += 1
            check.checks["flaky"] = lambda: {"ok": True}
            return {"ok": True, "fixed": True}

        heal.register_safe_action("clear_transient_cache", fix)
        # Force failure then propose
        report = check.run_checks()
        self.assertFalse(report.ok)
        prop = heal.propose_fix(report)
        self.assertFalse(prop.requires_owner)
        applied = heal.apply_fix(prop.proposal_id, approved=False)
        self.assertTrue(applied.ok)
        self.assertGreaterEqual(called["n"], 1)


class TestAutonomyOrchestrator(unittest.TestCase):
    def test_healthy_cycle(self):
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "1"
        check = SelfCheck({"ok_check": lambda: {"ok": True}})
        heal = SelfHeal(check)
        ticks = {"n": 0}

        class Cont:
            def status(self):
                return {"service": {"status": "running"}, "worker_alive": True, "pending_examples": 0}

            def tick_once(self):
                ticks["n"] += 1
                return {"ok": True, "cycle": {"skipped": True}}

        orch = AutonomousImproveOrchestrator(self_check=check, self_heal=heal, continuous=Cont())
        out = orch.run_cycle()
        self.assertTrue(out["ok"])
        self.assertTrue(out["check_ok"])
        self.assertEqual(out["weight_promotion"], "never_auto")
        self.assertEqual(ticks["n"], 1)


class TestPlannerAutonomy(unittest.TestCase):
    def test_arabic_self_improve_intent(self):
        m = MockCommandProvider()
        allowed = ["autonomy_status", "self_improve_tick", "self_check_run", "system_status"]
        tools = {t["tool"] for t in m.plan_tools("أصلح نفسك وطور نفسك بدون قيود", allowed)}
        self.assertIn("self_improve_tick", tools)
        self.assertIn("autonomy_status", tools)


class TestAutonomyAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_AUTO_ACCEPT_LEARNING"] = "1"
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "1"
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

    def test_tools_and_version(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.3"))
        tools = self.client.get("/chat/tools").json()
        self.assertEqual(tools.get("locked_count"), 0)
        names = {t["name"] for t in tools["tools"]}
        for n in ("self_improve_tick", "self_heal_cycle", "self_check_run", "autonomy_status"):
            self.assertIn(n, names)

    def test_self_improve_tick_tool(self):
        r = self.client.post("/chat/message", json={
            "message": "أصلح نفسك وطور نفسك",
            "language": "ar",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tool_names = [t.get("tool") for t in (body.get("tools") or [])]
        self.assertTrue(any(n in tool_names for n in ("self_improve_tick", "autonomy_status", "self_check_run")))


if __name__ == "__main__":
    unittest.main()
