import json, sqlite3, threading
from pathlib import Path
from datetime import datetime, timezone

class VectorStore:
    def __init__(self,path,embedder):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(p, check_same_thread=False)
        self._lock=threading.RLock(); self.embedder=embedder
        with self._lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS vectors (id INTEGER PRIMARY KEY, content TEXT, source TEXT, metadata TEXT, vector TEXT, created_at TEXT)")
            self.db.commit()
    def add(self,content,source='',metadata=None):
        v=self.embedder.embed(content)
        with self._lock:
            self.db.execute("INSERT INTO vectors(content,source,metadata,vector,created_at) VALUES(?,?,?,?,?)",(content,source,json.dumps(metadata or {},ensure_ascii=False),json.dumps(v),datetime.now(timezone.utc).isoformat()))
            self.db.commit()
    def close(self):
        with getattr(self,'_lock',threading.RLock()):
            if getattr(self,'db',None) is not None:
                self.db.close(); self.db=None
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def __del__(self):
        try: self.close()
        except Exception: pass
    def search(self,query,limit=5):
        q=self.embedder.embed(query)
        with self._lock:
            rows=self.db.execute("SELECT id,content,source,metadata,vector,created_at FROM vectors").fetchall()
        out=[]
        for r in rows:
            v=json.loads(r[4]); score=sum(a*b for a,b in zip(q,v))
            out.append({'id':r[0],'content':r[1],'source':r[2],'metadata':json.loads(r[3]),'score':round(score,6),'created_at':r[5]})
        return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]
