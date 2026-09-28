"""Coding Academy / Coding Intelligence tests."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.coding_curriculum import CurriculumEngine
from pfai.coding_skill_profile import SkillProfileStore
from pfai.coding_tutor import CodingTutor
from pfai.coding_reviewer import CodingReviewer
from pfai.coding_debugger import DebuggingTrainer
from pfai.coding_quality import CodingQualityGate
from pfai.coding_agent import CodingAgent
from pfai.coding_academy_memory import CodingAcademyMemory
from pfai.coding_training_scaffold import CodingTrainingScaffold
from pfai.memory import MemoryStore
from pfai.tool_router import ToolRouter


class TestCurriculumEngine(unittest.TestCase):
    def setUp(self):
        self.eng = CurriculumEngine("configs/coding")

    def test_tracks_extensible(self):
        tracks = self.eng.list_tracks()
        self.assertGreaterEqual(len(tracks), 5)
        ids = {t["id"] for t in tracks}
        self.assertIn("python", ids)

    def test_personalize_path(self):
        path = self.eng.personalize_path("python", {"syntax": 0.2, "testing": 0.9}, goal="learn python")
        self.assertTrue(path["ok"])
        self.assertTrue(path["path"])


class TestSkillAndTutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eng = CurriculumEngine("configs/coding")
        self.profiles = SkillProfileStore(str(Path(self.tmp.name) / "p.sqlite3"), eng)
        self.tutor = CodingTutor(eng, self.profiles)

    def tearDown(self):
        self.tmp.cleanup()

    def test_assessment_and_progress(self):
        start = self.profiles.start_assessment()
        self.assertGreater(start["count"], 5)
        answers = {}
        for item in CurriculumEngine("configs/coding").assessments():
            answers[item["id"]] = item["answer"]
        graded = self.profiles.grade_assessment("owner@x", answers)
        self.assertTrue(graded["ok"])
        self.assertEqual(graded["level"], "advanced")

    def test_hint_then_sandbox_pass(self):
        h1 = self.tutor.hint("owner@x", "python", "py-intro")
        self.assertTrue(h1["ok"])
        self.assertEqual(h1["level"], 1)
        result = self.tutor.submit_exercise("owner@x", "python", "py-intro", "def answer():\n    return 15\n")
        self.assertTrue(result["passed"])


class TestReviewDebugQuality(unittest.TestCase):
    def test_review_flags_bare_except(self):
        r = CodingReviewer().review("try:\n x=1\nexcept:\n pass\n")
        cats = {f["category"] for f in r["findings"]}
        self.assertIn("correctness", cats)

    def test_debug_progressive(self):
        d = DebuggingTrainer()
        s = d.start("o", "def f():\n return 1\n", "assert f()==2")
        r1 = d.respond(s["session_id"], "maybe wrong return")
        self.assertEqual(r1["status"], "hint")
        r2 = d.respond(s["session_id"], "still unsure")
        self.assertEqual(r2["hint_level"], 2)

    def test_quality_gate_untested(self):
        q = CodingQualityGate().evaluate_answer("def ok():\n return 1\n", "")
        self.assertEqual(q["claim"], "untested")


class TestCodingAgentAndMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eng = CurriculumEngine("configs/coding")
        profiles = SkillProfileStore(str(Path(self.tmp.name) / "p.sqlite3"), eng)
        mem = CodingAcademyMemory(MemoryStore(str(Path(self.tmp.name) / "m.sqlite3")))
        self.agent = CodingAgent(model=None, curriculum=eng, profiles=profiles, academy_memory=mem)
        self.scaffold = CodingTrainingScaffold(str(Path(self.tmp.name) / "scaffold"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_teach_intent(self):
        r = self.agent.handle("علمني Python", owner="o@x")
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "teach")
        self.assertTrue(r.get("path", {}).get("ok"))

    def test_scaffold_no_autofinetune(self):
        self.scaffold.add_example(owner="o", kind="exercise", prompt="x", response="y")
        st = self.scaffold.status()
        self.assertFalse(st["auto_finetune"])
        self.assertEqual(st["examples"], 1)


class TestCodingAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime, COMMAND_AGENT, CODING_AGENT
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        CODING_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.h = {"X-Owner-Secret": "test-secret"}

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_PASSWORD_HASH", None)

    def test_tracks_and_sandbox(self):
        t = self.client.get("/coding/tracks", headers=self.h)
        self.assertEqual(t.status_code, 200)
        self.assertTrue(t.json()["tracks"])
        s = self.client.post("/coding/sandbox", headers=self.h, json={"code": "def answer():\n return 15\n", "test_code": "assert answer()==15"})
        self.assertEqual(s.status_code, 200)
        self.assertTrue(s.json()["passed"])

    def test_chat_teach_delegate(self):
        r = self.client.post("/chat/message", headers=self.h, json={"message": "علمني Python"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("coding", body)
        self.assertEqual(body["coding"]["intent"], "teach")

    def test_coding_chat_review(self):
        r = self.client.post("/coding/chat", headers=self.h, json={
            "message": "راجع هذا الكود",
            "code": "def add(a,b):\n return a+b\n",
            "mode": "learning",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["intent"], "review")

    def test_permission_required(self):
        self.assertEqual(self.client.get("/coding/tracks").status_code, 401)


if __name__ == "__main__":
    unittest.main()
