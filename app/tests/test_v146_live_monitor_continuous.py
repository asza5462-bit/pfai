"""PFAI 8.13 — 24/7 live monitor + continuous learn/train chat routing."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from pfai.deep_comprehension import comprehend
from pfai.elite_reply import compose_elite, humanize_tool
from pfai.live_monitor import LiveSystemMonitor
from pfai.model_mock import MockCommandProvider


class TestLiveMonitorUnit(unittest.TestCase):
    def test_pulse_ensures_and_ticks(self):
        calls = {"ensure": 0, "tick": 0, "train": 0}

        def ensure():
            calls["ensure"] += 1
            return {"ok": True, "worker_alive": True}

        def tick():
            calls["tick"] += 1
            return {"ok": True, "cycle": {"ok": True}}

        def elig():
            return {"eligible": True, "ok": True}

        def train():
            calls["train"] += 1
            return {"ok": True, "async_accepted": True, "status": "RUNNING", "actual_training_executed": False}

        mon = LiveSystemMonitor(
            continuous_ensure_fn=ensure,
            continuous_tick_fn=tick,
            continuous_status_fn=lambda: {"worker_alive": True, "pending_examples": 2, "service": {"status": "running"}},
            evolution_ensure_fn=lambda: {"ok": True, "alive": True},
            evolution_status_fn=lambda: {"alive": True, "minute_ticks": 3},
            training_eligibility_fn=elig,
            training_start_fn=train,
            training_status_fn=lambda: {"status": "IDLE"},
            interval_seconds=30,
        )
        out = mon.pulse(deep=False, train_if_eligible=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["continuous_alive"])
        self.assertEqual(calls["ensure"], 1)
        self.assertEqual(calls["tick"], 1)
        self.assertEqual(calls["train"], 1)
        self.assertTrue(out["training"]["triggered"])
        self.assertEqual(out["weight_promotion"], "never_auto")
        # Cooldown blocks immediate second train
        out2 = mon.pulse(deep=False, train_if_eligible=True)
        self.assertEqual(calls["train"], 1)
        self.assertEqual(out2["training"]["reason"], "train_cooldown")
        ar = mon.answer_status(language="ar")
        self.assertIn("المراقب الحي", ar)
        self.assertNotIn("{", ar)


class TestContinuousRouting(unittest.TestCase):
    def test_arabic_continuous_question_plans_monitor(self):
        m = MockCommandProvider()
        planned = m.plan_tools(
            "هل التدريب المستمر يعمل",
            [
                "live_monitor_pulse", "live_monitor_status", "continuous_start",
                "continuous_status", "continuous_tick", "smart_training_status",
                "unified_brain_pulse", "unified_train_learn_cycle", "unified_train_learn_status",
            ],
        )
        tools = {t["tool"] for t in planned}
        # Status ask → unified status/cycle (learn-only) + monitor status — no LoRA stampede
        self.assertIn("unified_train_learn_status", tools)
        self.assertTrue(tools & {"live_monitor_status", "live_monitor_pulse", "continuous_status"})
        cycle = next((t for t in planned if t["tool"] == "unified_train_learn_cycle"), None)
        if cycle:
            self.assertFalse(cycle["args"].get("train_if_eligible"))

    def test_continue_inherits_train_intent(self):
        u = comprehend(
            "اكمل",
            dialog=[
                {"role": "user", "content": "هل التدريب المستمر يعمل"},
                {"role": "assistant", "content": "المراقب يعمل"},
            ],
            language="ar",
        )
        self.assertEqual(u["intent"], "train_learn")
        self.assertNotIn("continue prior", u["latent_need"])

    def test_compose_no_english_latent_leak(self):
        reply = compose_elite(
            "اكمل",
            [
                {"ok": True, "tool": "live_monitor_pulse", "result": {
                    "ok": True, "continuous_alive": True, "evolution_alive": True,
                    "training": {"triggered": False, "reason": "train_cooldown"},
                }},
                {"ok": True, "tool": "continuous_status", "result": {
                    "worker_alive": True, "pending_examples": 1, "service": {"status": "running"},
                }},
            ],
            "",
            language="ar",
            understanding={"intent": "train_learn", "latent_need": "تعلّم وتدريب مستمران 24/7 بمراقب حي — عمل حقيقي بلا وهم"},
        )
        self.assertNotIn("continue prior desire", reply)
        self.assertNotIn("active_facts", reply)
        self.assertTrue("مستمر" in reply or "مراقب" in reply or "24/7" in reply)

    def test_humanize_continuous(self):
        line = humanize_tool(
            "continuous_status",
            {"worker_alive": True, "pending_examples": 4, "service": {"status": "running"}},
            en=False,
        )
        self.assertIn("24/7", line or "")


class TestLiveMonitorAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, LIVE_MONITOR, CONTINUOUS
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)
        cls.monitor = LIVE_MONITOR
        cls.continuous = CONTINUOUS

    def test_version_81x(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.1"))
        self.assertEqual(self.client.get("/health").json().get("version"), __version__)

    def test_tools_include_live_monitor(self):
        r = self.client.get("/chat/tools")
        names = {t["name"] for t in r.json()["tools"]}
        self.assertIn("live_monitor_status", names)
        self.assertIn("live_monitor_pulse", names)

    def test_chat_continuous_question_natural(self):
        r = self.client.post("/chat/message", json={
            "message": "هل التدريب المستمر يعمل",
            "language": "ar",
            "conversation_id": f"cont-{os.getpid()}",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        reply = body.get("reply") or ""
        self.assertEqual(body.get("status"), "completed")
        self.assertNotIn("continue prior desire", reply)
        self.assertNotIn('"active_facts"', reply)
        # Should mention continuous/monitor reality
        self.assertTrue(
            any(x in reply for x in ("مستمر", "مراقب", "LoRA", "تعلّم", "تعلم", "24/7")),
            reply,
        )
        tool_names = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            tool_names & {"live_monitor_pulse", "continuous_start", "continuous_status", "continuous_tick", "live_monitor_status"},
            tool_names,
        )

    def test_continue_does_real_work(self):
        cid = f"cont-follow-{os.getpid()}"
        self.client.post("/chat/message", json={
            "message": "هل التعليم المستمر يعمل", "language": "ar", "conversation_id": cid,
        })
        r = self.client.post("/chat/message", json={
            "message": "اكمل", "language": "ar", "conversation_id": cid,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        reply = body.get("reply") or ""
        self.assertNotIn("continue prior desire with higher precision", reply)
        self.assertNotIn("نكمل: continue prior", reply)


if __name__ == "__main__":
    unittest.main()
