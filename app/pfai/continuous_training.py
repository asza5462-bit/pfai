from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
import json, time, traceback

@dataclass
class ContinuousConfig:
    interval_seconds: int = 3600
    max_consecutive_failures: int = 3
    checkpoint_every_cycle: bool = True
    auto_promote: bool = False
    require_evaluation: bool = True
    heartbeat_seconds: int = 30

class ContinuousTrainingService:
    """24/7 training supervisor. It schedules bounded cycles; it does not bypass lifecycle gates."""
    def __init__(self, root='data/continuous_training', config: Optional[ContinuousConfig]=None):
        self.root=Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.config=config or ContinuousConfig()
        self.state_path=self.root/'state.json'
        self.events_path=self.root/'events.jsonl'
        self._state=self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding='utf-8'))
        return {'status':'stopped','cycles':0,'successes':0,'failures':0,'consecutive_failures':0,
                'last_cycle':None,'last_success':None,'last_error':None,'started_at':None,'heartbeat':None}

    def _save(self):
        self.state_path.write_text(json.dumps(self._state,ensure_ascii=False,indent=2),encoding='utf-8')

    def _event(self, kind, payload=None):
        e={'time':datetime.now(timezone.utc).isoformat(),'event':kind,'payload':payload or {}}
        with self.events_path.open('a',encoding='utf-8') as f: f.write(json.dumps(e,ensure_ascii=False)+'\n')

    def status(self): return dict(self._state)

    def start(self):
        self._state['status']='running'; self._state['started_at']=datetime.now(timezone.utc).isoformat(); self._save(); self._event('started')
        return self.status()

    def stop(self, reason='operator'):
        self._state['status']='stopped'; self._state['last_error']=reason; self._save(); self._event('stopped',{'reason':reason}); return self.status()

    def pause(self):
        self._state['status']='paused'; self._save(); self._event('paused'); return self.status()

    def resume(self):
        self._state['status']='running'; self._save(); self._event('resumed'); return self.status()

    def heartbeat(self):
        self._state['heartbeat']=datetime.now(timezone.utc).isoformat(); self._save(); return self._state['heartbeat']

    def run_cycle(self, cycle_fn: Callable[[], dict]):
        if self._state['status'] not in ('running','cycle'):
            return {'status':'skipped','reason':self._state['status']}
        self._state['status']='cycle'; self._state['cycles'] += 1; self._state['last_cycle']=datetime.now(timezone.utc).isoformat(); self._save()
        self._event('cycle_started',{'cycle':self._state['cycles']})
        try:
            result=cycle_fn() or {}
            if self.config.require_evaluation and result.get('evaluated') is not True:
                raise RuntimeError('cycle rejected: evaluation gate was not satisfied')
            self._state['successes'] += 1; self._state['consecutive_failures']=0; self._state['last_success']=datetime.now(timezone.utc).isoformat(); self._state['last_error']=None; self._state['status']='running'
            self._save(); self._event('cycle_success',result); return {'status':'success',**result}
        except Exception as exc:
            self._state['failures'] += 1; self._state['consecutive_failures'] += 1; self._state['last_error']=str(exc)
            self._state['status']='stopped' if self._state['consecutive_failures'] >= self.config.max_consecutive_failures else 'running'
            self._save(); self._event('cycle_failed',{'error':str(exc),'traceback':traceback.format_exc()})
            return {'status':'failed','error':str(exc),'service_status':self._state['status']}

    def serve_forever(self, cycle_fn: Callable[[], dict], sleep_fn=time.sleep, max_cycles: Optional[int]=None):
        if self._state['status'] != 'running': self.start()
        ran=0
        while self._state['status']=='running' and (max_cycles is None or ran < max_cycles):
            self.heartbeat(); self.run_cycle(cycle_fn); ran += 1
            if self._state['status']=='running' and (max_cycles is None or ran < max_cycles): sleep_fn(max(1,int(self.config.interval_seconds)))
        return self.status()
