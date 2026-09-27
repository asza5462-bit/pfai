import hashlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from pfai.recovery_policy import RecoveryPolicy

class TestRecoveryPolicy(unittest.TestCase):
    def _db(self, p, value='good'):
        c=sqlite3.connect(p); c.execute('create table state(v text)'); c.execute('insert into state values (?)',(value,)); c.commit(); c.close()
    def _snapshot(self, root, db):
        b=root/'backups'; b.mkdir(); snap=b/'good.db'; snap.write_bytes(db.read_bytes())
        digest=hashlib.sha256(snap.read_bytes()).hexdigest()
        (b/'good.json').write_text(json.dumps({'path':str(snap),'sha256':digest}), encoding='utf-8')
        return snap
    def test_valid_db_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); self._snapshot(r,db)
            d=RecoveryPolicy(db,r/'backups').decide(); self.assertEqual(d.action,'ALLOW'); self.assertIn('no_recovery',d.reason)
    def test_corrupt_db_auto_recovers_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db,'good'); self._snapshot(r,db); db.write_bytes(b'corrupt')
            d=RecoveryPolicy(db,r/'backups').recover(); self.assertEqual(d.action,'RECOVERED'); self.assertTrue(RecoveryPolicy(db,r/'backups')._integrity(db))
    def test_tampered_snapshot_denied(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); snap=self._snapshot(r,db); snap.write_bytes(b'bad'); db.write_bytes(b'corrupt')
            d=RecoveryPolicy(db,r/'backups').decide(); self.assertEqual(d.action,'DENY')
    def test_ledger_tamper_denies_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); self._snapshot(r,db); db.write_bytes(b'corrupt'); rp=RecoveryPolicy(db,r/'backups'); rp.decide(); ledger=r/'backups'/'recovery_policy_ledger.jsonl'; ledger.write_text(ledger.read_text().replace('verified', 'tampered', 1), encoding='utf-8')
            self.assertFalse(rp.verify_ledger()); self.assertEqual(rp.recover().action,'DENY')

if __name__=='__main__': unittest.main()
