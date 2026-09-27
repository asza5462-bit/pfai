"""Policy-aware global PFAI job scheduler with persistent recovery state."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from pathlib import Path
import json, os, tempfile

def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass
class Job:
    job_id: str
    priority: int = 50
    dependencies: List[str] = field(default_factory=list)
    required_cpu: float = 0.0
    required_ram_gb: float = 0.0
    required_gpu: int = 0
    required_vram_gb: float = 0.0
    deadline: Optional[str] = None
    status: str = "PENDING"
    worker_id: Optional[str] = None
    checkpoint: Optional[str] = None
    attempts: int = 0

class GlobalJobScheduler:
    """Schedules only onto workers already authorized by the Global Fabric."""
    def __init__(self, fabric, resource_manager=None, state_path=None):
        self.fabric = fabric; self.resource_manager = resource_manager
        self.state_path = Path(state_path) if state_path else None
        self.jobs: Dict[str, Job] = {}; self.events: List[dict] = []; self.failed_workers: Set[str] = set()
        self._load()

    def _event(self, kind, job_id, **extra):
        self.events.append({"time": _now(), "kind": kind, "job_id": job_id, **extra}); self._save()

    def _save(self):
        if not self.state_path: return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload={"version":1,"jobs":{k:asdict(v) for k,v in self.jobs.items()},"events":self.events[-2000:],"failed_workers":sorted(self.failed_workers)}
        fd,tmp=tempfile.mkstemp(prefix='.scheduler-',suffix='.json',dir=str(self.state_path.parent))
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.state_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _load(self):
        if not self.state_path or not self.state_path.exists(): return
        try:
            data=json.loads(self.state_path.read_text(encoding='utf-8'))
            self.jobs={k:Job(**v) for k,v in data.get('jobs',{}).items()}
            self.events=list(data.get('events',[])); self.failed_workers=set(data.get('failed_workers',[]))
            for j in self.jobs.values():
                if j.status == 'RUNNING':
                    j.status='PENDING'; j.worker_id=None
            self._event('RECOVERED','__scheduler__',requeued=sum(1 for j in self.jobs.values() if j.status=='PENDING'))
        except (OSError, ValueError, TypeError) as exc:
            self.jobs={}; self.events=[{"time":_now(),"kind":"RECOVERY_FAILED","job_id":"__scheduler__","reason":str(exc)}]

    def submit(self, job: Job):
        if job.job_id in self.jobs: raise ValueError("duplicate job_id")
        self._validate_dependencies(job); self.jobs[job.job_id]=job; self._event("SUBMITTED",job.job_id,priority=job.priority); return job

    def _validate_dependencies(self, job):
        graph={k:set(v.dependencies) for k,v in self.jobs.items()}; graph[job.job_id]=set(job.dependencies)
        if job.job_id in graph[job.job_id]: raise ValueError("dependency cycle")
        visiting,visited=set(),set()
        def dfs(n):
            if n in visiting: return True
            if n in visited or n not in graph: return False
            visiting.add(n)
            if any(dfs(x) for x in graph[n]): return True
            visiting.remove(n); visited.add(n); return False
        if dfs(job.job_id): raise ValueError("dependency cycle")
        missing=[d for d in job.dependencies if d not in self.jobs]
        if missing: raise ValueError(f"missing dependencies: {missing}")

    def ready(self, job_id):
        j=self.jobs[job_id]; return j.status=='PENDING' and all(self.jobs[d].status=='COMPLETED' for d in j.dependencies)

    def _workers(self):
        out=[]
        for sid,info in getattr(self.fabric,'servers',{}).items():
            if info.get('authorized') is not True or sid in self.failed_workers: continue
            if info.get('status','UNKNOWN') not in ('HEALTHY','READY'): continue
            out.append((sid,info))
        return out

    @staticmethod
    def _fits(job,info):
        r=info.get('resources',info)
        return (float(r.get('cpu_free',r.get('cpu',0)))>=job.required_cpu and float(r.get('ram_free_gb',r.get('ram_gb',0)))>=job.required_ram_gb and int(r.get('gpu_free',r.get('gpu',0)))>=job.required_gpu and float(r.get('vram_free_gb',r.get('vram_gb',0)))>=job.required_vram_gb)

    def schedule(self,job_id=None):
        candidates=[self.jobs[job_id]] if job_id else list(self.jobs.values()); candidates=[j for j in candidates if self.ready(j.job_id)]
        candidates.sort(key=lambda j:(-j.priority,j.deadline or '9999-12-31T23:59:59Z')); scheduled=[]
        for job in candidates:
            workers=[(sid,info) for sid,info in self._workers() if self._fits(job,info)]
            if not workers: self._event('WAITING_FOR_RESOURCE',job.job_id); continue
            sid,info=min(workers,key=lambda x:float(x[1].get('load',0))); job.worker_id=sid; job.status='RUNNING'; job.attempts+=1
            self._event('ASSIGNED',job.job_id,worker_id=sid,attempt=job.attempts); scheduled.append(job)
        return scheduled

    def checkpoint(self,job_id,checkpoint_id):
        j=self.jobs[job_id]; j.checkpoint=checkpoint_id; self._event('CHECKPOINT',job_id,checkpoint=checkpoint_id)

    def worker_failed(self,worker_id):
        self.failed_workers.add(worker_id); affected=[]
        for j in self.jobs.values():
            if j.worker_id==worker_id and j.status=='RUNNING': j.status='PENDING'; j.worker_id=None; affected.append(j.job_id); self._event('WORKER_FAILED',j.job_id,previous_worker=worker_id,checkpoint=j.checkpoint)
        return self.schedule() if affected else []

    def complete(self,job_id):
        j=self.jobs[job_id]; j.status='COMPLETED'; self._event('COMPLETED',job_id)

    def fail(self,job_id,reason='unknown'):
        j=self.jobs[job_id]; j.status='FAILED'; self._event('FAILED',job_id,reason=reason)

    def snapshot(self): return {k:vars(v).copy() for k,v in self.jobs.items()}
