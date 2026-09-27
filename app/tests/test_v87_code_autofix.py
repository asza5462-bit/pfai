import tempfile, unittest
from pfai.code_autofix_engine import CodeAutoFixEngine
from pfai.code_learning_pipeline import CodeLearningPipeline
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.code_execution_evaluator import SandboxedCodeEvaluator

class RepairModel:
    def __init__(self): self.calls=0
    def generate(self, prompt, **kwargs):
        self.calls += 1
        if "VERIFIER FAILURE" in prompt:
            return "def add(a, b):\n    return a + b\n"
        if "adversarial Python assertions" in prompt:
            return "assert add(0, 0) == 0\nassert add(-2, 5) == 3\n"
        return "def add(a, b):\n    return a - b\n"

class TestAutoFix(unittest.TestCase):
    def test_repairs_failed_code_and_records_regression(self):
        with tempfile.TemporaryDirectory() as d:
            m=RepairModel(); e=SandboxedCodeEvaluator()
            r=CodeAutoFixEngine(m,e,max_repairs=2,regression_root=d).solve_and_repair(
                "write add", "def add(a,b):\n return a-b\n", "assert add(2,3)==5")
            self.assertTrue(r.solved); self.assertEqual(r.repairs,1)
            self.assertTrue(r.regression_added)

    def test_pipeline_uses_adversarial_verification(self):
        with tempfile.TemporaryDirectory() as d:
            orch=ContinuousLearningOrchestrator(root=d)
            m=RepairModel()
            p=CodeLearningPipeline(m,orch,evaluator=SandboxedCodeEvaluator(),n=1,max_repairs=2,adversarial_rounds=1)
            r=p.solve_and_learn("write add", "assert add(2,3)==5")
            self.assertTrue(r["solved"])
            self.assertTrue(r["curated"])

if __name__ == '__main__': unittest.main()
