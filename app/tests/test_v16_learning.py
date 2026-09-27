import tempfile, unittest
from pathlib import Path
from pfai.learning_curriculum import LearningCurriculum
from pfai.data_acquisition import DataAcquisitionEngine

class TestV16Learning(unittest.TestCase):
    def test_curriculum_prioritizes_code_and_ai(self):
        c=LearningCurriculum(); a=c.allocate(100)
        self.assertEqual(a['software_engineering'],45); self.assertEqual(a['ai_engineering'],35)
        self.assertGreater(a['software_engineering'],a['general_knowledge'])

    def test_curation_filters_duplicates_and_low_quality(self):
        e=DataAcquisitionEngine(LearningCurriculum())
        rows=e.curate([
            {'instruction':'Write a Python unit test for an API client','response':'Create a test using unittest with assertions and a mocked HTTP response.','source':'docs'},
            {'instruction':'Write a Python unit test for an API client','response':'Create a test using unittest with assertions and a mocked HTTP response.','source':'docs'},
            {'instruction':'x','response':'y'},
        ])
        self.assertEqual(len(rows),1); self.assertEqual(rows[0].track,'software_engineering')

    def test_export(self):
        e=DataAcquisitionEngine(LearningCurriculum())
        rows=e.curate([{'instruction':'Explain transformers in AI systems','response':'Transformers use attention to model relationships among tokens and support efficient parallel training.','source':'book'}])
        with tempfile.TemporaryDirectory() as d:
            r=e.export_jsonl(rows,Path(d)/'learn.jsonl'); self.assertEqual(r['total'],1)
            self.assertTrue((Path(d)/'learn.jsonl').exists())

if __name__=='__main__': unittest.main()
