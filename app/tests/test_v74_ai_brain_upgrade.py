import json, tempfile, unittest
from pathlib import Path

from pfai.self_reflection import SelfReflectionEngine
from pfai.llm_reasoning import LLMPlanner, LLMCritic, IntelligentReasoner
from pfai.llm_evaluator import LLMEvaluator
from pfai.reasoning_core import ReasoningCore
from pfai.memory import MemoryStore
from pfai.agent import Agent
from pfai.audit import AuditLog
from pfai.tools import ToolGateway
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator


class FakeModel:
    """Returns canned responses in order; raises after the queue is exhausted."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        if not self.responses:
            raise RuntimeError("no more canned responses")
        return self.responses.pop(0)


class BrokenModel:
    def generate(self, prompt, **kwargs):
        raise RuntimeError("model unavailable")


# ---------------------------------------------------------------------------
# SelfReflectionEngine
# ---------------------------------------------------------------------------
class TestSelfReflection(unittest.TestCase):
    def test_stores_lessons_from_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            model = FakeModel([json.dumps({"critique": "fine", "lessons": ["Paris is the capital of France"]})])
            eng = SelfReflectionEngine(model, mem)
            out = eng.reflect("capital of France?", "Paris")
            self.assertEqual(out["stored"], 1)
            self.assertIn("Paris is the capital of France", [m["content"] for m in mem.all_documents()])

    def test_respects_max_lessons_cap(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            model = FakeModel([json.dumps({"lessons": ["a", "b", "c", "d", "e"]})])
            eng = SelfReflectionEngine(model, mem, max_lessons=2)
            out = eng.reflect("q", "a")
            self.assertEqual(out["stored"], 2)

    def test_fails_closed_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            model = FakeModel(["not json at all"])
            eng = SelfReflectionEngine(model, mem)
            out = eng.reflect("q", "a")
            self.assertEqual(out["stored"], 0)
            self.assertEqual(mem.all_documents(), [])

    def test_fails_closed_when_model_raises(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            eng = SelfReflectionEngine(BrokenModel(), mem)
            out = eng.reflect("q", "a")
            self.assertEqual(out["stored"], 0)
            self.assertIn("error", out)

    def test_max_lessons_zero_skips_model_call_entirely(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            model = FakeModel([])  # would raise if called
            eng = SelfReflectionEngine(model, mem, max_lessons=0)
            out = eng.reflect("q", "a")
            self.assertEqual(out["stored"], 0)
            self.assertEqual(model.calls, [])


# ---------------------------------------------------------------------------
# LLMPlanner / LLMCritic / IntelligentReasoner
# ---------------------------------------------------------------------------
class TestLLMPlanner(unittest.TestCase):
    def test_filters_to_whitelist_only(self):
        model = FakeModel([json.dumps(["b", "hack_system", "a"])])
        planner = LLMPlanner(model)
        chosen = planner.plan_actions("goal", ["a", "b"])
        self.assertEqual(chosen, ["b", "a"])
        self.assertNotIn("hack_system", chosen)

    def test_fails_closed_to_given_order_on_bad_output(self):
        model = FakeModel(["not a json array"])
        planner = LLMPlanner(model)
        chosen = planner.plan_actions("goal", ["x", "y"])
        self.assertEqual(chosen, ["x", "y"])

    def test_fails_closed_when_model_raises(self):
        planner = LLMPlanner(BrokenModel())
        chosen = planner.plan_actions("goal", ["x", "y"])
        self.assertEqual(chosen, ["x", "y"])

    def test_empty_allowed_actions_returns_empty(self):
        planner = LLMPlanner(FakeModel([]))
        self.assertEqual(planner.plan_actions("goal", []), [])


class TestLLMCritic(unittest.TestCase):
    def test_reports_passed_and_filters_unknown_retry_actions(self):
        from pfai.reasoning_core import ReasoningTask, ReasoningStep
        task = ReasoningTask("t1", "goal", [ReasoningStep("1", "a", status="success")])
        model = FakeModel([json.dumps({"passed": True, "reason": "ok", "actions": ["a", "nonexistent"]})])
        critic = LLMCritic(model)
        result = critic.critique(task)
        self.assertTrue(result["passed"])
        self.assertEqual(result["actions"], ["a"])

    def test_fails_closed_on_bad_output(self):
        from pfai.reasoning_core import ReasoningTask, ReasoningStep
        task = ReasoningTask("t1", "goal", [ReasoningStep("1", "a", status="success")])
        critic = LLMCritic(FakeModel(["garbage"]))
        result = critic.critique(task)
        self.assertFalse(result["passed"])


class TestIntelligentReasoner(unittest.TestCase):
    def test_end_to_end_plan_execute_verify(self):
        plan_response = json.dumps(["step_a"])
        critique_response = json.dumps({"passed": True, "reason": "done", "actions": []})
        model = FakeModel([plan_response, critique_response])
        reasoner = IntelligentReasoner(model, core=ReasoningCore())

        def handler(step, task):
            return "ok"

        task = reasoner.run("achieve goal", ["step_a"], {"step_a": handler})
        self.assertEqual(task.status, "verified")
        self.assertEqual(task.steps[0].action, "step_a")

    def test_cannot_invent_actions_outside_whitelist(self):
        # even if the model proposes an unknown action, it's dropped before ReasoningCore ever sees it
        model = FakeModel([json.dumps(["not_allowed", "step_a"])])
        reasoner = IntelligentReasoner(model, core=ReasoningCore())
        task = reasoner.core.plan("goal", reasoner.planner.plan_actions("goal", ["step_a"]))
        self.assertEqual([s.action for s in task.steps], ["step_a"])


# ---------------------------------------------------------------------------
# LLMEvaluator
# ---------------------------------------------------------------------------
class TestLLMEvaluator(unittest.TestCase):
    def test_parses_valid_score(self):
        model = FakeModel([json.dumps({"score": 0.8, "reason": "solid examples"})])
        result = LLMEvaluator(model).score_examples([{"instruction": "x", "response": "y"}])
        self.assertEqual(result["score"], 0.8)
        self.assertEqual(result["evaluated"], 1)

    def test_clamps_out_of_range_score(self):
        model = FakeModel([json.dumps({"score": 5.0})])
        result = LLMEvaluator(model).score_examples([{"instruction": "x", "response": "y"}])
        self.assertEqual(result["score"], 1.0)

    def test_fails_closed_to_zero_on_bad_output(self):
        model = FakeModel(["not json"])
        result = LLMEvaluator(model).score_examples([{"instruction": "x", "response": "y"}])
        self.assertEqual(result["score"], 0.0)

    def test_no_examples_returns_zero_without_calling_model(self):
        model = FakeModel([])
        result = LLMEvaluator(model).score_examples([])
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(model.calls, [])


# ---------------------------------------------------------------------------
# ContinuousLearningOrchestrator auto-scoring (human approval gate untouched)
# ---------------------------------------------------------------------------
class TestOrchestratorAutoScoring(unittest.TestCase):
    def test_auto_score_without_evaluator_model_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            self.assertFalse(orch.auto_score()["evaluated"])

    def test_run_cycle_auto_scores_when_score_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            model = FakeModel([json.dumps({"score": 0.77, "reason": "looks fine"})])
            orch = ContinuousLearningOrchestrator(root=d, evaluator_model=model)
            orch.register_batch([
                {"instruction": "Explain database indexing", "response": "An index speeds up lookups.", "source": "t"},
            ])
            result = orch.run_cycle("v1")  # no score supplied
            self.assertTrue(result["evaluated"])
            self.assertTrue(result["auto_scored"])
            self.assertAlmostEqual(result["score"], 0.77)

    def test_human_approval_still_required_after_auto_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            model = FakeModel([json.dumps({"score": 0.9})])
            orch = ContinuousLearningOrchestrator(root=d, evaluator_model=model)
            orch.register_batch([
                {"instruction": "Explain CAP theorem", "response": "You can only guarantee two of consistency, availability, partition tolerance.", "source": "t"},
            ])
            orch.run_cycle("v1")
            self.assertFalse(orch.promote("v1"))  # not approved yet
            self.assertIsNone(orch.loop.active())
            self.assertTrue(orch.approve("v1"))
            self.assertTrue(orch.promote("v1"))

    def test_run_cycle_fails_closed_without_score_or_evaluator(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            orch.register_batch([
                {"instruction": "Explain TCP handshake", "response": "SYN, SYN-ACK, ACK establishes the connection.", "source": "t"},
            ])
            result = orch.run_cycle("v1")
            self.assertFalse(result["evaluated"])


# ---------------------------------------------------------------------------
# Agent + reflector integration
# ---------------------------------------------------------------------------
class TestAgentReflectorIntegration(unittest.TestCase):
    def test_answer_still_returned_even_if_reflector_raises(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            audit = AuditLog(str(Path(d) / "audit.jsonl"))

            class ExplodingReflector:
                def reflect(self, q, a):
                    raise RuntimeError("boom")

            agent = Agent(FakeModel(["the answer"]), mem, ToolGateway(audit=audit), audit,
                           reflector=ExplodingReflector())
            out = agent.answer("question")
            self.assertEqual(out, "the answer")

    def test_reflector_is_invoked_with_question_and_answer(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            audit = AuditLog(str(Path(d) / "audit.jsonl"))
            seen = {}

            class RecordingReflector:
                def reflect(self, q, a):
                    seen["question"] = q; seen["answer"] = a

            agent = Agent(FakeModel(["42"]), mem, ToolGateway(audit=audit), audit,
                           reflector=RecordingReflector())
            agent.answer("what is the answer to everything?")
            self.assertEqual(seen["answer"], "42")
            self.assertEqual(seen["question"], "what is the answer to everything?")


if __name__ == "__main__":
    unittest.main()
