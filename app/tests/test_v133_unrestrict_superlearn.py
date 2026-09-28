"""PFAI 8.1 — real continuous worker, open corrections, training_cycle_start from chat."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.continuous_training import ContinuousConfig
from pfai.open_execution import open_chat_tools


class TestContinuousRealLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orch = ContinuousLearningOrchestrator(
            root=str(Path(self.tmp.name) / "cl"),
            evaluator_model=None,
            self_training=False,
            continuous_config=ContinuousConfig(interval_seconds=60, max_consecutive_failures=5),
        )

    def tearDown(self):
        try:
            self.orch.stop("test")
        except Exception:
            pass
        self.tmp.cleanup()

    def test_start_spawns_worker_and_tick(self):
        st = self.orch.start()
        self.assertTrue(st.get("real_loop"))
        self.assertTrue(st.get("worker_alive") or self.orch._worker_alive())
        # Seed curated data then tick
        self.orch.register_batch([
            {
                "instruction": "What is 2+2?",
                "response": "4",
                "source": "test",
                "track": "general_knowledge",
            }
        ])
        tick = self.orch.tick_once()
        self.assertTrue(tick.get("ok"))
        # Without evaluator/score, cycle may skip — still honest
        self.assertIn("cycle", tick)
        status = self.orch.status()
        self.assertIn("worker_alive", status)
        self.assertFalse(status.get("auto_promote"))


class TestUnrestrictAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
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
        os.environ.pop("PFAI_OPEN_CHAT_TOOLS", None)
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_PASSWORD_HASH", None)

    def test_version_is_81(self):
        from pfai import __version__
        self.assertEqual(__version__, "8.1.0")
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("version"), "8.1.0")

    def test_chat_tools_include_cycle_and_tick(self):
        r = self.client.get("/chat/tools")
        self.assertEqual(r.status_code, 200)
        names = {t["name"] for t in r.json()["tools"]}
        self.assertIn("training_cycle_start", names)
        self.assertIn("continuous_tick", names)
        self.assertEqual(r.json().get("locked_count"), 0)

    def test_continuous_start_reports_real_loop(self):
        r = self.client.post("/continuous/start")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("real_loop") or body.get("worker_alive") or body.get("status") == "running")

    def test_chat_continuous_start_completes(self):
        r = self.client.post(
            "/chat/message",
            json={"message": "ابدأ التعلم المستمر", "language": "ar"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(tools.intersection({"continuous_start", "continuous_tick", "continuous_status"}))

    def test_repo_is_apache_licensed(self):
        lic = Path("/agent/pfai/pfai/LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", lic)


class TestOpenCorrection(unittest.TestCase):
    def test_open_flag_true_in_public(self):
        with mock.patch.dict(os.environ, {"PFAI_PUBLIC_ACCESS_MODE": "1", "PFAI_OPEN_CHAT_TOOLS": ""}, clear=False):
            self.assertTrue(open_chat_tools())


if __name__ == "__main__":
    unittest.main()
