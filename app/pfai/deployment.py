from dataclasses import dataclass
from datetime import datetime, timezone
import json, os
@dataclass
class CanaryState:
    version:str; traffic:float; status:str; created_at:str; promoted_at:str=''; rolled_back_at:str=''
class DeploymentController:
    def __init__(self,path='data/deployments.json',registry=None):
        self.path=path; self.registry=registry; os.makedirs(os.path.dirname(path) or '.',exist_ok=True)
        if not os.path.exists(path): self._save([])
    def _load(self):
        with open(self.path,'r',encoding='utf-8') as f:return json.load(f)
    def _save(self,x):
        with open(self.path,'w',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
    def canary(self,version,traffic=.1):
        if not 0 < traffic <= 1: raise ValueError('traffic must be in (0,1]')
        rows=self._load(); state=CanaryState(version,float(traffic),'canary',datetime.now(timezone.utc).isoformat())
        rows.append(state.__dict__); self._save(rows); return rows[-1]
    def promote(self,version):
        rows=self._load(); target=next((x for x in reversed(rows) if x['version']==version and x['status']=='canary'),None)
        if not target:return False
        target['status']='promoted'; target['promoted_at']=datetime.now(timezone.utc).isoformat(); self._save(rows)
        return self.registry.promote(version) if self.registry else True
    def rollback(self,version):
        rows=self._load(); target=next((x for x in reversed(rows) if x['version']==version and x['status'] in ('canary','promoted')),None)
        if not target:return False
        target['status']='rolled_back'; target['rolled_back_at']=datetime.now(timezone.utc).isoformat(); self._save(rows); return True
    def history(self): return self._load()
