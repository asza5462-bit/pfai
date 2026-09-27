import os, tempfile, unittest, warnings, sqlite3
from pfai.global_job_scheduler import GlobalJobScheduler, Job
from pfai.distributed_research_fabric import DistributedResearchFabric, FabricJob
from pfai.vector_store import VectorStore
from pfai.vector_memory import SemanticMemory

class Fabric:
    def __init__(self):
        self.servers={"gpu-a":{"authorized":True,"status":"HEALTHY","load":.1,"resources":{"cpu_free":16,"ram_free_gb":64,"gpu_free":1,"vram_free_gb":24}},
                      "gpu-b":{"authorized":True,"status":"HEALTHY","load":.2,"resources":{"cpu_free":16,"ram_free_gb":64,"gpu_free":1,"vram_free_gb":24}}}

class E:
    def embed(self,s): return [1.0,0.0]

class TestV65(unittest.TestCase):
    def test_scheduler_recovers_running_job_as_pending(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'scheduler.json'); f=Fabric()
            s=GlobalJobScheduler(f,state_path=path); s.submit(Job('j',required_gpu=1)); s.schedule('j'); s.checkpoint('j','ckpt-1')
            s2=GlobalJobScheduler(f,state_path=path)
            self.assertEqual(s2.jobs['j'].status,'PENDING'); self.assertEqual(s2.jobs['j'].checkpoint,'ckpt-1')
            self.assertIsNone(s2.jobs['j'].worker_id)

    def test_fabric_recovers_running_job(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'fabric.json'); f=Fabric(); s=GlobalJobScheduler(f)
            r=DistributedResearchFabric(s,state_path=path); r.submit(FabricJob('r','research')); r.jobs['r'].status='RUNNING'; r.jobs['r'].worker_id='gpu-a'; r._save()
            r2=DistributedResearchFabric(s,state_path=path)
            self.assertEqual(r2.jobs['r'].status,'PENDING'); self.assertIsNone(r2.jobs['r'].worker_id)

    def test_sqlite_wrappers_close_without_resource_warning(self):
        with tempfile.TemporaryDirectory() as d, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ResourceWarning)
            vs=VectorStore(os.path.join(d,'v.db'),E()); vs.add('hello'); vs.close()
            sm=SemanticMemory(os.path.join(d,'s.db')); sm.add('hello'); sm.close()
            self.assertFalse([w for w in caught if issubclass(w.category, ResourceWarning)])

if __name__=='__main__': unittest.main()
