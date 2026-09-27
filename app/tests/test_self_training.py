import json, tempfile, unittest
from pathlib import Path
from pfai.self_training import SelfTrainingEngine

class FakeTeacher:
    def __init__(self): self.calls=0
    def generate(self, prompt):
        self.calls += 1
        if 'Evaluate this training example' in prompt:
            return json.dumps({'score':0.95,'reason':'correct'})
        return json.dumps({'instruction':'Explain why deterministic tests matter','response':'They make regressions reproducible and failures diagnosable.'})

class TestSelfTraining(unittest.TestCase):
    def test_generates_and_judges_examples(self):
        with tempfile.TemporaryDirectory() as d:
            t=FakeTeacher(); e=SelfTrainingEngine(t,d,batch_size=1,min_teacher_score=.8)
            out=e.generate_batch(['software_engineering','ai_engineering'])
            self.assertEqual(out['accepted'],2)
            self.assertEqual(t.calls,4)
            self.assertEqual(len(Path(d,'accepted.jsonl').read_text().splitlines()),2)

    def test_missing_teacher_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            out=SelfTrainingEngine(None,d).generate_batch(['software_engineering'])
            self.assertEqual(out['accepted'],0)

if __name__=='__main__': unittest.main()
