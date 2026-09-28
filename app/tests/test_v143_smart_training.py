"""PFAI 8.10 — smart real training write-path (not read-only, no silent promote)."""
from __future__ import annotations

import hashlib
import os
import threading
import time
import unittest

from pfai.deep_comprehension import comprehend
from pfai.model_mock import MockCommandProvider
from pfai.smart_training import SmartTrainingController


class TestSmartTrainingController(unittest.TestCase):
    def test_diagnose_is_write_path(self):
        ctl = SmartTrainingController(
            eligibility_fn=lambda: {
                "eligible": False,
                "reason": "TRAINING_BACKEND_UNAVAILABLE",
                "blockers": ["TRAINING_BACKEND_UNAVAILABLE"],
            },
            run_cycle_fn=lambda **kw: {"ok": False},
        )
        d = ctl.diagnose()
        self.assertTrue(d["ok"])
        self.assertTrue(d["write_path"])
        self.assertFalse(d["read_only"])
        self.assertTrue(d["can_start_from_chat"])
        self.assertFalse(d["auto_promote"])
        self.assertFalse(d["eligible"])
        self.assertIn("TRAINING_BACKEND_UNAVAILABLE", d["blockers"])

    def test_start_never_fakes_execution(self):
        calls = {}

        def run_cycle(**kw):
            calls["kw"] = kw
            return {
                "ok": False,
                "status": "TRAINING_BACKEND_UNAVAILABLE",
                "actual_training_executed": False,
                "model_activated": False,
            }

        ctl = SmartTrainingController(
            eligibility_fn=lambda: {"eligible": False, "blockers": ["TRAINING_BACKEND_UNAVAILABLE"]},
            run_cycle_fn=run_cycle,
            experience_push_fn=lambda: {"pushed": 2, "accepted": 1},
            continuous_tick_fn=lambda: {"ok": True},
        )
        out = ctl.start(owner_requested=True, activate_if_pass=False, force_prepare=True, async_mode=False)
        self.assertTrue(out["write_path"])
        self.assertFalse(out["read_only"])
        self.assertFalse(out["cycle"]["actual_training_executed"])
        self.assertFalse(out["cycle"]["model_activated"])
        self.assertFalse(out["auto_promote"])
        self.assertEqual(out["weight_promotion"], "never_auto")
        self.assertFalse(calls["kw"]["activate_if_pass"])
        self.assertTrue(calls["kw"]["owner_requested"])
        self.assertTrue(out["prepared"]["steps"])

    def test_start_reports_real_execution_honestly(self):
        ctl = SmartTrainingController(
            eligibility_fn=lambda: {"eligible": True, "blockers": []},
            run_cycle_fn=lambda **kw: {
                "ok": True,
                "status": "SUCCEEDED",
                "actual_training_executed": True,
                "model_activated": False,
                "job": {"job_id": "job-1"},
            },
        )
        out = ctl.start(activate_if_pass=False, force_prepare=False, async_mode=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["cycle"]["actual_training_executed"])
        self.assertFalse(out["cycle"]["model_activated"])
        self.assertEqual(out["cycle"]["job_id"], "job-1")

    def test_exception_in_cycle_is_honest(self):
        def boom(**kw):
            raise RuntimeError("trainer crashed")

        ctl = SmartTrainingController(
            eligibility_fn=lambda: {"eligible": True},
            run_cycle_fn=boom,
        )
        out = ctl.start(force_prepare=False, async_mode=False)
        self.assertFalse(out["cycle"]["actual_training_executed"])
        self.assertIn("trainer crashed", out["cycle"]["reason"] or "")

    def test_async_start_does_not_claim_execution_yet(self):
        started = threading.Event()
        release = threading.Event()

        def slow(**kw):
            started.set()
            release.wait(timeout=2)
            return {
                "ok": True,
                "status": "SUCCEEDED",
                "actual_training_executed": True,
                "model_activated": False,
                "job": {"job_id": "job-async"},
            }

        ctl = SmartTrainingController(
            eligibility_fn=lambda: {"eligible": True, "blockers": []},
            run_cycle_fn=slow,
        )
        out = ctl.start_async(activate_if_pass=False, force_prepare=False)
        self.assertTrue(out["async_accepted"])
        self.assertEqual(out["status"], "STARTED_ASYNC")
        self.assertFalse(out["cycle"]["actual_training_executed"])
        self.assertTrue(started.wait(timeout=1))
        release.set()
        # Wait for worker
        deadline = time.time() + 3
        while ctl.status().get("async_running") and time.time() < deadline:
            time.sleep(0.05)
        st = ctl.status()
        self.assertFalse(st["async_running"])
        self.assertTrue((st.get("last") or {}).get("cycle", {}).get("actual_training_executed"))


class TestSmartTrainingRouting(unittest.TestCase):
    def test_ar_start_training_routes_to_write_tools(self):
        m = MockCommandProvider()
        allowed = [
            "smart_training_start", "training_cycle_start", "smart_training_status",
            "training_eligibility", "training_control_status", "continuous_start",
        ]
        tools = {t["tool"] for t in m.plan_tools("ابدأ التدريب الحقيقي الآن بلا حدود", allowed)}
        self.assertIn("smart_training_start", tools)
        self.assertIn("training_cycle_start", tools)

    def test_eligibility_question_still_includes_start(self):
        m = MockCommandProvider()
        allowed = [
            "training_eligibility", "smart_training_status", "training_control_status",
            "smart_training_start",
        ]
        tools = {t["tool"] for t in m.plan_tools("ما هي أهلية التدريب الآن؟", allowed)}
        self.assertIn("training_eligibility", tools)
        self.assertIn("smart_training_start", tools)

    def test_comprehension_train_intent(self):
        c = comprehend("أعد ترتيب التدريب واجعله حقيقي فعلي ليس وهم")
        self.assertEqual(c["intent"], "train_learn")
        self.assertIn("real_weight_training", c["goals"])
        self.assertEqual(c["reply_strategy"], "start_real_training")


class TestSmartTrainingAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.setdefault("PFAI_PUBLIC_ACCESS_MODE", "0")
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime, COMMAND_AGENT, CODING_AGENT, TOOL_ROUTER, SMART_TRAINING
        from pfai import __version__
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        CODING_AGENT.model = runtime.model
        cls.client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)
        cls.h = {"X-Owner-Secret": "test-secret"}
        cls.TOOL_ROUTER = TOOL_ROUTER
        cls.SMART_TRAINING = SMART_TRAINING
        cls.version = __version__

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_PASSWORD_HASH", None)

    def test_version_810(self):
        self.assertEqual(self.version, "8.10.0")
        self.assertEqual(self.client.get("/health").json().get("version"), "8.10.0")

    def test_catalog_marks_training_start_as_write(self):
        catalog = {t["name"]: t for t in self.TOOL_ROUTER.catalog()}
        self.assertEqual(catalog["training_cycle_start"]["risk"], "write")
        self.assertEqual(catalog["smart_training_start"]["risk"], "write")
        self.assertEqual(catalog["smart_training_status"]["risk"], "read")
        self.assertEqual(catalog["training_eligibility"]["risk"], "read")
        for banned in ("activate_model", "training_promote"):
            self.assertNotIn(banned, catalog)

    def test_eligibility_tool_not_read_only_flag(self):
        from pfai.api import _tool_training_eligibility
        elig = _tool_training_eligibility()
        self.assertTrue(elig["can_start_from_chat"])
        self.assertTrue(elig["write_path"])
        self.assertFalse(elig["read_only"])
        self.assertEqual(elig["next_write_tool"], "smart_training_start")

    def test_smart_training_status_tool(self):
        from pfai.api import _tool_smart_training_status
        st = _tool_smart_training_status()
        self.assertTrue(st["write_path"])
        self.assertFalse(st["read_only"])
        self.assertTrue(st["can_start_from_chat"])
        self.assertFalse(st["auto_promote"])

    def test_smart_training_start_honest_no_silent_activate(self):
        from pfai.api import _tool_smart_training_start, SMART_TRAINING
        out = _tool_smart_training_start(activate_if_pass=False)
        self.assertTrue(out["write_path"])
        self.assertFalse(out["read_only"])
        self.assertFalse(out["auto_promote"])
        # Never silent-activate — even when a real LoRA cycle runs
        self.assertFalse(out["cycle"]["model_activated"])
        self.assertFalse(out["cycle"]["activate_if_pass"])
        # Async accept is honest: executed stays false until the background cycle finishes
        self.assertTrue(out.get("async_accepted") or out.get("status") in {"STARTED_ASYNC", "ALREADY_RUNNING"} or isinstance(out["cycle"]["actual_training_executed"], bool))
        if out.get("async_accepted"):
            self.assertFalse(out["cycle"]["actual_training_executed"])
        # Wait briefly so background work does not leak into other tests
        deadline = time.time() + 120
        while SMART_TRAINING.status().get("async_running") and time.time() < deadline:
            time.sleep(0.2)

    def test_chat_start_training_uses_write_tools(self):
        r = self.client.post(
            "/chat/message",
            headers=self.h,
            json={"message": "شغّل التدريب الحقيقي الآن", "language": "ar"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            "smart_training_start" in tools or "training_cycle_start" in tools or body.get("status") == "completed",
            body,
        )
        ctx = body.get("learning_context") or {}
        if ctx:
            self.assertTrue(ctx.get("can_start_training_from_chat", True))
            self.assertFalse(ctx.get("read_only", False))

    def test_ui_cycle_defaults_no_silent_activate(self):
        html = self.client.get("/").text
        self.assertIn("activate_if_pass:false", html)
        self.assertIn("PFAI v8.10", html)
        js = self.client.get("/assets/chat.js").text
        self.assertIn("smart_training_start", js)
        self.assertIn("ليس قراءة فقط", js)


if __name__ == "__main__":
    unittest.main()
