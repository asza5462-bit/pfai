import tempfile,unittest
from pathlib import Path
from pfai.autonomous_os import PFAIAutonomousOS
from pfai.project_scheduler import ProjectTask

class TestV40(unittest.TestCase):
    def setUp(self): self.d=tempfile.TemporaryDirectory(); p=Path(self.d.name); self.os=PFAIAutonomousOS(str(p/'c.json'),str(p/'s.json'))
    def tearDown(self): self.d.cleanup()
    def test_control(self):
        self.assertFalse(self.os.control.allows_work()); self.os.start('test'); self.assertTrue(self.os.control.allows_work()); self.os.pause(); self.assertFalse(self.os.control.allows_work()); self.os.resume(); self.assertTrue(self.os.control.allows_work())
    def test_project_tick_and_status(self):
        self.os.scheduler.create_project('demo',[ProjectTask('a','A'),ProjectTask('b','B',dependencies=['a'])]); self.os.start()
        self.assertEqual(self.os.tick(lambda t:{'ok':True}),['a']); self.assertEqual(self.os.tick(lambda t:{'ok':True}),['b']); self.assertEqual(self.os.scheduler.status,'completed')
        self.assertEqual(self.os.status()['project']['completed'],2)
    def test_recovery(self):
        self.os.scheduler.create_project('demo',[ProjectTask('a','A')]); self.os.start(); self.os.scheduler.tasks['a'].state='running'; self.os.scheduler._save(); rec=self.os.recover(); self.assertEqual(rec,['a']); self.assertTrue(self.os.control.allows_work())
    def test_resource_detection(self):
        r=self.os.resources.detect(); self.assertGreaterEqual(r.cpu,1); self.assertGreaterEqual(r.disk_free_bytes,0)

if __name__=='__main__': unittest.main()
