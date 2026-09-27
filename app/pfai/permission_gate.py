from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json

FORBIDDEN_SELF_GRANTS = {'root', 'kernel', 'disable_audit', 'disable_policy', 'unrestricted_network'}

@dataclass
class PermissionRequest:
    request_id: str
    actor: str
    target: str
    current: list[str]
    requested: list[str]
    reason: str
    risk: str
    status: str
    created_at: str

class PermissionGate:
    """Default-deny permission escalation. The model may request, never self-approve."""
    def __init__(self, path='data/security/permission_ledger.jsonl'):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self.path.with_suffix('.state.json')
        if not self.state.exists(): self.state.write_text(json.dumps({'approved':{},'revoked':{}}), encoding='utf-8')

    def _state(self): return json.loads(self.state.read_text(encoding='utf-8'))
    def _save(self, x): self.state.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding='utf-8')
    @staticmethod
    def _id(actor,target,requested,reason):
        raw='|'.join([actor,target,','.join(sorted(requested)),reason])
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
    @staticmethod
    def _risk(requested):
        high={'network','shell','filesystem_write','process_control','deploy','model_promote'}
        if any(p in high for p in requested): return 'HIGH'
        if len(requested)>2: return 'MEDIUM'
        return 'LOW'
    def request(self, actor, target, current, requested, reason):
        requested=list(dict.fromkeys(requested)); current=list(dict.fromkeys(current))
        if actor == 'model' and any(p in FORBIDDEN_SELF_GRANTS for p in requested):
            raise PermissionError('forbidden self-grant request')
        rid=self._id(actor,target,requested,reason)
        item=PermissionRequest(rid,actor,target,current,requested,reason,self._risk(requested),'PENDING',datetime.now(timezone.utc).isoformat())
        self._append(item); return asdict(item)
    def _append(self,item):
        prev=''
        if self.path.exists():
            lines=self.path.read_text(encoding='utf-8').splitlines()
            if lines: prev=json.loads(lines[-1])['entry_hash']
        d=asdict(item); d['prev_hash']=prev
        d['entry_hash']=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(d,ensure_ascii=False)+'\n')
    def approve(self, request_id, approver):
        if not approver or approver in {'model','agent'}: raise PermissionError('external approver required')
        entries=self._entries(); req=next((x for x in entries if x['request_id']==request_id),None)
        if not req: raise ValueError('unknown request')
        s=self._state(); s['approved'][request_id]={'approver':approver,'approved_at':datetime.now(timezone.utc).isoformat(),'permissions':req['requested']}; self._save(s)
        self._append_event(request_id,'APPROVED',approver,req['requested']); return s['approved'][request_id]
    def revoke(self, request_id, approver):
        if not approver or approver in {'model','agent'}: raise PermissionError('external approver required')
        s=self._state(); s['revoked'][request_id]={'approver':approver,'revoked_at':datetime.now(timezone.utc).isoformat()}; self._save(s); self._append_event(request_id,'REVOKED',approver,[])
    def active_permissions(self, request_id):
        s=self._state(); return [] if request_id in s['revoked'] else s['approved'].get(request_id,{}).get('permissions',[])
    def _entries(self):
        if not self.path.exists(): return []
        return [json.loads(x) for x in self.path.read_text(encoding='utf-8').splitlines() if x]
    def _append_event(self,rid,status,actor,permissions):
        self._append(PermissionRequest(rid,actor,'permission',[],permissions,'ledger_event','HIGH',status,datetime.now(timezone.utc).isoformat()))
    def verify_chain(self):
        prev=''
        for raw in self.path.read_text(encoding='utf-8').splitlines() if self.path.exists() else []:
            d=json.loads(raw); h=d.pop('entry_hash');
            if d.get('prev_hash','') != prev or hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()!=h: return False
            prev=h
        return True
