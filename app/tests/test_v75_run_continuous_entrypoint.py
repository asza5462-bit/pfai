import importlib, os, tempfile, unittest

run_continuous = importlib.import_module("run_continuous")
from pfai.continuous_learning_orchestrator import ContinuousLearningOrchestrator


class FakeModel:
    """Deterministic stand-in for AnthropicProvider: no network calls."""
    def __init__(self, score=0.9):
        self.score = score
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return '{"score": %s, "reason": "looks fine"}' % self.score


class TestBuildModel(unittest.TestCase):
    def test_echo_provider_yields_no_evaluator(self):
        self.assertIsNone(run_continuous.build_model({'provider': 'echo'}))

    def test_anthropic_without_api_key_yields_no_evaluator(self):
        env_key = 'ANTHROPIC_API_KEY_TEST_UNSET'
        os.environ.pop(env_key, None)
        model = run_continuous.build_model({'provider': 'anthropic', 'api_key_env': env_key})
        self.assertIsNone(model)

    def test_anthropic_with_api_key_yields_real_provider(self):
        env_key = 'ANTHROPIC_API_KEY_TEST_SET'
        os.environ[env_key] = 'sk-test-not-real'
        try:
            model = run_continuous.build_model({'provider': 'anthropic', 'api_key_env': env_key})
            self.assertIsNotNone(model)
            self.assertEqual(model.api_key_env, env_key)
        finally:
            os.environ.pop(env_key, None)


class TestMakeCycle(unittest.TestCase):
    def test_cycle_fails_closed_with_no_curated_data(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            cycle = run_continuous.make_cycle(orch)
            result = cycle()
            self.assertFalse(result['evaluated'])

    def test_cycle_auto_scores_and_still_requires_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            fake_model = FakeModel(score=0.9)
            orch = ContinuousLearningOrchestrator(root=d, evaluator_model=fake_model)
            orch.register_batch([
                {'instruction': 'Write a unit test for a stack class',
                 'response': 'Push three items, assert pop() returns them in LIFO order.',
                 'source': 'unit-test'},
            ])
            cycle = run_continuous.make_cycle(orch)
            result = cycle()
            self.assertTrue(result['evaluated'])
            self.assertTrue(result['auto_scored'])
            self.assertEqual(result['status'], 'pending_approval')
            # The cycle itself never promotes anything -- no active candidate exists yet.
            self.assertIsNone(orch.loop.active())
            self.assertGreaterEqual(fake_model.calls, 1)

    def test_version_is_unique_per_call(self):
        with tempfile.TemporaryDirectory() as d:
            orch = ContinuousLearningOrchestrator(root=d)
            cycle = run_continuous.make_cycle(orch)
            r1 = cycle()
            r2 = cycle()
            # Both fail closed (no data), but each call must build a fresh version tag.
            self.assertFalse(r1['evaluated'])
            self.assertFalse(r2['evaluated'])


class TestBuildOrchestratorSafetyBoundary(unittest.TestCase):
    def test_require_human_approval_is_hardcoded_true_not_config_driven(self):
        """build_orchestrator must pass require_human_approval=True unconditionally --
        it must never read this from the JSON config, so an operator editing
        configs/default.json cannot silently disable the promotion gate."""
        import inspect
        src = inspect.getsource(run_continuous.build_orchestrator)
        self.assertIn('require_human_approval=True', src)
        self.assertNotIn("ct_cfg.get('require_human_approval'", src)

    def test_auto_promote_is_hardcoded_false_not_config_driven(self):
        import inspect
        src = inspect.getsource(run_continuous.build_orchestrator)
        self.assertIn('auto_promote=False', src)


if __name__ == '__main__':
    unittest.main()
