from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable
import json, time, uuid

STATES = {'pending','ready','running','blocked','succeeded','failed','cancelled'}

@dataclass
class ProjectTask:
    task_id: str
    name: str
    priority: int = 50
    dependencies: list[str] = field(default_factory=list)
    resource: str = 'cpu'
    max_retries: int = 1
    attempts: int = 0
    state: str = 'pending'
    last_error: str | None = None
    result: dict | None = None

class ProjectScheduler:
    """Persistent, dependency-aware scheduler for long-running PFAI projects.

    It plans and dispatches tasks but never grants permissions or bypasses policy.
    Worker execution is injected, making scheduling deterministic and testable.
    """
    def __init__(self, path: str = 'data/scheduler/state.json'):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, ProjectTask] = {}
        self.project_id = None
        self.status = 'idle'
        self.events: list[dict] = []
        self._load()

    def _save(self):
        payload = {'project_id': self.project_id, 'status': self.status,
                   'tasks': {k: asdict(v) for k,v in self.tasks.items()}, 'events': self.events[-500:]}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')

    def _load(self):
        if not self.path.exists(): return
        data=json.loads(self.path.read_text(encoding='utf-8'))
        self.project_id=data.get('project_id'); self.status=data.get('status','idle')
        self.tasks={k: ProjectTask(**v) for k,v in data.get('tasks',{}).items()}
        self.events=data.get('events',[])

    def _event(self, kind, task_id=None, **data):
        self.events.append({'ts':time.time(),'event':kind,'task_id':task_id,**data}); self._save()

    def create_project(self, name: str, tasks: list[ProjectTask]) -> str:
        if not name.strip(): raise ValueError('project name required')
        ids=[t.task_id for t in tasks]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate task id')
        known=set(ids)
        for t in tasks:
            if t.state not in STATES: raise ValueError('invalid task state')
            if any(d not in known for d in t.dependencies): raise ValueError(f'unknown dependency:{t.task_id}')
        self.project_id=f'{name}-{uuid.uuid4().hex[:8]}'
        self.tasks={t.task_id:t for t in tasks}; self.status='ready'; self._save()
        return self.project_id

    def ready_tasks(self):
        out=[]
        for t in self.tasks.values():
            if t.state not in {'pending','ready'}: continue
            deps=[self.tasks[d] for d in t.dependencies]
            if any(d.state in {'failed','cancelled'} and d.attempts >= d.max_retries for d in deps):
                t.state='blocked'; continue
            if all(d.state=='succeeded' for d in deps): t.state='ready'; out.append(t)
        out.sort(key=lambda x:(-x.priority,x.task_id)); self._save(); return out

    def detect_cycle(self):
        visiting=set(); visited=set()
        def dfs(n):
            if n in visiting: return True
            if n in visited: return False
            visiting.add(n)
            if any(d in self.tasks and dfs(d) for d in self.tasks[n].dependencies): return True
            visiting.remove(n); visited.add(n); return False
        return any(dfs(n) for n in self.tasks)

    def dispatch(self, worker: Callable[[ProjectTask], dict], max_tasks: int = 1):
        if max_tasks <= 0: raise ValueError('max_tasks must be positive')
        if self.detect_cycle(): raise ValueError('dependency cycle detected')
        dispatched=[]
        for task in self.ready_tasks()[:max_tasks]:
            task.state='running'; task.attempts += 1; self.status='running'; self._event('task_started',task.task_id,attempt=task.attempts)
            try:
                result=worker(task); task.result=result if isinstance(result,dict) else {'value':result}; task.last_error=None; task.state='succeeded'
                self._event('task_succeeded',task.task_id)
            except Exception as exc:
                task.last_error=f'{type(exc).__name__}: {exc}'
                task.state='pending' if task.attempts <= task.max_retries else 'failed'
                self._event('task_failed',task.task_id,error=task.last_error,retry=task.state=='pending')
            dispatched.append(task.task_id)
        if all(t.state in {'succeeded','cancelled'} for t in self.tasks.values()): self.status='completed'
        elif not dispatched and any(t.state=='running' for t in self.tasks.values()): self.status='running'
        elif not dispatched: self.status='waiting'
        self._save(); return dispatched

    def cancel(self, task_id: str):
        t=self.tasks[task_id]; t.state='cancelled'; self._event('task_cancelled',task_id)

    def recover(self):
        recovered=[]
        for t in self.tasks.values():
            if t.state=='running': t.state='pending'; recovered.append(t.task_id)
        self.status='ready' if recovered else self.status; self._save(); return recovered

    def progress(self):
        total=len(self.tasks); done=sum(t.state=='succeeded' for t in self.tasks.values())
        return {'project_id':self.project_id,'status':self.status,'total':total,'completed':done,'progress':0.0 if not total else done/total,
                'states':{s:sum(t.state==s for t in self.tasks.values()) for s in sorted(STATES)}}
