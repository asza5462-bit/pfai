import tempfile, unittest

from pfai.code_learning_pipeline import CodeLearningPipeline
from pfai.code_execution_evaluator import SandboxedCodeEvaluator
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator


GOOD_ADD = "def add(a, b):\n    return a + b\n"
BUGGY_ADD = "def add(a, b):\n    return a - b\n"
TEST_ADD = "assert add(2, 3) == 5\nassert add(-1, 1) == 0\n"


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        if not self.responses:
            raise RuntimeError("no more canned responses")
        return self.responses.pop(0)


class TestCodeLearningPipeline(unittest.TestCase):
    def test_curates_the_first_passing_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = FakeModel([BUGGY_ADD, GOOD_ADD, GOOD_ADD])
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=3)
            result = pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertTrue(result["solved"])
            self.assertTrue(result["curated"])
            self.assertIn("return a + b", result["code"])

    def test_does_not_curate_when_nothing_passes(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = FakeModel([BUGGY_ADD, BUGGY_ADD])
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=2)
            result = pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertFalse(result["solved"])
            self.assertFalse(result["curated"])
            self.assertEqual(orch.pending_examples(), [])

    def test_strips_markdown_fences_from_model_output(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            fenced = "```python\n" + GOOD_ADD + "```"
            model = FakeModel([fenced])
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1)
            result = pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertTrue(result["solved"])
            self.assertNotIn("```", result["code"])

    def test_rejects_empty_instruction_or_tests(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            pipe = CodeLearningPipeline(FakeModel([]), orch)
            result = pipe.solve_and_learn("", TEST_ADD)
            self.assertFalse(result["solved"])
            self.assertEqual(pipe.model.calls, 0)

    def test_survives_model_errors_on_some_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)

            class FlakyModel:
                def __init__(self):
                    self.n = 0
                def generate(self, prompt, **kwargs):
                    self.n += 1
                    if self.n == 1:
                        raise RuntimeError("transient error")
                    return GOOD_ADD

            pipe = CodeLearningPipeline(FlakyModel(), orch, evaluator=SandboxedCodeEvaluator(), n=2)
            result = pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertTrue(result["solved"])

    def test_never_promotes_anything_by_itself(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = FakeModel([GOOD_ADD])
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1)
            pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertIsNone(orch.loop.active())  # curated only, nothing active


if __name__ == "__main__":
    unittest.main()
