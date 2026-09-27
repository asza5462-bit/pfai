from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json, time, uuid

COMMANDS={'start','stop','pause','resume','recover'}

@dataclass
class ControlState:
    mode:str='stopped'
    generation:int=0
    last_command:str|None=None
    updated_at:float=0.0
    reason:str|None=None

class ControlPlane:
    """External control boundary. Model output cannot mutate this state directly."""
    def __init__(self,path='data/control/state.json'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.state=ControlState(); self.events=[]; self._load()
    def _load(self):
        if self.path.exists():
            d=json.loads(self.path.read_text()); self.state=ControlState(**d.get('state',{})); self.events=d.get('events',[])
    def _save(self):
        self.path.write_text(json.dumps({'state':asdict(self.state),'events':self.events[-500:]},indent=2,sort_keys=True))
    def command(self,command,reason=''):
        if command not in COMMANDS: raise ValueError('unsupported command')
        transitions={'start':'running','resume':'running','stop':'stopped','pause':'paused','recover':'recovering'}
        self.state.mode=transitions[command]; self.state.generation+=1; self.state.last_command=command; self.state.reason=reason; self.state.updated_at=time.time()
        self.events.append({'id':uuid.uuid4().hex,'ts':self.state.updated_at,'command':command,'reason':reason,'generation':self.state.generation})
        self._save(); return asdict(self.state)
    def allows_work(self): return self.state.mode=='running'
    def snapshot(self): return asdict(self.state)
