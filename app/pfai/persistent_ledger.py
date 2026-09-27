from __future__ import annotations
import hashlib, json, sqlite3, time
from pathlib import Path

class PersistentLedger:
    """Transactional SQLite state + tamper-evident event ledger."""
    def __init__(self, path='data/pfai_state.db'):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.conn=sqlite3.connect(self.path, isolation_level=None)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL)')

    def close(self):
        if self.conn: self.conn.close(); self.conn=None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def set_state(self,key,value):
        raw=json.dumps(value,sort_keys=True,separators=(',',':'))
        with self.conn:
            self.conn.execute('INSERT INTO state(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,raw,time.time()))

    def get_state(self,key,default=None):
        row=self.conn.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def append_event(self,kind,payload=None,ts=None):
        ts=time.time() if ts is None else float(ts); payload=payload or {}
        prev=self.conn.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
        prev=prev[0] if prev else ''
        body={'ts':ts,'kind':kind,'payload':payload,'prev_hash':prev}
        h=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.conn:
            self.conn.execute('INSERT INTO events(ts,kind,payload,prev_hash,hash) VALUES(?,?,?,?,?)',(ts,kind,json.dumps(payload,sort_keys=True),prev,h))
        return h

    def events(self):
        return [dict(id=r[0],ts=r[1],kind=r[2],payload=json.loads(r[3]),prev_hash=r[4],hash=r[5]) for r in self.conn.execute('SELECT id,ts,kind,payload,prev_hash,hash FROM events ORDER BY id')]

    def verify_chain(self):
        prev=''
        for e in self.events():
            body={'ts':e['ts'],'kind':e['kind'],'payload':e['payload'],'prev_hash':e['prev_hash']}
            if e['prev_hash']!=prev or hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=e['hash']: return False
            prev=e['hash']
        return True
