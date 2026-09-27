import hashlib, json, time
from pathlib import Path

class SecurityKnowledgeGraph:
    def __init__(self, path='data/security/knowledge_graph.jsonl'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
    def _fp(self, obj):
        return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def add(self, kind, node_id, attrs=None, provenance=None, verified=False):
        if not kind or not node_id: raise ValueError('kind and node_id required')
        if verified and not provenance: raise PermissionError('verified knowledge requires provenance')
        rec={'ts':time.time(),'op':'node','kind':kind,'id':node_id,'attrs':attrs or {},'provenance':provenance,'verified':bool(verified)}
        rec['fingerprint']=self._fp(rec)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(rec,sort_keys=True)+'\n')
        return rec['fingerprint']
    def link(self, src, relation, dst, provenance=None, verified=False):
        if verified and not provenance: raise PermissionError('verified relation requires provenance')
        rec={'ts':time.time(),'op':'edge','src':src,'relation':relation,'dst':dst,'provenance':provenance,'verified':bool(verified)}
        rec['fingerprint']=self._fp(rec)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(rec,sort_keys=True)+'\n')
        return rec['fingerprint']
    def query(self, node_id=None, relation=None, verified_only=False):
        out=[]
        if not self.path.exists(): return out
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line: continue
            r=json.loads(line)
            if verified_only and not r.get('verified'): continue
            if node_id and node_id not in (r.get('id'),r.get('src'),r.get('dst')): continue
            if relation and r.get('relation') != relation: continue
            out.append(r)
        return out
