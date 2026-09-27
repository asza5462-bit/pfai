import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

class MemoryStore:
    """SQLite is always the durable source of truth for every memory. `vector_store`
    (optional) is a purely additive semantic index on top of it: if given, search()
    tries semantic retrieval first and falls back to the original exact-substring
    LIKE search whenever the index has no hits yet or is unavailable for any reason
    (fresh/empty index, embedder error, etc.) — so behavior is identical to before
    for any caller that doesn't pass one, and never breaks even for one that does.
    """
    def __init__(self,path,vector_store=None):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); self.db=sqlite3.connect(p, check_same_thread=False); self._lock=threading.RLock()
        with self._lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, kind TEXT, content TEXT, source TEXT, confidence REAL, created_at TEXT)'); self.db.commit()
        
        self.vector_store=vector_store
    def add(self,kind,content,source="",confidence=0.0):
        with self._lock:
            cur=self.db.execute('INSERT INTO memories(kind,content,source,confidence,created_at) VALUES(?,?,?,?,?)',(kind,content,source,float(confidence),datetime.now(timezone.utc).isoformat())); self.db.commit()
        row_id=cur.lastrowid
        if self.vector_store is not None:
            try: self.vector_store.add(content,source=source,metadata={'memory_id':row_id,'kind':kind,'confidence':float(confidence)})
            except Exception: pass  # semantic indexing is best-effort; the sqlite row above is already durable
        return row_id
    def all_documents(self):
        with self._lock:
            rows=self.db.execute('SELECT id,kind,content,source,confidence,created_at FROM memories ORDER BY id DESC').fetchall()
        return [dict(id=r[0],kind=r[1],content=r[2],source=r[3],confidence=r[4],created_at=r[5]) for r in rows]
    def _like_search(self,query,limit=10):
        with self._lock:
            rows=self.db.execute('SELECT id,kind,content,source,confidence,created_at FROM memories WHERE content LIKE ? ORDER BY id DESC LIMIT ?',(f'%{query}%',limit)).fetchall()
        return [dict(id=r[0],kind=r[1],content=r[2],source=r[3],confidence=r[4],created_at=r[5]) for r in rows]
    def search(self,query,limit=10):
        if self.vector_store is not None:
            try:
                hits=self.vector_store.search(query,limit=limit)
                hydrated=[]
                for h in hits:
                    mid=(h.get('metadata') or {}).get('memory_id')
                    if mid is None: continue
                    with self._lock:
                        row=self.db.execute('SELECT id,kind,content,source,confidence,created_at FROM memories WHERE id=?',(mid,)).fetchone()
                    if row: hydrated.append(dict(id=row[0],kind=row[1],content=row[2],source=row[3],confidence=row[4],created_at=row[5],score=h.get('score')))
                if hydrated: return hydrated[:limit]
            except Exception:
                pass
        return self._like_search(query,limit)

    def get(self, memory_id: int):
        with self._lock:
            row=self.db.execute('SELECT id,kind,content,source,confidence,created_at FROM memories WHERE id=?',(int(memory_id),)).fetchone()
        if not row: return None
        return dict(id=row[0],kind=row[1],content=row[2],source=row[3],confidence=row[4],created_at=row[5])

    def update(self, memory_id: int, content: str, confidence: float | None = None):
        """Correct an existing durable memory row. Returns False if missing."""
        with self._lock:
            row=self.db.execute('SELECT id FROM memories WHERE id=?',(int(memory_id),)).fetchone()
            if not row: return False
            if confidence is None:
                self.db.execute('UPDATE memories SET content=? WHERE id=?',(content,int(memory_id)))
            else:
                self.db.execute('UPDATE memories SET content=?, confidence=? WHERE id=?',(content,float(confidence),int(memory_id)))
            self.db.commit()
        return True

    def forget(self, memory_id: int) -> bool:
        """Permanently remove a memory row (owner-gated at the API/agent layer)."""
        with self._lock:
            cur=self.db.execute('DELETE FROM memories WHERE id=?',(int(memory_id),))
            self.db.commit()
            return cur.rowcount > 0

    def list_by_kind(self, kind: str, limit: int = 50):
        with self._lock:
            rows=self.db.execute(
                'SELECT id,kind,content,source,confidence,created_at FROM memories WHERE kind=? ORDER BY id DESC LIMIT ?',
                (kind, int(limit)),
            ).fetchall()
        return [dict(id=r[0],kind=r[1],content=r[2],source=r[3],confidence=r[4],created_at=r[5]) for r in rows]

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def __del__(self):
        try: self.db.close()
        except Exception: pass
