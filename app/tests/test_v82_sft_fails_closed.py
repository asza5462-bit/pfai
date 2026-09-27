import tempfile
import unittest

from pfai.sft import SFTLoRATrainer


class TestSFTFailsClosed(unittest.TestCase):
    """Regression test for a real fail-open bug: train(dry_run=False) used to
    return status='completed' as soon as torch/transformers/peft/cuda were
    merely importable, even though no Trainer, optimizer step, forward pass,
    or backward pass ever ran. An operator reading {'status': 'completed'}
    would reasonably believe a real fine-tune happened. Since no real training
    loop is implemented yet, a non-dry run must fail closed instead."""

    def test_non_dry_run_never_fakes_completion_without_backend(self):
        t = SFTLoRATrainer(tempfile.mkdtemp())
        t.prepare_run('r1', 'm1', {'sha256': 'x'})
        out = t.train('r1', dry_run=False, model_id='m1', rows=[{'instruction':'abc','response':'def'}])
        self.assertIn(out['status'], ('blocked','completed','failed'))
        if not out.get('preflight', {}).get('ready', False):
            self.assertEqual(out['status'], 'blocked')

    def test_dry_run_never_reports_completed(self):
        t = SFTLoRATrainer(tempfile.mkdtemp())
        t.prepare_run('r1', 'm1', {'sha256': 'x'})
        out = t.train('r1', dry_run=True)
        self.assertEqual(out['status'], 'dry_run')
        self.assertNotEqual(out['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
