from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class Server:
    server_id: str
    region: str
    endpoint: str
    owner: str
    authorized: bool = False
    capacity: dict | None = None
    status: str = 'UNKNOWN'

class GlobalFabric:
    """Deploy only to explicitly registered/authorized infrastructure; never discovers or commandeers idle servers."""
    def __init__(self, path='data/fabric/servers.json'):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists(): self.path.write_text('[]',encoding='utf-8')
    def register(self, server_id, region, endpoint, owner, authorized=False, capacity=None):
        if not all([server_id,region,endpoint,owner]): raise ValueError('all server identity fields required')
        if not authorized: raise PermissionError('explicit authorization required')
        rows=json.loads(self.path.read_text(encoding='utf-8'))
        if any(x['server_id']==server_id for x in rows): raise ValueError('server already registered')
        s=Server(server_id,region,endpoint,owner,True,capacity or {},'REGISTERED')
        rows.append(asdict(s)); self.path.write_text(json.dumps(rows,indent=2),encoding='utf-8'); return asdict(s)
    def list_authorized(self):
        return [x for x in json.loads(self.path.read_text(encoding='utf-8')) if x.get('authorized')]
    def plan_distribution(self, regions=None):
        rows=self.list_authorized(); regions=set(regions or [])
        if regions: rows=[x for x in rows if x['region'] in regions]
        return {'count':len(rows),'servers':rows,'plan_hash':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()}
