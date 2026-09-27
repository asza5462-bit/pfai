"""Isolated recovery drills for verified backup snapshots."""
from __future__ import annotations
import hashlib, shutil, sqlite3, tempfile
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DrillResult:
    snapshot: str
    verified: bool
    restored: bool
    integrity_ok: bool
    state_rows: int
    error: str | None = None

class RecoveryDrill:
    def __init__(self, backup_dir: str | Path):
        self.backup_dir = Path(backup_dir)

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    def verify_snapshot(self, snapshot: str, expected_sha256: str | None = None) -> bool:
        p = self.backup_dir / snapshot
        if not p.is_file():
            return False
        if expected_sha256 is None:
            return True
        return self._sha256(p) == expected_sha256

    def drill_sqlite(self, snapshot: str, expected_sha256: str | None = None) -> DrillResult:
        p = self.backup_dir / snapshot
        if not self.verify_snapshot(snapshot, expected_sha256):
            return DrillResult(snapshot, False, False, False, 0, 'snapshot verification failed')
        tmp = Path(tempfile.mkdtemp(prefix='pfai-recovery-drill-'))
        try:
            restored = tmp / p.name
            shutil.copy2(p, restored)
            con = sqlite3.connect(restored)
            try:
                integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
                rows = 0
                tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for (name,) in tables:
                    if name.startswith('sqlite_'):
                        continue
                    try:
                        # Table names can't be bound as query parameters in sqlite3, so
                        # the identifier is quoted manually here. Doubling embedded `"`
                        # characters is the correct SQLite escape for a quoted identifier
                        # and prevents a crafted table name from breaking out of the
                        # quoted context (defense in depth: this reads a copy of an
                        # already-verified snapshot in an isolated temp dir, but a
                        # snapshot's own hash check is optional, so this is not assumed
                        # to be fully trusted input).
                        safe_name = name.replace('"', '""')
                        rows += int(con.execute(f'SELECT COUNT(*) FROM "{safe_name}"').fetchone()[0])
                    except sqlite3.DatabaseError:
                        pass
                return DrillResult(snapshot, True, True, integrity == 'ok', rows,
                                   None if integrity == 'ok' else integrity)
            finally:
                con.close()
        except Exception as exc:
            return DrillResult(snapshot, True, False, False, 0, str(exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
