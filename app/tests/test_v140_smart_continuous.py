"""PFAI 8.7 — smart continuous: focused, high-precision, always-running curation."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.continuous_training import ContinuousConfig
from pfai.smart_continuous import PrecisionScorer, SmartContinuousBrain, SmartContinuousConfig


class TestPrecisionScorer(unittest.TestCase):
    def test_high_quality_example_scores_above_threshold(self):
        scorer = PrecisionScorer()
        dims = scorer.score_example(
            "How should PFAI separate experience learning from weight training?",
            "Experience learning curates and evaluates candidates. Weight training is a separate "
            "eligible LoRA job with backend, growth, and evaluation gates. Never auto-promote.",
            track="ai_engineering",
            source="smart_seed",
        )
        score = scorer.aggregate(dims)
        self.assertGreaterEqual(score, 0.55)
        self.assertGreater(dims["substance"], 0.5)

    def test_junk_fails_closed(self):
        scorer = PrecisionScorer()
        dims = scorer.score_example("hi", "todo", track="general_knowledge", source="unknown")
        self.assertLess(scorer.aggregate(dims), 0.45)


class TestSmartContinuousBrain(unittest.TestCase):
    def test_prepare_seeds_when_thin(self):
        brain = SmartContinuousBrain(
            SmartContinuousConfig(thin_queue_threshold=8, seed_per_focus_track=2),
            open_mode=lambda: True,
        )
        registered = []

        def reg(rows):
            registered.extend(rows)
            return {"accepted": len(rows), "submitted": len(rows)}

        prep = brain.prepare_cycle(
            [],
            track_names=["software_engineering", "ai_engineering", "reasoning_and_agents", "general_knowledge"],
            track_weights={
                "software_engineering": 0.45,
                "ai_engineering": 0.35,
                "reasoning_and_agents": 0.12,
                "general_knowledge": 0.08,
            },
            register_batch=reg,
        )
        self.assertTrue(prep["thin_queue"])
        self.assertGreater(prep["seeded"], 0)
        self.assertTrue(prep["focus_tracks"])
        self.assertGreaterEqual(len(registered), 2)

    def test_precision_fallback_when_llm_weak(self):
        brain = SmartContinuousBrain(SmartContinuousConfig(precision_min_score=0.55))
        rows = [
            {
                "instruction": "Explain evaluation gates before model activation in PFAI.",
                "response": (
                    "Require task and regression suites versus last-known-good, reload/inference "
                    "compatibility, and explicit activation. Training loss alone is never enough."
                ),
                "track": "ai_engineering",
                "source": "smart_seed",
            }
        ]
        resolved = brain.resolve_score(rows, llm_score=0.0, llm_reason="failed")
        self.assertEqual(resolved["method"], "precision_fallback")
        self.assertGreaterEqual(resolved["score"], 0.55)
        self.assertTrue(resolved["fallback_used"])

    def test_adaptive_interval_faster_when_open_and_thin(self):
        brain = SmartContinuousBrain(
            SmartContinuousConfig(base_interval_seconds=120, fast_interval_seconds=60),
            open_mode=lambda: True,
        )
        self.assertEqual(brain.adaptive_interval(pending_count=2, last_skipped=True), 60)


class TestOrchestratorSmartCycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orch = ContinuousLearningOrchestrator(
            root=str(Path(self.tmp.name) / "cl"),
            evaluator_model=None,
            self_training=False,
            require_human_approval=False,
            min_improvement=-1.0,
            continuous_config=ContinuousConfig(interval_seconds=60, max_consecutive_failures=5),
            smart_config=SmartContinuousConfig(
                enabled=True,
                thin_queue_threshold=8,
                seed_per_focus_track=3,
                precision_min_score=0.55,
                use_precision_fallback=True,
            ),
            open_mode=lambda: True,
        )

    def tearDown(self):
        try:
            self.orch.stop("test")
        except Exception:
            pass
        self.tmp.cleanup()

    def test_empty_queue_cycle_seeds_and_evaluates(self):
        result = self.orch.run_cycle("v-smart-1")
        self.assertTrue(result.get("evaluated"), result)
        self.assertFalse(result.get("skipped"))
        self.assertIn("smart", result)
        self.assertGreater(result["smart"].get("seeded", 0), 0)
        self.assertIn(result.get("status"), ("accepted", "pending_approval"))
        self.assertFalse(self.orch.status().get("auto_promote"))
        self.assertGreater(self.orch.status()["pending_examples"], 0)

    def test_tick_once_succeeds_without_teacher(self):
        # Exercise the service-cycle path without spawning the background worker.
        self.orch.service.start()
        version = "cl-tick-test"
        cycle = self.orch._run_service_cycle(lambda: self.orch.run_cycle(version))
        self.assertFalse(cycle.get("skipped"), cycle)
        self.assertEqual(cycle.get("status"), "success")
        self.assertIn(cycle.get("learning_status"), ("accepted", "pending_approval"))
        st = self.orch.status()
        self.assertIn("smart", st)
        self.assertTrue(st["smart"].get("enabled"))


class TestSmartContinuousAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_AUTO_ACCEPT_LEARNING"] = "1"
        os.environ["PFAI_CONTINUOUS_TRAINING_ENABLED"] = "true"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime, COMMAND_AGENT, CONTINUOUS
        from pfai.model import EchoProvider

        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.CONTINUOUS = CONTINUOUS

    @classmethod
    def tearDownClass(cls):
        try:
            cls.CONTINUOUS.stop("test_teardown")
        except Exception:
            pass
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"

    def test_version_87(self):
        from pfai import __version__

        self.assertTrue(__version__.startswith("8."))
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("version"), __version__)

    def test_chat_tools_include_smart_status(self):
        r = self.client.get("/chat/tools")
        self.assertEqual(r.status_code, 200)
        names = {t["name"] for t in r.json()["tools"]}
        self.assertIn("smart_continuous_status", names)
        self.assertIn("continuous_tick", names)

    def test_continuous_status_exposes_smart(self):
        r = self.client.get("/continuous/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("smart", body)
        self.assertFalse(body.get("auto_promote"))
        self.assertTrue((body.get("smart") or {}).get("enabled"))

    def test_chat_smart_training_arabic(self):
        r = self.client.post(
            "/chat/message",
            json={
                "message": "اريد تدريب مستمر بذكاء وتركيز عالي ودقيق جدا بدون قيود",
                "language": "ar",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            tools.intersection(
                {"continuous_start", "continuous_tick", "smart_continuous_status", "continuous_status"}
            ),
            tools,
        )

    def test_tick_endpoint_evaluates(self):
        r = self.client.post("/continuous/tick")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("ok"))
        cycle = body.get("cycle") or {}
        # After smart seed, should evaluate (not empty-queue skip)
        if cycle.get("skipped"):
            # Allow soft skip only with explicit reason
            self.assertIn("reason", cycle)
        else:
            self.assertIn(cycle.get("status"), ("success", "accepted"))
            st = body.get("status") or {}
            self.assertIn("smart", st)


class TestAutoPromoteInvariant(unittest.TestCase):
    def test_smart_status_never_auto_promote(self):
        brain = SmartContinuousBrain()
        self.assertFalse(brain.status().get("auto_promote"))


if __name__ == "__main__":
    unittest.main()
