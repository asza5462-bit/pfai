import tempfile, unittest
from pathlib import Path
from pfai.continuous_training import ContinuousTrainingService, ContinuousConfig
from pfai.evaluation_lab import EvaluationLab

class TestV14(unittest.TestCase):
    def test_24_7_service_cycle_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            s=ContinuousTrainingService(d, ContinuousConfig(interval_seconds=1, max_consecutive_failures=2))
            s.start()
            out=s.serve_forever(lambda:{'evaluated':True,'loss':0.1}, sleep_fn=lambda _:None, max_cycles=3)
            self.assertEqual(out['cycles'],3); self.assertEqual(out['successes'],3)
            self.assertTrue(Path(d,'state.json').exists()); self.assertTrue(Path(d,'events.jsonl').exists())
    def test_failure_circuit_breaker(self):
        with tempfile.TemporaryDirectory() as d:
            s=ContinuousTrainingService(d, ContinuousConfig(max_consecutive_failures=2))
            s.start(); s.serve_forever(lambda: (_ for _ in ()).throw(RuntimeError('x')), sleep_fn=lambda _:None)
            self.assertEqual(s.status()['status'],'stopped')
    def test_evaluation_gate(self):
        lab=EvaluationLab(0.8)
        r=lab.evaluate({'knowledge':lambda:0.9,'reasoning':lambda:0.7})
        self.assertFalse(r['passed']); self.assertEqual(len(r['results']),2)

if __name__=='__main__': unittest.main()
