"""PFAI 8.6 — advanced aware self-develop with multi-pass code build."""
import hashlib
import os
import unittest

from pfai.advanced_self_develop import AdvancedSelfDevelop, _CURRICULUM
from pfai.code_execution_evaluator import SandboxedCodeEvaluator
from pfai.model_mock import MockCommandProvider


class _FakeContinuous:
    def __init__(self):
        self.batches = []
        self._pending = 5
        self._hist = [{"status": "accepted", "score": 0.9}, {"status": "accepted", "score": 0.91}]

    def status(self):
        return {
            "service": {"status": "running"},
            "worker_alive": True,
            "real_loop": True,
            "pending_examples": self._pending,
            "learning_history": self._hist,
        }

    def register_batch(self, rows):
        self.batches.extend(rows)
        self._pending += len(rows)
        return {"submitted": len(rows), "accepted": len(rows), "rejected": 0}

    def tick_once(self):
        return {"ok": True, "cycle": {"skipped": True}}


class _FakePipe:
    def __init__(self, evaluator):
        self.model = None
        self.evaluator = evaluator
        self.auto_fixer = None

    def solve_and_learn(self, instruction, test_code, source="x", task_id=""):
        # Pretend model failed so curriculum teacher path is exercised
        return {"solved": False, "reason": "no candidate", "curated": False}


class TestAdvancedUnit(unittest.TestCase):
    def setUp(self):
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_AUTO_ACCEPT_LEARNING"] = "1"
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "1"
        self.eval = SandboxedCodeEvaluator()
        self.cont = _FakeContinuous()
        self.adv = AdvancedSelfDevelop(
            code_learning=_FakePipe(self.eval),
            continuous=self.cont,
            evaluator=self.eval,
            review_passes=3,
            max_repairs=4,
            journal_path="data/longevity/test_advanced_self_develop.jsonl",
        )

    def test_maturity_advanced(self):
        m = self.adv.maturity()
        self.assertIn(m["stage"], {"advanced", "sovereign_safe", "capable"})
        self.assertEqual(m["weight_promotion"], "never_auto")

    def test_awareness_lists_boundaries(self):
        a = self.adv.awareness()
        self.assertTrue(a["aware"])
        self.assertIn("silent_weight_promotion", a["i_will_not"])

    def test_multi_pass_curriculum_teacher(self):
        task = _CURRICULUM[0]
        out = self.adv.multi_pass_build(
            task["instruction"],
            task["test_code"],
            allow_reference=task["reference"],
        )
        self.assertTrue(out["solved"])
        self.assertTrue(out["curated"])
        self.assertEqual(out["origin"], "curriculum_teacher")
        self.assertGreaterEqual(len(out["passes"]), 3)

    def test_autonomous_cycle(self):
        out = self.adv.autonomous_cycle(force=True, include_continuous_tick=False)
        self.assertTrue(out["ran"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["weight_promotion"], "never_auto")

    def test_planner_routes_arabic_advanced(self):
        m = MockCommandProvider()
        allowed = [
            "advanced_self_develop", "advanced_status", "advanced_awareness",
            "autonomy_status", "self_improve_tick", "coding_teach",
        ]
        tools = {t["tool"] for t in m.plan_tools(
            "أريد مرحلة متطورة يبني الأكواد ويراجع أكثر من مرة بدون الرجوع لأحد",
            allowed,
        )}
        self.assertIn("advanced_self_develop", tools)
        self.assertIn("advanced_awareness", tools)


class TestAdvancedAPI(unittest.TestCase):
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
        from pfai.api import app, runtime, COMMAND_AGENT, CONTINUOUS, ADVANCED
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = EchoProvider()
        cls.client = TestClient(app)
        cls.CONTINUOUS = CONTINUOUS
        cls.ADVANCED = ADVANCED

    @classmethod
    def tearDownClass(cls):
        try:
            cls.CONTINUOUS.stop("test")
        except Exception:
            pass

    def test_version_and_tools(self):
        from pfai import __version__
        self.assertTrue(__version__.startswith("8."))
        tools = {t["name"] for t in self.client.get("/chat/tools").json()["tools"]}
        for n in ("advanced_self_develop", "advanced_status", "advanced_awareness", "advanced_code_build"):
            self.assertIn(n, tools)

    def test_chat_advanced_cycle(self):
        r = self.client.post("/chat/message", json={
            "message": "مرحلة متطورة يبني الأكواد ويراجع أكثر من مرة بدون الرجوع لأحد",
            "language": "ar",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        names = [t.get("tool") for t in (body.get("tools") or [])]
        self.assertTrue(any(n and n.startswith("advanced_") for n in names))


if __name__ == "__main__":
    unittest.main()
