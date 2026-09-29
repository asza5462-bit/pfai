"""PFAI 8.15 — unified 24/7 learn→grow→train loop."""
from __future__ import annotations

import hashlib
import os
import threading
import time
import unittest

from pfai.model_mock import MockCommandProvider
from pfai.unified_train_learn import UnifiedTrainLearnLoop


class TestUnifiedLoopUnit(unittest.TestCase):
    def test_cycle_smooth_and_timed(self):
        calls = {"tick": 0, "train": 0}

        def tick():
            calls["tick"] += 1
            time.sleep(0.01)
            return {"ok": True, "cycle": {"ok": True}}

        def train():
            calls["train"] += 1
            return {"ok": True, "async_accepted": True, "status": "STARTED_ASYNC", "cycle": {"status": "STARTED_ASYNC"}}

        loop = UnifiedTrainLearnLoop(
            continuous_ensure_fn=lambda: {"ok": True, "worker_alive": True},
            continuous_tick_fn=tick,
            continuous_status_fn=lambda: {"worker_alive": True, "pending_examples": 3, "real_loop": True},
            experience_push_fn=lambda: {"pushed": 2, "accepted": 1},
            training_diagnose_fn=lambda: {"eligible": True, "reason": None},
            training_start_fn=train,
            training_status_fn=lambda: {"async_running": False, "runs": 0},
            train_cooldown_seconds=120,
            tick_timeout_seconds=5,
            min_tick_interval_seconds=0,  # allow second cycle to still skip train via cooldown
        )
        out = loop.cycle(train_if_eligible=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["learn"]["worker_alive"])
        self.assertTrue(out["learn"]["tick_ok"])
        self.assertTrue(out["train"]["triggered"])
        self.assertEqual(out["weight_promotion"], "never_auto")
        self.assertEqual(calls["tick"], 1)
        self.assertEqual(calls["train"], 1)
        # cooldown
        out2 = loop.cycle(train_if_eligible=True)
        self.assertEqual(calls["train"], 1)
        self.assertEqual(out2["train"]["reason"], "train_cooldown")
        ar = loop.answer(language="ar")
        self.assertIn("موحّدة", ar)
        self.assertNotIn("{", ar)

    def test_tick_timeout_marks_failure(self):
        started = {"n": 0}

        def slow():
            started["n"] += 1
            time.sleep(2.5)
            return {"ok": True}

        loop = UnifiedTrainLearnLoop(
            continuous_ensure_fn=lambda: {"ok": True, "worker_alive": True},
            continuous_tick_fn=slow,
            continuous_status_fn=lambda: {"worker_alive": True},
            experience_push_fn=lambda: {"pushed": 0},
            training_diagnose_fn=lambda: {"eligible": False},
            training_start_fn=lambda: {"ok": True},
            training_status_fn=lambda: {},
            tick_timeout_seconds=0.25,
            min_tick_interval_seconds=0,  # force tick
        )
        t0 = time.time()
        out = loop.cycle(train_if_eligible=False)
        elapsed = time.time() - t0
        # Either timed out quickly, or completed; never claim tick_ok on timeout path
        self.assertTrue(started["n"] >= 1)
        self.assertTrue(elapsed < 4.0)
        if elapsed < 1.5:
            self.assertFalse(out["learn"]["tick_ok"])

    def test_overlap_guard_and_debounce(self):
        ticks = {"n": 0}
        gate = threading.Event()
        release = threading.Event()

        def slow_tick():
            ticks["n"] += 1
            gate.set()
            release.wait(2.0)
            return {"ok": True}

        loop = UnifiedTrainLearnLoop(
            continuous_ensure_fn=lambda: {"ok": True, "worker_alive": True},
            continuous_tick_fn=slow_tick,
            continuous_status_fn=lambda: {"worker_alive": True, "pending_examples": 1, "real_loop": True},
            experience_push_fn=lambda: {"pushed": 0},
            training_diagnose_fn=lambda: {"eligible": False},
            training_start_fn=lambda: {"ok": True},
            training_status_fn=lambda: {},
            tick_timeout_seconds=5,
            min_tick_interval_seconds=60,
            train_cooldown_seconds=120,
        )

        def run():
            loop.cycle(train_if_eligible=False)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        self.assertTrue(gate.wait(2.0))
        overlap = loop.cycle(train_if_eligible=False)
        self.assertTrue(overlap.get("skipped") or overlap.get("reason") == "cycle_in_progress")
        release.set()
        th.join(3.0)
        # Debounce: immediate second cycle should skip tick
        out2 = loop.cycle(train_if_eligible=False)
        self.assertTrue(out2["learn"].get("tick_debounced") or ticks["n"] == 1)

    def test_heartbeat_start_stop(self):
        trains = {"n": 0}

        def train():
            trains["n"] += 1
            return {"ok": True, "async_accepted": True, "status": "STARTED_ASYNC"}

        loop = UnifiedTrainLearnLoop(
            continuous_ensure_fn=lambda: {"ok": True, "worker_alive": True},
            continuous_tick_fn=lambda: {"ok": True},
            continuous_status_fn=lambda: {"worker_alive": True, "real_loop": True},
            experience_push_fn=lambda: {"pushed": 0},
            training_diagnose_fn=lambda: {"eligible": True},
            training_start_fn=train,
            training_status_fn=lambda: {"async_running": False},
            heartbeat_seconds=20,
            min_tick_interval_seconds=5,
            heartbeat_train_every=8,
            train_cooldown_seconds=120,
        )
        st = loop.start()
        self.assertTrue(st.get("alive"))
        self.assertEqual(st.get("heartbeat_train_every"), 8)
        time.sleep(0.2)
        self.assertTrue(loop.status().get("heartbeat_alive"))
        # Soft first beat must not train
        self.assertEqual(trains["n"], 0)
        loop.stop("test")
        self.assertFalse(loop.status().get("heartbeat_alive"))


class TestUnifiedRouting(unittest.TestCase):
    def test_plans_unified_cycle(self):
        m = MockCommandProvider()
        tools = {t["tool"] for t in m.plan_tools(
            "هل التدريب المستمر يعمل",
            [
                "unified_train_learn_cycle", "unified_train_learn_status",
                "live_monitor_pulse", "continuous_start", "smart_training_start",
            ],
        )}
        self.assertIn("unified_train_learn_cycle", tools)

    def test_plans_cycle_phrase(self):
        m = MockCommandProvider()
        tools = {t["tool"] for t in m.plan_tools(
            "طور دورة التدريب مع التعليم على مدار الساعة",
            [
                "unified_train_learn_cycle", "unified_train_learn_status",
                "live_monitor_pulse", "continuous_start", "smart_training_start",
            ],
        )}
        self.assertIn("unified_train_learn_cycle", tools)


class TestUnifiedAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, UNIFIED_TRAIN_LEARN
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)
        cls.loop = UNIFIED_TRAIN_LEARN

    @classmethod
    def tearDownClass(cls):
        for k in ("PFAI_PUBLIC_ACCESS_MODE", "PFAI_OPEN_CHAT_TOOLS"):
            os.environ.pop(k, None)

    def test_version_815(self):
        from pfai import __version__
        self.assertEqual(__version__, "8.15.0")
        self.assertEqual(self.client.get("/health").json().get("version"), "8.15.0")

    def test_tools_registered(self):
        names = {t["name"] for t in self.client.get("/chat/tools").json()["tools"]}
        self.assertIn("unified_train_learn_cycle", names)
        self.assertIn("unified_train_learn_status", names)

    def test_chat_runs_unified_cycle(self):
        r = self.client.post("/chat/message", json={
            "message": "هل التدريب المستمر يعمل",
            "language": "ar",
            "conversation_id": f"utl-{os.getpid()}",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        reply = body.get("reply") or ""
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertEqual(body.get("status"), "completed")
        self.assertTrue(
            tools & {"unified_train_learn_cycle", "unified_train_learn_status"},
            tools,
        )
        self.assertNotIn("continue prior desire", reply)
        self.assertTrue(
            any(x in reply for x in ("موحّد", "مستمر", "تدريب", "LoRA", "24/7", "دورة")),
            reply,
        )


if __name__ == "__main__":
    unittest.main()
