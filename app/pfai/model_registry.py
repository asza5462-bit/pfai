from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json, os

@dataclass
class ModelVersion:
    version: str
    artifact: str
    score: float
    status: str
    created_at: str
    parent: str = ''

class ModelRegistry:
    def __init__(self, path='data/model_registry.json'):
        self.path=path; os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        if not os.path.exists(path): self._save([])
    def _load(self):
        with open(self.path,'r',encoding='utf-8') as f:return json.load(f)
    def _save(self,x):
        with open(self.path,'w',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
    def register(self,version,artifact,score,parent=''):
        rows=self._load(); rows.append(asdict(ModelVersion(version,artifact,float(score),'candidate',datetime.now(timezone.utc).isoformat(),parent))); self._save(rows); return rows[-1]
    def promote(self,version):
        rows=self._load(); target=next((x for x in rows if x['version']==version and x['status']=='candidate'),None)
        if not target:return False
        for x in rows:
            if x['status']=='active':x['status']='archived'
        target['status']='active'; self._save(rows); return True
    def active(self):
        rows=self._load(); a=[x for x in rows if x['status']=='active']; return a[-1] if a else None
    def rollback(self,version):
        rows=self._load(); target=next((x for x in rows if x['version']==version and x['status'] in ('archived','candidate')),None)
        if not target:return False
        for x in rows:
            if x['status']=='active':x['status']='archived'
        target['status']='active'; self._save(rows); return True
    def history(self):return self._load()
