import math, re, sqlite3
from collections import Counter
from pathlib import Path

TOKEN_RE=re.compile(r"\w+", re.UNICODE)
def tokens(s): return TOKEN_RE.findall(s.lower())
class SemanticMemory:
    def __init__(self,path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); self.db=sqlite3.connect(p)
        self.db.execute('CREATE TABLE IF NOT EXISTS semantic_chunks (id INTEGER PRIMARY KEY, content TEXT, source TEXT, metadata TEXT, created_at TEXT)'); self.db.commit()
    def close(self):
        if getattr(self, 'db', None) is not None:
            self.db.close(); self.db = None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def __del__(self):
        try: self.close()
        except Exception: pass

    def add(self,content,source='',metadata=''):
        from datetime import datetime, timezone
        self.db.execute('INSERT INTO semantic_chunks(content,source,metadata,created_at) VALUES(?,?,?,?)',(content,source,metadata,datetime.now(timezone.utc).isoformat())); self.db.commit()
    def _score(self,q,d):
        qt,dt=tokens(q),tokens(d); a=Counter(qt); b=Counter(dt); common=sum(min(a[x],b[x]) for x in a)
        return common/(math.sqrt(sum(v*v for v in a.values()))*math.sqrt(sum(v*v for v in b.values())) or 1)
    def search(self,q,limit=5):
        rows=self.db.execute('SELECT id,content,source,metadata,created_at FROM semantic_chunks').fetchall()
        out=[]
        for r in rows: out.append({'id':r[0],'content':r[1],'source':r[2],'metadata':r[3],'created_at':r[4],'score':self._score(q,r[1])})
        return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]
