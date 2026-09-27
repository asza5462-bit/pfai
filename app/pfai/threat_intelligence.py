import hashlib, json, time
from pathlib import Path

class ThreatIntelligenceEngine:
    ALLOWED_TYPES = {'ip','domain','url','hash','email','cve','technique'}
    def __init__(self, path='data/security/threat_intel.jsonl'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
    def _fp(self,obj):
        return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def ingest(self, indicator, kind, source, confidence=0.0, observed_at=None, verified=False, tags=None):
        if not indicator or kind not in self.ALLOWED_TYPES or not source: raise ValueError('indicator, supported kind and source required')
        confidence=float(confidence)
        if not 0 <= confidence <= 1: raise ValueError('confidence must be 0..1')
        if verified and not source: raise PermissionError('verified intelligence requires source')
        rec={'ts':time.time(),'op':'indicator','indicator':indicator,'kind':kind,'source':source,'confidence':confidence,'observed_at':observed_at or time.time(),'verified':bool(verified),'tags':sorted(set(tags or []))}
        rec['fingerprint']=self._fp(rec)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(rec,sort_keys=True)+'\n')
        return rec['fingerprint']
    def query(self, indicator=None, verified_only=False, min_confidence=0.0):
        out=[]
        if not self.path.exists(): return out
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line: continue
            r=json.loads(line)
            if indicator and r.get('indicator') != indicator: continue
            if verified_only and not r.get('verified'): continue
            if r.get('confidence',0) < min_confidence: continue
            out.append(r)
        return out
    def conflicts(self, indicator):
        rows=self.query(indicator)
        return len({r['source'] for r in rows}) > 1 and len({r['verified'] for r in rows}) > 1
    def decision_input(self, indicator):
        rows=self.query(indicator, verified_only=True)
        if not rows: return {'indicator':indicator,'usable':False,'reason':'no_verified_intelligence'}
        return {'indicator':indicator,'usable':True,'confidence':max(r['confidence'] for r in rows),'sources':sorted({r['source'] for r in rows}),'conflict':self.conflicts(indicator)}
