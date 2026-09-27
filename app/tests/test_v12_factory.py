import tempfile, unittest
from pfai.data_factory import DataFactory
from pfai.training_factory import TrainingFactory

class TestV12(unittest.TestCase):
    def test_clean_dedup(self):
        f=DataFactory(); rows=[{"instruction":" hello ","response":" world "},{"instruction":"hello","response":"world"},{"instruction":"x","response":"y"}]
        self.assertEqual(len(f.clean(rows)),1)
    def test_split_manifest(self):
        f=DataFactory(); rows=[{"instruction":f"question {i}","response":f"answer {i}"} for i in range(10)]
        s=f.split(f.clean(rows)); m=f.manifest("demo","1",s)
        self.assertEqual(m.total,10); self.assertEqual(m.train+m.validation+m.test,10); self.assertEqual(len(m.sha256),64)
    def test_prepare_and_run(self):
        with tempfile.TemporaryDirectory() as d:
            t=TrainingFactory(workdir=d); rows=[{"instruction":f"question {i}","response":f"answer {i}"} for i in range(6)]
            m=t.prepare("demo","1",rows); run=t.start_run("demo","1")
            self.assertEqual(m.total,6); self.assertEqual(run["status"],"created")

if __name__=='__main__': unittest.main()
