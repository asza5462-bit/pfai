import tempfile, unittest
from pathlib import Path
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator
from pfai.continuous_training import ContinuousConfig
from pfai.smart_continuous import SmartContinuousConfig


class TestContinuousLearningOrchestrator(unittest.TestCase):
    def test_ingest_curates_and_allocates_by_curriculum(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d, smart_config=SmartContinuousConfig(enabled=False))
            rows = [
                {'instruction': 'Write a Python function to reverse a list', 'response': 'def reverse(x): return x[::-1]', 'source': 'unit-test'},
                {'instruction': 'hi', 'response': '', 'source': 'unit-test'},  # empty response, rejected by quality gate
                {'instruction': 'Explain fine-tuning a transformer model', 'response': 'Fine-tuning adapts pretrained weights on a smaller labeled dataset.', 'source': 'unit-test'},
            ]
            result = orch.register_batch(rows)
            self.assertEqual(result['submitted'], 3)
            self.assertEqual(result['accepted'], 2)
            self.assertEqual(result['rejected'], 1)
            self.assertIn('software_engineering', result['by_track'])
            self.assertIn('ai_engineering', result['by_track'])

    def test_run_cycle_fails_closed_without_data(self):
        with tempfile.TemporaryDirectory() as d:
            # Smart seeding disabled — empty queue must fail closed.
            orch = ContinuousLearningOrchestrator(
                root=d, smart_config=SmartContinuousConfig(enabled=False)
            )
            result = orch.run_cycle('v1', score=0.9)
            self.assertFalse(result['evaluated'])

    def test_run_cycle_requires_human_approval_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(
                root=d, smart_config=SmartContinuousConfig(enabled=False)
            )
            orch.register_batch([
                {'instruction': 'Debug this SQL query for a slow join', 'response': 'Add an index on the join column and re-run EXPLAIN.', 'source': 'unit-test'},
            ])
            result = orch.run_cycle('v1', score=0.9)
            self.assertTrue(result['evaluated'])
            self.assertEqual(result['status'], 'pending_approval')
            self.assertIsNone(orch.loop.active())
            self.assertTrue(orch.approve('v1'))
            self.assertTrue(orch.promote('v1'))
            self.assertEqual(orch.loop.active()['version'], 'v1')

    def test_model_cannot_bypass_approval_gate(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(
                root=d, smart_config=SmartContinuousConfig(enabled=False)
            )
            orch.register_batch([
                {'instruction': 'Explain how RLHF differs from supervised fine-tuning', 'response': 'RLHF optimizes a policy against a learned reward model instead of fixed labels.', 'source': 'unit-test'},
            ])
            result = orch.run_cycle('v2', score=0.95)
            # promote must fail until an external approve() call happens
            self.assertFalse(orch.promote('v2'))
            self.assertIsNone(orch.loop.active())

    def test_service_lifecycle_delegates_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d, continuous_config=ContinuousConfig(interval_seconds=1))
            self.assertEqual(orch.start()['status'], 'running')
            self.assertEqual(orch.pause()['status'], 'paused')
            self.assertEqual(orch.resume()['status'], 'running')
            self.assertEqual(orch.stop('test done')['status'], 'stopped')

    def test_status_reports_consistent_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            orch.register_batch([
                {'instruction': 'What causes index bloat in Postgres?', 'response': 'Frequent updates/deletes leave dead tuples until vacuum reclaims them.', 'source': 'unit-test'},
            ])
            snap = orch.status()
            self.assertEqual(snap['pending_examples'], 1)
            self.assertEqual(len(snap['curriculum']), 4)
            self.assertIsNone(snap['active_candidate'])


if __name__ == '__main__':
    unittest.main()
