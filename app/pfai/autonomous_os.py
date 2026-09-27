from __future__ import annotations
from .control_plane import ControlPlane
from .project_scheduler import ProjectScheduler
from .resource_intelligence import ResourceManager

class PFAIAutonomousOS:
    """Unified orchestration layer for long-running PFAI work."""
    def __init__(self,control_path='data/control/state.json',scheduler_path='data/scheduler/state.json'):
        self.control=ControlPlane(control_path); self.scheduler=ProjectScheduler(scheduler_path); self.resources=ResourceManager()
    def status(self):
        return {'control':self.control.snapshot(),'project':self.scheduler.progress(),'resources':self.resources.detect().__dict__}
    def start(self,reason=''): return self.control.command('start',reason)
    def stop(self,reason=''): return self.control.command('stop',reason)
    def pause(self,reason=''): return self.control.command('pause',reason)
    def resume(self,reason=''): return self.control.command('resume',reason)
    def recover(self):
        self.control.command('recover','recovery requested'); recovered=self.scheduler.recover(); self.control.command('start','recovery complete'); return recovered
    def tick(self,worker,max_tasks=1):
        if not self.control.allows_work(): return []
        return self.scheduler.dispatch(worker,max_tasks=max_tasks)
