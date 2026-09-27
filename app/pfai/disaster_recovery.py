import hashlib, json, os, shutil, sqlite3, tempfile
from pathlib import Path

class DisasterRecovery:
    def __init__(self, db_path, snapshot_dir=None):
        self.db_path = Path(db_path)
        self.snapshot_dir = Path(snapshot_dir or (self.db_path.parent / 'snapshots'))
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def integrity(self):
        if not self.db_path.exists():
            return {'ok': False, 'reason': 'missing_database'}
        try:
            with sqlite3.connect(self.db_path) as con:
                row = con.execute('PRAGMA integrity_check').fetchone()
                return {'ok': bool(row and row[0] == 'ok'), 'result': row[0] if row else None}
        except sqlite3.DatabaseError as exc:
            return {'ok': False, 'reason': 'database_error', 'error': str(exc)}

    def create_snapshot(self, label='auto'):
        if not self.integrity()['ok']:
            raise RuntimeError('cannot snapshot an invalid database')
        fd, tmp = tempfile.mkstemp(prefix='.snapshot-', dir=self.snapshot_dir)
        os.close(fd)
        try:
            shutil.copy2(self.db_path, tmp)
            digest = hashlib.sha256(Path(tmp).read_bytes()).hexdigest()
            target = self.snapshot_dir / f'{label}-{digest[:16]}.db'
            os.replace(tmp, target)
            meta = target.with_suffix('.json')
            meta.write_text(json.dumps({'path': str(target), 'sha256': digest}, sort_keys=True), encoding='utf-8')
            return str(target)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def latest_valid_snapshot(self):
        for p in sorted(self.snapshot_dir.glob('*.db'), key=lambda x: x.stat().st_mtime, reverse=True):
            if self._verify_snapshot(p): return p
        return None

    def _verify_snapshot(self, path):
        try:
            with sqlite3.connect(path) as con:
                row = con.execute('PRAGMA integrity_check').fetchone()
                if not row or row[0] != 'ok': return False
            meta = path.with_suffix('.json')
            if meta.exists():
                data = json.loads(meta.read_text(encoding='utf-8'))
                return hashlib.sha256(path.read_bytes()).hexdigest() == data.get('sha256')
            return True
        except Exception:
            return False

    def recover(self):
        if self.integrity()['ok']:
            return {'recovered': False, 'reason': 'database_valid'}
        snap = self.latest_valid_snapshot()
        if not snap: raise RuntimeError('no_valid_snapshot')
        backup = self.db_path.with_suffix('.corrupt')
        if self.db_path.exists(): os.replace(self.db_path, backup)
        shutil.copy2(snap, self.db_path)
        result = self.integrity()
        result.update({'recovered': result['ok'], 'snapshot': str(snap)})
        return result
