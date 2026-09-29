"""Advanced Command Chat linked to Coding Academy + read-only training status."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.coding_agent import CodingAgent, build_learning_context
from pfai.coding_curriculum import CurriculumEngine
from pfai.coding_skill_profile import SkillProfileStore
from pfai.model_mock import MockCommandProvider


class TestLearningContextHelper(unittest.TestCase):
    def test_build_learning_context_from_exercise(self):
        ctx = build_learning_context({
            "mode": "learning",
            "intent": "exercise",
            "track_id": "python",
            "lesson": {
                "lesson": {"id": "py-intro", "title": "Intro", "track_id": "python"},
                "exercise": {"prompt": "return 15", "hints_available": 2, "starter": "def answer():\n pass"},
            },
            "next": {"next": {"id": "py-intro"}},
        })
        self.assertEqual(ctx["intent"], "exercise")
        self.assertEqual(ctx["track_id"], "python")
        self.assertEqual(ctx["lesson_id"], "py-intro")
        self.assertTrue(ctx["has_exercise"])
        self.assertFalse(ctx["training_auto"])
        self.assertTrue(ctx["can_start_training_from_chat"])


class TestMockTrainingRouting(unittest.TestCase):
    def test_eligibility_routes_to_training_status_and_start(self):
        m = MockCommandProvider()
        allowed = [
            "training_eligibility", "training_control_status", "continuous_status",
            "continuous_start", "coding_teach", "learner_snapshot", "coding_progress",
            "coding_next_lesson", "system_status", "smart_training_status", "smart_training_start",
        ]
        tools = {t["tool"] for t in m.plan_tools("ما هي أهلية التدريب الآن؟", allowed)}
        self.assertIn("training_eligibility", tools)
        self.assertIn("training_control_status", tools)
        self.assertIn("smart_training_start", tools)  # write path available from eligibility turn
        self.assertNotIn("continuous_start", tools)

    def test_learner_snapshot_routing(self):
        m = MockCommandProvider()
        allowed = ["learner_snapshot", "coding_progress", "system_status"]
        tools = {t["tool"] for t in m.plan_tools("ما هو تقدمي في الأكاديمية", allowed)}
        self.assertIn("learner_snapshot", tools)


class TestCodingAgentLearningContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eng = CurriculumEngine("configs/coding")
        profiles = SkillProfileStore(str(Path(self.tmp.name) / "p.sqlite3"), eng)
        self.agent = CodingAgent(model=None, curriculum=eng, profiles=profiles)

    def tearDown(self):
        self.tmp.cleanup()

    def test_teach_includes_learning_context(self):
        r = self.agent.handle("علمني Python", owner="learner@x")
        self.assertTrue(r["ok"])
        self.assertIn("learning_context", r)
        self.assertEqual(r["learning_context"]["intent"], "teach")
        self.assertTrue(r["learning_context"]["can_start_training_from_chat"])

    def test_exercise_includes_track_and_starter(self):
        r = self.agent.handle("أعطني تمرين", owner="learner@x")
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "exercise")
        lesson = r.get("lesson") or {}
        self.assertTrue((lesson.get("exercise") or {}).get("prompt") or lesson.get("ok"))
        self.assertFalse(r["learning_context"]["training_auto"])


class TestAdvancedChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.setdefault("PFAI_PUBLIC_ACCESS_MODE", "0")
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime, COMMAND_AGENT, CODING_AGENT, TOOL_ROUTER
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        CODING_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.h = {"X-Owner-Secret": "test-secret"}
        cls.TOOL_ROUTER = TOOL_ROUTER

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_PASSWORD_HASH", None)

    def test_chat_tools_include_education_and_training_write_path(self):
        r = self.client.get("/chat/tools", headers=self.h)
        self.assertEqual(r.status_code, 200)
        names = {t["name"] for t in r.json()["tools"]}
        for n in (
            "training_eligibility", "training_control_status",
            "learner_snapshot", "coding_next_lesson",
            "coding_teach", "coding_progress",
            "smart_training_start", "smart_training_status",
        ):
            self.assertIn(n, names)
        # Weight activation / promote must not be chat tools; cycle start is write path
        self.assertIn("training_cycle_start", names)
        self.assertIn("continuous_tick", names)
        for banned in ("activate_model", "platform_training_cycle", "training_promote"):
            self.assertNotIn(banned, names)

    def test_status_tools_read_and_start_tools_write(self):
        catalog = {t["name"]: t for t in self.TOOL_ROUTER.catalog()}
        for n in ("training_eligibility", "training_control_status", "learner_snapshot", "smart_training_status"):
            self.assertEqual(catalog[n]["risk"], "read")
            self.assertFalse(catalog[n]["requires_approval"])
        for n in ("training_cycle_start", "smart_training_start"):
            self.assertEqual(catalog[n]["risk"], "write")
            self.assertFalse(catalog[n]["requires_approval"])  # open mode — no approval friction

    def test_chat_teach_returns_learning_context_and_hub(self):
        r = self.client.post("/chat/message", headers=self.h, json={"message": "علمني Python"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("coding", body)
        self.assertIn("learning_context", body)
        self.assertEqual(body["learning_context"]["intent"], "teach")
        self.assertTrue(body["learning_context"]["can_start_training_from_chat"])
        self.assertIn("learning_hub", body)
        self.assertTrue(body["learning_hub"]["training_from_chat"])

    def test_chat_training_eligibility_readonly(self):
        r = self.client.post(
            "/chat/message",
            headers=self.h,
            json={"message": "ما هي أهلية التدريب الآن؟", "language": "ar"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotIn("coding", body)  # should not delegate to academy teach
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            "training_eligibility" in tools or "training_control_status" in tools or body.get("status") == "completed",
            body,
        )
        # Eligibility is a write-path probe (not read-only) but does not claim trained yet
        for t in body.get("tools") or []:
            res = t.get("result") or {}
            if t.get("tool") in {"training_eligibility", "training_control_status"}:
                self.assertTrue(res.get("can_start_from_chat"))
                self.assertFalse(res.get("read_only", False))
                self.assertFalse(res.get("trained"))
        reply = body.get("reply") or ""
        self.assertTrue(
            any(x in reply for x in ("مسار كتابة", "write path", "ليس وهماً", "ابدأ التدريب", "أهلية")),
            reply,
        )

    def test_exercise_submit_never_marks_trained(self):
        r = self.client.post(
            "/coding/exercise/submit",
            headers=self.h,
            json={
                "track_id": "python",
                "lesson_id": "py-intro",
                "code": "def answer():\n    return 15\n",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        if body.get("passed"):
            self.assertIn("learning_candidate", body)
            self.assertFalse(body["learning_candidate"].get("trained"))

    def test_chat_assets_mention_academy_bridge(self):
        asset = self.client.get("/assets/chat.js")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("learning_context", asset.text)
        self.assertIn("training_eligibility", asset.text)
        self.assertIn("/coding/exercise/submit", asset.text)
        dash = self.client.get("/")
        self.assertEqual(dash.status_code, 200)
        self.assertIn("chatLearnLevel", dash.text)
        self.assertIn("أهلية التدريب", dash.text)


if __name__ == "__main__":
    unittest.main()
