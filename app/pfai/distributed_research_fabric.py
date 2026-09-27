"""Policy-aware distributed training/research/evaluation orchestration.
Only schedules onto already-authorized workers; promotion remains externally approved.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
import json, os, tempfile


def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass
class FabricJob:
    job_id: str
    kind: str  # training, research, evaluation
    priority: int = 50
    required_gpu: int = 0
    required_vram_gb: float = 0.0
    required_cpu: float = 1.0
    required_ram_gb: float = 1.0
    dataset_hash: Optional[str] = None
    base_version: Optional[str] = None
    candidate_version: Optional[str] = None
    status: str = "PENDING"
    worker_id: Optional[str] = None
    artifact: Optional[str] = None
    benchmark_score: Optional[float] = None
    security_passed: Optional[bool] = None
    regression_passed: Optional[bool] = None
    provenance_ok: Optional[bool] = None
    created_at: str = ""

class DistributedResearchFabric:
    ALLOWED_KINDS = {"training", "research", "evaluation"}
    def __init__(self, scheduler, upgrade_gate=None, state_path=None):
        self.scheduler = scheduler
        self.upgrade_gate = upgrade_gate
        self.state_path = Path(state_path) if state_path else None
        self.jobs: Dict[str, FabricJob] = {}
        self.events: List[dict] = []
        self._load()

    def _save(self):
        if not self.state_path: return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload={"version":1,"jobs":{k:asdict(v) for k,v in self.jobs.items()},"events":self.events[-2000:]}
        fd,tmp=tempfile.mkstemp(prefix='.fabric-',suffix='.json',dir=str(self.state_path.parent))
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.state_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _load(self):
        if not self.state_path or not self.state_path.exists(): return
        try:
            data=json.loads(self.state_path.read_text(encoding='utf-8'))
            self.jobs={k:FabricJob(**v) for k,v in data.get('jobs',{}).items()}
            self.events=list(data.get('events',[]))
            for job in self.jobs.values():
                if job.status=='RUNNING':
                    job.status='PENDING'; job.worker_id=None
            self._event('RECOVERED','__fabric__',requeued=sum(1 for j in self.jobs.values() if j.status=='PENDING'))
        except (OSError, ValueError, TypeError) as exc:
            self.jobs={}; self.events=[{"time":_now(),"kind":"RECOVERY_FAILED","job_id":"__fabric__","reason":str(exc)}]


    def _event(self, kind, job_id, **extra):
        self.events.append({"time": _now(), "kind": kind, "job_id": job_id, **extra}); self._save()

    def submit(self, job: FabricJob):
        if job.kind not in self.ALLOWED_KINDS: raise ValueError("unsupported job kind")
        if job.job_id in self.jobs: raise ValueError("duplicate job_id")
        job.created_at = job.created_at or _now()
        self.jobs[job.job_id] = job
        self._event("SUBMITTED", job.job_id, job_kind=job.kind)
        return job

    def dispatch(self, job_id):
        job = self.jobs[job_id]
        if job.status != "PENDING": raise ValueError("job not pending")
        # Reuse v6.3 scheduler's authorization/resource policy.
        from .global_job_scheduler import Job
        sj = Job(job_id=job.job_id, priority=job.priority,
                 required_cpu=job.required_cpu, required_ram_gb=job.required_ram_gb,
                 required_gpu=job.required_gpu, required_vram_gb=job.required_vram_gb)
        self.scheduler.submit(sj)
        selected = self.scheduler.schedule(job_id)
        if not selected:
            self._event("WAITING", job_id); return None
        job.worker_id = selected[0].worker_id; job.status = "RUNNING"
        self._event("DISPATCHED", job_id, worker_id=job.worker_id)
        return job

    def complete_research(self, job_id, result: Dict[str, Any]):
        job = self.jobs[job_id]
        if job.kind != "research": raise ValueError("not a research job")
        job.status = "COMPLETED"; self._event("RESEARCH_COMPLETED", job_id)
        self.scheduler.complete(job_id)
        return result

    def record_evaluation(self, job_id, artifact, benchmark_score, security_passed,
                          regression_passed, provenance_ok=True):
        job = self.jobs[job_id]
        if job.kind not in {"evaluation", "training"}: raise ValueError("not an evaluation/training job")
        job.artifact = artifact; job.benchmark_score = float(benchmark_score)
        job.security_passed = bool(security_passed); job.regression_passed = bool(regression_passed)
        job.provenance_ok = bool(provenance_ok); job.status = "EVALUATED"
        self._event("EVALUATED", job_id, score=job.benchmark_score)
        self.scheduler.complete(job_id)
        return asdict(job)

    def request_promotion(self, job_id, approver=""):
        job = self.jobs[job_id]
        if job.kind != "training" or job.status != "EVALUATED": raise ValueError("training job is not evaluation-complete")
        if not self.upgrade_gate: raise RuntimeError("upgrade gate required")
        report = self.upgrade_gate.audit(job.candidate_version, job.artifact, job.base_version or "",
                                         job.benchmark_score or 0.0, job.security_passed is True,
                                         job.regression_passed is True, job.provenance_ok is True)
        self._event("PROMOTION_AUDIT", job_id, decision=report["decision"])
        if approver:
            report = self.upgrade_gate.approve_after_audit(job.candidate_version, job.artifact, approver)
            self._event("PROMOTION_APPROVED", job_id, approver=approver)
        return report

    def snapshot(self): return {k: asdict(v) for k,v in self.jobs.items()}
