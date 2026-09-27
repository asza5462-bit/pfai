import os, tempfile, unittest
from pfai.global_job_scheduler import GlobalJobScheduler
from pfai.distributed_research_fabric import DistributedResearchFabric, FabricJob
from pfai.model_upgrade_gate import ModelUpgradeGate

class Fabric:
    def __init__(self):
        self.servers={"gpu-a":{"authorized":True,"status":"HEALTHY","load":.1,"resources":{"cpu_free":16,"ram_free_gb":64,"gpu_free":1,"vram_free_gb":24}}}

class TestV64(unittest.TestCase):
    def test_training_dispatches_to_authorized_resource(self):
        f=DistributedResearchFabric(GlobalJobScheduler(Fabric()))
        j=f.submit(FabricJob("t","training",required_gpu=1,required_vram_gb=16))
        self.assertEqual(f.dispatch("t").worker_id,"gpu-a")

    def test_research_completion(self):
        f=DistributedResearchFabric(GlobalJobScheduler(Fabric()))
        f.submit(FabricJob("r","research")); f.dispatch("r"); f.complete_research("r",{"answer":"ok"})
        self.assertEqual(f.jobs["r"].status,"COMPLETED")

    def test_promotion_requires_gate_and_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            artifact=os.path.join(d,"candidate.bin");
            with open(artifact,"wb") as fh: fh.write(b"candidate")
            gate=ModelUpgradeGate(os.path.join(d,"audit"),min_score=.8)
            f=DistributedResearchFabric(GlobalJobScheduler(Fabric()),gate)
            f.submit(FabricJob("t","training",candidate_version="v64",base_version="v63")); f.dispatch("t")
            f.record_evaluation("t",artifact,.9,True,True,True)
            report=f.request_promotion("t")
            self.assertEqual(report["decision"],"WAITING_HUMAN_APPROVAL")
            report=f.request_promotion("t",approver="external-operator")
            self.assertEqual(report["decision"],"PASS")

    def test_failed_security_cannot_promote(self):
        with tempfile.TemporaryDirectory() as d:
            artifact=os.path.join(d,"candidate.bin");
            with open(artifact,"wb") as fh: fh.write(b"candidate")
            gate=ModelUpgradeGate(os.path.join(d,"audit"),min_score=.0)
            f=DistributedResearchFabric(GlobalJobScheduler(Fabric()),gate)
            f.submit(FabricJob("t","training",candidate_version="v64",base_version="v63")); f.dispatch("t")
            f.record_evaluation("t",artifact,.9,False,True,True)
            with self.assertRaises(ValueError): f.request_promotion("t",approver="external")

if __name__=='__main__': unittest.main()
