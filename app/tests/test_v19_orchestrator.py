import tempfile, unittest
from pathlib import Path
from pfai.gpu_orchestrator import GPUOrchestrator

class TestV19(unittest.TestCase):
    def make(self):
        self.t=tempfile.TemporaryDirectory()
        return GPUOrchestrator(Path(self.t.name)/'state.json', max_concurrent=2)
    def tearDown(self):
        if hasattr(self,'t'): self.t.cleanup()
    def test_priority_and_resources(self):
        o=self.make(); o.register_resource('gpu0',2,24)
        low=o.submit('general',20,1); high=o.submit('code',90,1)
        started=o.dispatch(); self.assertEqual(started[0]['job_id'],high['job_id'])
        self.assertEqual(o.resources['gpu0'].free_gpus,0)
    def test_retry_then_fail(self):
        o=self.make(); o.register_resource('gpu0',1,16)
        j=o.submit('train',50,1,max_attempts=2); o.dispatch()
        o.fail(j['job_id'],'boom'); self.assertEqual(o.jobs[j['job_id']].state,'queued')
        o.dispatch(); o.fail(j['job_id'],'boom2'); self.assertEqual(o.jobs[j['job_id']].state,'failed')
    def test_persistence_and_recovery(self):
        o=self.make(); o.register_resource('gpu0',1,16); j=o.submit('ai',80,1); o.dispatch()
        o2=GPUOrchestrator(o.state_path,max_concurrent=1); self.assertEqual(o2.jobs[j['job_id']].state,'running')
        self.assertEqual(o2.recover(),[j['job_id']]); self.assertEqual(o2.jobs[j['job_id']].state,'queued')
    def test_pause_resume_cancel(self):
        o=self.make(); o.register_resource('gpu0',1,16); j=o.submit('x'); o.pause(j['job_id']); o.resume(j['job_id']); o.cancel(j['job_id']); self.assertEqual(o.jobs[j['job_id']].state,'cancelled')

if __name__=='__main__': unittest.main()
