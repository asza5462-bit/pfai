import hashlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from pfai.recovery_scheduler import RecoveryDrillScheduler

class TestRecoveryScheduler(unittest.TestCase):
    def _db(self, p):
        c=sqlite3.connect(p); c.execute('create table state(v text)'); c.executemany('insert into state values (?)',[('a',),('b',)]); c.commit(); c.close()
    def test_run_and_history(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); b=r/'backups'; b.mkdir(); snap=b/'good.db'; snap.write_bytes(db.read_bytes()); digest=hashlib.sha256(snap.read_bytes()).hexdigest()
            s=RecoveryDrillScheduler(b, interval_seconds=100)
            rec=s.run('good.db', digest, now=1000)
            self.assertTrue(rec.integrity_ok); self.assertEqual(rec.state_rows,2); self.assertTrue(s.verify_history()); self.assertFalse(s.due('good.db', now=1050)); self.assertTrue(s.due('good.db', now=1101))
    def test_tamper_history_blocks_drill(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); b=r/'backups'; b.mkdir(); snap=b/'good.db'; snap.write_bytes(db.read_bytes())
            s=RecoveryDrillScheduler(b); s.run('good.db', now=1000); p=b/'recovery_drills.jsonl'; p.write_text(p.read_text().replace('"state_rows": 2','"state_rows": 99'))
            self.assertFalse(s.verify_history())
            with self.assertRaises(RuntimeError): s.run('good.db', now=2000)
    def test_bad_snapshot_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); b=r/'backups'; b.mkdir(); (b/'bad.db').write_bytes(b'not sqlite')
            s=RecoveryDrillScheduler(b); rec=s.run('bad.db'); self.assertFalse(rec.integrity_ok); self.assertFalse(rec.restored); self.assertTrue(s.verify_history())
if __name__=='__main__': unittest.main()
