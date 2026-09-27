import tempfile
import unittest

from pfai.code_learning_pipeline import CodeLearningPipeline
from pfai.code_execution_evaluator import SandboxedCodeEvaluator
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.policy import Policy
from pfai.research_gate import ResearchGate

GOOD_ADD = "def add(a, b):\n    return a + b\n"
TEST_ADD = "assert add(2, 3) == 5\nassert add(-1, 1) == 0\n"


class _StubWeb:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        return self.pages[url]


class PromptCapturingModel:
    """Returns GOOD_ADD every time but records every prompt it was asked."""
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return GOOD_ADD


class TestCodeLearningPipelineResearch(unittest.TestCase):
    def test_backward_compatible_with_no_research_gate(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1)
            result = pipe.solve_and_learn("write an add function", TEST_ADD)
            self.assertTrue(result["solved"])
            self.assertEqual(result["research"], [])
            self.assertNotIn("reference", model.prompts[0])

    def test_reference_urls_ignored_without_a_configured_research_gate(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1)
            result = pipe.solve_and_learn("write an add function", TEST_ADD,
                                           reference_urls=["https://docs.python.org/x"])
            self.assertTrue(result["solved"])
            self.assertEqual(result["research"], [])

    def test_allowed_reference_is_fetched_and_included_in_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            policy = Policy({"allow_network": True, "allowed_domains": ["docs.python.org"]})
            gate = ResearchGate(policy, web=_StubWeb({"https://docs.python.org/x": "use a+b, not a-b"}),
                                 ledger_path=f"{d}/research_ledger.jsonl")
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1,
                                         research_gate=gate)
            result = pipe.solve_and_learn("write an add function", TEST_ADD,
                                           reference_urls=["https://docs.python.org/x"])
            self.assertTrue(result["solved"])
            self.assertIn("use a+b, not a-b", model.prompts[0])
            self.assertIn("untrusted", model.prompts[0])  # framed as reference, not instruction
            self.assertEqual(len(result["research"]), 1)
            self.assertTrue(result["research"][0]["fetched"])
            self.assertTrue(result["research"][0]["content_hash"])

    def test_curated_example_carries_research_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            policy = Policy({"allow_network": True, "allowed_domains": ["docs.python.org"]})
            gate = ResearchGate(policy, web=_StubWeb({"https://docs.python.org/x": "reference text"}),
                                 ledger_path=f"{d}/research_ledger.jsonl")
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1,
                                         research_gate=gate)
            pipe.solve_and_learn("write an add function", TEST_ADD,
                                  reference_urls=["https://docs.python.org/x"])
            pending = orch.pending_examples()
            self.assertEqual(len(pending), 1)
            self.assertIn("research", pending[0]["metadata"])
            self.assertEqual(pending[0]["metadata"]["research"][0]["url"], "https://docs.python.org/x")

    def test_denied_domain_does_not_break_the_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            policy = Policy({"allow_network": True, "allowed_domains": ["only-this.example"]})
            gate = ResearchGate(policy, web=_StubWeb({}), ledger_path=f"{d}/research_ledger.jsonl")
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1,
                                         research_gate=gate)
            result = pipe.solve_and_learn("write an add function", TEST_ADD,
                                           reference_urls=["https://not-allowed.example/x"])
            self.assertTrue(result["solved"])
            self.assertFalse(result["research"][0]["allowed"])
            self.assertNotIn("reference", model.prompts[0])

    def test_never_promotes_anything_by_itself_even_with_research(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            model = PromptCapturingModel()
            policy = Policy({"allow_network": True, "allowed_domains": ["docs.python.org"]})
            gate = ResearchGate(policy, web=_StubWeb({"https://docs.python.org/x": "text"}),
                                 ledger_path=f"{d}/research_ledger.jsonl")
            pipe = CodeLearningPipeline(model, orch, evaluator=SandboxedCodeEvaluator(), n=1,
                                         research_gate=gate)
            pipe.solve_and_learn("write an add function", TEST_ADD,
                                  reference_urls=["https://docs.python.org/x"])
            self.assertIsNone(orch.loop.active())


if __name__ == "__main__":
    unittest.main()
