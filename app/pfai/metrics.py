import json, os, threading

class Metrics:
    def __init__(self, path='data/metrics.json'):
        self.path=path; os.makedirs(os.path.dirname(path) or '.', exist_ok=True); self._lock=threading.Lock()
        if not os.path.exists(path): self._save({'counters':{},'latency_ms':{}})
    def _load(self):
        with open(self.path,'r',encoding='utf-8') as f:return json.load(f)
    def _save(self,x):
        with open(self.path,'w',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
    def inc(self,name,n=1):
        with self._lock:
            x=self._load(); x['counters'][name]=x['counters'].get(name,0)+n; self._save(x)
    def observe(self,name,value):
        with self._lock:
            x=self._load(); x['latency_ms'].setdefault(name,[]).append(float(value)); self._save(x)
    def snapshot(self): return self._load()
