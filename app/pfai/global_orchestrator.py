from __future__ import annotations
import hashlib, json, time
from pathlib import Path

class GlobalOrchestrator:
    """Control-plane planner for explicitly authorized worker nodes. No discovery or takeover."""
    def __init__(self, fabric, state_path='data/fabric/orchestrator.jsonl', heartbeat_timeout=60):
        self.fabric = fabric
        self.path = Path(state_path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_timeout = heartbeat_timeout
        if not self.path.exists(): self.path.touch()

    def _rows(self):
        return [json.loads(x) for x in self.path.read_text(encoding='utf-8').splitlines() if x.strip()]

    def heartbeat(self, server_id, status='HEALTHY', load=0.0, capacity=None):
        if not any(x['server_id'] == server_id for x in self.fabric.list_authorized()):
            raise PermissionError('server is not explicitly authorized')
        e={'event':'HEARTBEAT','server_id':server_id,'status':status,'load':float(load),'capacity':capacity or {},'ts':time.time()}
        rows=self._rows(); prev=rows[-1]['hash'] if rows else ''
        e['prev_hash']=prev; e['hash']=hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(e,sort_keys=True)+'\n')
        return e

    def health(self, now=None):
        now = time.time() if now is None else now
        auth={x['server_id']:x for x in self.fabric.list_authorized()}
        latest={}
        for e in self._rows():
            if e.get('event')=='HEARTBEAT': latest[e['server_id']]=e
        out=[]
        for sid,s in auth.items():
            hb=latest.get(sid); age=None if not hb else max(0, now-hb['ts'])
            state='STALE' if hb is None or age > self.heartbeat_timeout else hb['status']
            out.append({'server_id':sid,'region':s['region'],'state':state,'load':None if not hb else hb['load'],'heartbeat_age':age})
        return out

    def route_job(self, job_id, required_region=None, now=None):
        candidates=[x for x in self.health(now=now) if x['state']=='HEALTHY']
        if required_region: candidates=[x for x in candidates if x['region']==required_region]
        if not candidates: return {'job_id':job_id,'status':'WAITING_FOR_WORKER'}
        chosen=sorted(candidates,key=lambda x:(x['load'],x['server_id']))[0]
        return {'job_id':job_id,'status':'ROUTED','server_id':chosen['server_id'],'region':chosen['region']}

    def failover(self, job_id, failed_server_id, required_region=None, now=None):
        if failed_server_id not in {x['server_id'] for x in self.fabric.list_authorized()}:
            raise PermissionError('failed server is not an authorized node')
        result=self.route_job(job_id, required_region, now=now)
        result['failed_server_id']=failed_server_id
        result['failover']=result['status']=='ROUTED'
        return result

    def verify_chain(self):
        prev=''
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            e=json.loads(line); h=e.pop('hash')
            if e.get('prev_hash','') != prev: return False
            if hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=h: return False
            prev=h
        return True
