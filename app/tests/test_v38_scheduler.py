import tempfile, unittest
from pathlib import Path
from pfai.project_scheduler import ProjectScheduler, ProjectTask

class TestV38(unittest.TestCase):
    def test_dependency_and_priority(self):
        with tempfile.TemporaryDirectory() as d:
            s=ProjectScheduler(str(Path(d)/'s.json'))
            s.create_project('demo',[ProjectTask('a','research',20),ProjectTask('b','code',80,['a']),ProjectTask('c','eval',70,['b'])])
            order=[]
            worker=lambda t: order.append(t.task_id) or {'ok':True}
            s.dispatch(worker); self.assertEqual(order,['a'])
            s.dispatch(worker); self.assertEqual(order,['a','b'])
            s.dispatch(worker); self.assertEqual(order,['a','b','c'])
            self.assertEqual(s.progress()['progress'],1.0)

    def test_recovery_and_retry(self):
        with tempfile.TemporaryDirectory() as d:
            s=ProjectScheduler(str(Path(d)/'s.json'))
            s.create_project('x',[ProjectTask('a','x',max_retries=1)])
            s.dispatch(lambda t: (_ for _ in ()).throw(RuntimeError('boom')))
            self.assertEqual(s.tasks['a'].state,'pending')
            s.dispatch(lambda t: (_ for _ in ()).throw(RuntimeError('boom')))
            self.assertEqual(s.tasks['a'].state,'failed')
            s.tasks['a'].state='running'; s._save(); self.assertEqual(s.recover(),['a']); self.assertEqual(s.tasks['a'].state,'pending')

    def test_cycle_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            s=ProjectScheduler(str(Path(d)/'s.json'))
            s.create_project('x',[ProjectTask('a','a',dependencies=['b']),ProjectTask('b','b',dependencies=['a'])])
            with self.assertRaises(ValueError): s.dispatch(lambda t:{})

if __name__=='__main__': unittest.main()
