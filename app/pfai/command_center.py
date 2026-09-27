from __future__ import annotations
import hashlib, json, time
from pathlib import Path

class CommandCenter:
    """Read-mostly global observability surface. Operational actions remain behind existing gates."""
    def __init__(self, fabric=None, orchestrator=None, ledger_path='data/observability/command_center.jsonl'):
        self.fabric = fabric
        self.orchestrator = orchestrator
        self.path = Path(ledger_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists(): self.path.touch()

    def _append(self, event, data):
        rows = [json.loads(x) for x in self.path.read_text(encoding='utf-8').splitlines() if x.strip()]
        prev = rows[-1]['hash'] if rows else ''
        e = {'event': event, 'data': data, 'ts': time.time(), 'prev_hash': prev}
        e['hash'] = hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.path.open('a', encoding='utf-8') as f: f.write(json.dumps(e, sort_keys=True) + '\n')
        return e

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        health = self.orchestrator.health(now=now) if self.orchestrator else []
        counts = {}
        for x in health: counts[x['state']] = counts.get(x['state'], 0) + 1
        state = 'HEALTHY'
        if counts.get('STALE') or counts.get('DEGRADED'): state = 'DEGRADED'
        if counts.get('ISOLATED') or counts.get('LOCKDOWN'): state = 'ISOLATED'
        snap = {'state': state, 'workers': health, 'worker_counts': counts, 'ts': now}
        self._append('SNAPSHOT', snap)
        return snap

    def alerts(self, now=None):
        snap = self.snapshot(now=now)
        alerts = []
        for w in snap['workers']:
            if w['state'] == 'STALE': alerts.append({'severity':'HIGH','type':'STALE_WORKER','server_id':w['server_id']})
            elif w['state'] in {'ISOLATED','LOCKDOWN'}: alerts.append({'severity':'CRITICAL','type':'WORKER_SECURITY_STATE','server_id':w['server_id']})
        self._append('ALERT_EVALUATION', {'alerts': alerts})
        return alerts

    def verify_chain(self):
        prev = ''
        if not self.path.exists(): return True
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            e = json.loads(line); h = e.pop('hash')
            if e.get('prev_hash','') != prev: return False
            if hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != h: return False
            prev = h
        return True
