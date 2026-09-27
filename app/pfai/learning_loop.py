from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List
import json, os, hashlib

@dataclass
class Candidate:
    version: str
    dataset_hash: str
    score: float
    status: str
    created_at: str
    notes: str = ''

class LearningLoop:
    """Governed continuous-learning loop. It never self-grants privileges or deploys blindly."""
    def __init__(self, registry_path='data/learning_registry.json', min_improvement=0.01,
                 min_score=0.0, require_human_approval=False):
        self.registry_path=registry_path; self.min_improvement=float(min_improvement)
        self.min_score=float(min_score); self.require_human_approval=bool(require_human_approval)
        os.makedirs(os.path.dirname(registry_path) or '.', exist_ok=True)
        if not os.path.exists(registry_path): self._save([])
    def _load(self):
        with open(self.registry_path,'r',encoding='utf-8') as f: return json.load(f)
    def _save(self,x):
        with open(self.registry_path,'w',encoding='utf-8') as f: json.dump(x,f,ensure_ascii=False,indent=2)
    @staticmethod
    def fingerprint(items: List[Dict[str,Any]]) -> str:
        raw=json.dumps(items,sort_keys=True,ensure_ascii=False).encode(); return hashlib.sha256(raw).hexdigest()
    def propose(self, version, dataset, evaluator: Callable[[List[Dict[str,Any]]],float], notes=''):
        score=float(evaluator(dataset)); now=datetime.now(timezone.utc).isoformat()
        entries=self._load(); baseline=max((x['score'] for x in entries if x['status'] in ('accepted','active')), default=None)
        improvement=score-(baseline if baseline is not None else 0.0)
        eligible=score>=self.min_score and (baseline is None or improvement>=self.min_improvement)
        status='pending_approval' if eligible and self.require_human_approval else ('accepted' if eligible else 'rejected')
        c=Candidate(version,self.fingerprint(dataset),score,status,now,notes)
        entries.append(asdict(c)); self._save(entries)
        return {**asdict(c),'baseline':baseline,'improvement':improvement,'eligible':eligible}
    def approve(self,version):
        entries=self._load(); found=False
        for e in entries:
            if e['version']==version and e['status']=='pending_approval': e['status']='accepted'; found=True
        self._save(entries); return found
    def reject(self,version):
        entries=self._load(); found=False
        for e in entries:
            if e['version']==version and e['status']=='pending_approval': e['status']='rejected'; found=True
        self._save(entries); return found
    def active(self):
        entries=self._load(); active=[e for e in entries if e['status']=='active']
        return active[-1] if active else None
    def promote(self,version):
        entries=self._load(); target=None
        for e in entries:
            if e['version']==version and e['status'] in ('accepted','active'): target=e
        if not target: return False
        for e in entries:
            if e is target: e['status']='active'
            elif e['status']=='active': e['status']='accepted'
        self._save(entries); return True
    def rollback(self,version=None):
        entries=self._load(); accepted=[e for e in entries if e['status']=='accepted']
        if version:
            candidates=[e for e in accepted if e['version']==version]
        else: candidates=accepted[-1:]
        if not candidates: return False
        return self.promote(candidates[-1]['version'])
    def history(self): return self._load()
