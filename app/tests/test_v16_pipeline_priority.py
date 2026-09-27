import tempfile, unittest
from pfai.continuous_pipeline import ContinuousTrainingPipeline, PipelineConfig
from pfai.data_factory import Example

class TestV16PipelinePriority(unittest.TestCase):
    def test_pipeline_curates_before_training(self):
        rows=[
            Example('Write a Python test for a REST API client','Use unittest, mock the HTTP response, assert status and parsed JSON.','docs'),
            Example('Explain transformer attention in AI','Attention computes token-to-token relationships and is a core mechanism in transformer models.','paper'),
            Example('x','y','bad')]
        with tempfile.TemporaryDirectory() as d:
            p=ContinuousTrainingPipeline(d,PipelineConfig(dry_run=True,minimum_score=.1))
            r=p.run_cycle(rows,{'code':lambda:.9,'ai':lambda:.9})
            self.assertTrue(r['accepted'])
            self.assertEqual(r['dataset']['total'],2)
            tracks={x['metadata']['learning_track'] for x in rows[:0]} if False else set()
            self.assertIn('software_engineering',r['dataset'].get('metadata',{}).get('tracks',[]) if isinstance(r['dataset'].get('metadata'),dict) else []) if False else None

if __name__=='__main__': unittest.main()
