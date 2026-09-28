"""PFAI 8.6 — chat master control: coding strength + web tools + unified plane."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.coding_agent import CodingAgent
from pfai.coding_curriculum import CurriculumEngine
from pfai.coding_skill_profile import SkillProfileStore
from pfai.coding_tutor import CodingTutor
from pfai.model_mock import MockCommandProvider


class TestStrongerCodingTutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eng = CurriculumEngine("configs/coding")
        profiles = SkillProfileStore(str(Path(self.tmp.name) / "p.sqlite3"), eng)
        self.tutor = CodingTutor(eng, profiles)
        self.agent = CodingAgent(model=None, curriculum=eng, profiles=profiles)

    def tearDown(self):
        self.tmp.cleanup()

    def test_curriculum_has_advanced_python_lessons(self):
        eng = CurriculumEngine("configs/coding")
        ids = {l["id"] for l in (eng.get_track("python") or {}).get("lessons") or eng.list_tracks() and []}
        # Fallback: list lessons via personalize path
        path = eng.personalize_path("python", {}, goal="master python")
        lesson_ids = {x["id"] for x in (path.get("path") or [])}
        self.assertTrue({"py-dicts", "py-oop", "py-exceptions"} & lesson_ids or len(path.get("path") or []) >= 4)

    def test_hint_includes_diagnostic_on_stub(self):
        h = self.tutor.hint("u", "python", "py-intro", code="def answer():\n    pass\n")
        self.assertTrue(h.get("ok"))
        self.assertTrue(h.get("hint"))
        self.assertIn("pass", (h.get("diagnostic") or h.get("hint") or "").lower())

    def test_submit_fail_teaches(self):
        r = self.tutor.submit_exercise("u", "python", "py-intro", "def answer():\n    return 0\n")
        self.assertFalse(r.get("passed"))
        self.assertTrue(r.get("teaching"))

    def test_submit_pass(self):
        r = self.tutor.submit_exercise("u", "python", "py-intro", "def answer():\n    return 15\n")
        self.assertTrue(r.get("passed"))

    def test_agent_hint_reply_contains_text(self):
        r = self.agent.handle("أعطني تلميح", owner="u")
        self.assertTrue(r.get("ok"))
        self.assertIn("Hint", r.get("reply") or "")


class TestMockWebAndCodingRouting(unittest.TestCase):
    def test_web_research_not_research_verify(self):
        m = MockCommandProvider()
        allowed = [
            "web_search", "web_research", "web_status", "web_fetch",
            "research_verify", "system_status", "coding_teach", "coding_tracks",
        ]
        planned = m.plan_tools("ابحث في الويب عن Python typing", allowed)
        tools = {t["tool"] for t in planned}
        self.assertIn("web_search", tools)
        self.assertIn("web_status", tools)
        self.assertNotIn("research_verify", tools)
        # Must not stack coding tools on a web turn (was causing 80s stalls)
        self.assertNotIn("coding_teach", tools)
        self.assertNotIn("coding_tracks", tools)
        self.assertNotIn("web_research", tools)  # deep research only on explicit research

    def test_master_control_routing(self):
        m = MockCommandProvider()
        allowed = ["app_control_status", "system_status", "continuous_status", "web_status"]
        tools = {t["tool"] for t in m.plan_tools("أظهر التحكم الكامل للتطبيق", allowed)}
        self.assertIn("app_control_status", tools)

    def test_coding_hint_tool_routing(self):
        m = MockCommandProvider()
        allowed = ["coding_hint", "coding_teach", "system_status"]
        tools = {t["tool"] for t in m.plan_tools("أعطني تلميح", allowed)}
        self.assertIn("coding_hint", tools)


class TestChatMasterAPI(unittest.TestCase):
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
            cls.CONTINUOUS.stop("test")
        except Exception:
            pass
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"
        os.environ.pop("PFAI_OPEN_CHAT_TOOLS", None)

    def test_version_82(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8.6"))
        self.assertTrue(str(self.client.get("/health").json().get("version")).startswith("8.6"))

    def test_tools_catalog_master(self):
        r = self.client.get("/chat/tools")
        names = {t["name"] for t in r.json()["tools"]}
        for n in (
            "web_search", "web_fetch", "web_research", "web_status",
            "coding_hint", "coding_exercise_submit", "app_control_status",
            "training_cycle_start", "continuous_tick",
        ):
            self.assertIn(n, names)
        self.assertEqual(r.json().get("locked_count"), 0)

    def test_app_control_status_tool(self):
        r = self.client.post("/chat/message", json={"message": "أظهر التحكم الكامل للتطبيق", "language": "ar"})
        self.assertEqual(r.status_code, 200, r.text)
        tools = {t.get("tool") for t in (r.json().get("tools") or [])}
        # Master control may collapse into unified pulse (one mind) or app_control
        self.assertTrue(tools & {"app_control_status", "unified_brain_pulse"}, tools)

    def test_coding_exercise_submit_tool(self):
        from pfai.api import TOOL_ROUTER
        out = TOOL_ROUTER.execute(
            "coding_exercise_submit",
            {"owner": "public", "track_id": "python", "lesson_id": "py-intro", "code": "def answer():\n    return 15\n"},
            approved=True,
            actor="public",
        )
        self.assertTrue(out.get("ok"), out)
        self.assertTrue((out.get("result") or {}).get("passed"))

    def test_web_status_tool(self):
        from pfai.api import TOOL_ROUTER
        out = TOOL_ROUTER.execute("web_status", {}, approved=True, actor="public")
        self.assertTrue(out.get("ok"), out)
        self.assertIn("WEB_FABRIC_STATUS", out.get("result") or {})

    def test_ui_mentions_web_and_master(self):
        html = self.client.get("/").text
        self.assertIn("بحث ويب", html)
        self.assertIn("تحكم كامل", html)
        self.assertIn("PFAI v8.6", html)


if __name__ == "__main__":
    unittest.main()
