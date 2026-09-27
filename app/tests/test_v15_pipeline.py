import tempfile, unittest
from pfai.continuous_pipeline import ContinuousTrainingPipeline, PipelineConfig
from pfai.data_factory import Example

class TestV15Pipeline(unittest.TestCase):
    def rows(self):
        return [Example(f"question {i}", f"answer {i}", source="test") for i in range(12)]

    def test_cycle_trains_evaluates_and_registers_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p=ContinuousTrainingPipeline(d, PipelineConfig(dataset_id="ds", dry_run=True, minimum_score=.5))
            r=p.run_cycle(self.rows(), {"knowledge":lambda:.8,"reasoning":lambda:.7})
            self.assertTrue(r["evaluated"])
            self.assertTrue(r["accepted"])
            self.assertIsNotNone(r["registered"])
            self.assertIsNone(p.registry.active())

    def test_regression_is_not_registered(self):
        with tempfile.TemporaryDirectory() as d:
            p=ContinuousTrainingPipeline(d, PipelineConfig(dry_run=True, minimum_score=.5, require_improvement=True))
            r=p.run_cycle(self.rows(), {"knowledge":lambda:.8}, baseline_score=.8)
            self.assertFalse(r["accepted"])
            self.assertIsNone(r["registered"])

    def test_auto_promote_uses_canary(self):
        with tempfile.TemporaryDirectory() as d:
            p=ContinuousTrainingPipeline(d, PipelineConfig(dry_run=True, minimum_score=.5, auto_promote=True))
            r=p.run_cycle(self.rows(), {"knowledge":lambda:.9})
            self.assertTrue(r["accepted"])
            self.assertIsNotNone(p.registry.active())
            self.assertEqual(p.registry.active()["version"], r["registered"]["version"])

if __name__=='__main__': unittest.main()
