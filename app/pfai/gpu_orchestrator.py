from dataclasses import dataclass, asdict
from pathlib import Path
import json, time, uuid

STATES = {'queued','running','paused','completed','failed','cancelled'}

@dataclass
class GPUResource:
    id: str
    total_gpus: int = 0
    free_gpus: int = 0
    memory_gb: float = 0.0
    labels: tuple = ()
    healthy: bool = True

@dataclass
class TrainingJob:
    job_id: str
    kind: str
    priority: int
    gpu_required: int
    memory_gb: float
    payload: dict
    state: str = 'queued'
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    assigned_resource: str = ''
    last_error: str = ''

class GPUOrchestrator:
    """Persistent scheduler for long-running training/experiment jobs.

    It schedules work but does not pretend to provide GPU hardware. A worker/runner
    must call start/finish/fail; this keeps scheduling separate from execution.
    """
    def __init__(self, state_path='artifacts/orchestrator/state.json', max_concurrent=1):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max(1, int(max_concurrent))
        self.resources = {}
        self.jobs = {}
        self._load()

    def _load(self):
        if not self.state_path.exists(): return
        data=json.loads(self.state_path.read_text(encoding='utf-8'))
        self.resources={k:GPUResource(**v) for k,v in data.get('resources',{}).items()}
        self.jobs={k:TrainingJob(**v) for k,v in data.get('jobs',{}).items()}

    def _save(self):
        data={'resources':{k:asdict(v) for k,v in self.resources.items()},
              'jobs':{k:asdict(v) for k,v in self.jobs.items()},
              'saved_at':time.time()}
        self.state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')

    def register_resource(self, resource_id, total_gpus=0, memory_gb=0.0, labels=()):
        r=GPUResource(resource_id,int(total_gpus),int(total_gpus),float(memory_gb),tuple(labels),True)
        self.resources[resource_id]=r; self._save(); return asdict(r)

    def set_health(self, resource_id, healthy):
        self.resources[resource_id].healthy=bool(healthy); self._save()

    def submit(self, kind, priority=50, gpu_required=0, memory_gb=0.0, payload=None, max_attempts=3, job_id=None):
        jid=job_id or uuid.uuid4().hex
        if jid in self.jobs: raise ValueError('job_id already exists')
        job=TrainingJob(jid,kind,int(priority),int(gpu_required),float(memory_gb),payload or {},
                        max_attempts=max(1,int(max_attempts)),created_at=time.time())
        self.jobs[jid]=job; self._save(); return asdict(job)

    def _active(self): return [j for j in self.jobs.values() if j.state=='running']

    def dispatch(self):
        slots=max(0, self.max_concurrent-len(self._active()))
        if not slots: return []
        queued=sorted((j for j in self.jobs.values() if j.state=='queued'), key=lambda j:(-j.priority,j.created_at))
        started=[]
        for job in queued:
            if not slots: break
            res=self._find_resource(job)
            if res is None: continue
            res.free_gpus -= job.gpu_required
            job.state='running'; job.started_at=time.time(); job.assigned_resource=res.id
            job.attempts += 1; started.append(asdict(job)); slots -= 1
        self._save(); return started

    def _find_resource(self, job):
        for r in self.resources.values():
            if not r.healthy: continue
            if r.free_gpus >= job.gpu_required and r.memory_gb >= job.memory_gb:
                return r
        return None

    def finish(self, job_id):
        job=self.jobs[job_id]
        if job.state!='running': raise ValueError('job is not running')
        self._release(job); job.state='completed'; job.finished_at=time.time(); self._save(); return asdict(job)

    def fail(self, job_id, error, retry=True):
        job=self.jobs[job_id]
        if job.state!='running': raise ValueError('job is not running')
        self._release(job); job.last_error=str(error); job.finished_at=time.time()
        if retry and job.attempts < job.max_attempts:
            job.state='queued'; job.assigned_resource=''; job.finished_at=0.0
        else: job.state='failed'
        self._save(); return asdict(job)

    def pause(self, job_id):
        job=self.jobs[job_id]
        if job.state=='running': self._release(job)
        if job.state not in ('queued','running'): raise ValueError('job cannot be paused')
        job.state='paused'; job.assigned_resource=''; self._save(); return asdict(job)

    def resume(self, job_id):
        job=self.jobs[job_id]
        if job.state!='paused': raise ValueError('job is not paused')
        job.state='queued'; self._save(); return asdict(job)

    def cancel(self, job_id):
        job=self.jobs[job_id]
        if job.state=='running': self._release(job)
        if job.state in ('completed','failed','cancelled'): raise ValueError('job is terminal')
        job.state='cancelled'; job.finished_at=time.time(); job.assigned_resource=''; self._save(); return asdict(job)

    def _release(self, job):
        if job.assigned_resource and job.assigned_resource in self.resources:
            self.resources[job.assigned_resource].free_gpus += job.gpu_required
        job.assigned_resource=''

    def recover(self):
        """After process restart, requeue jobs that were running so no job is lost."""
        recovered=[]
        for job in self.jobs.values():
            if job.state=='running':
                self._release(job); job.state='queued'; recovered.append(job.job_id)
        self._save(); return recovered

    def status(self):
        counts={s:0 for s in STATES}
        for j in self.jobs.values(): counts[j.state]=counts.get(j.state,0)+1
        return {'jobs':counts,'resources':{k:asdict(v) for k,v in self.resources.items()},'active':len(self._active())}
