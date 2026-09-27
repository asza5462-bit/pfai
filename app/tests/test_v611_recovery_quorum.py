import hashlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from pfai.recovery_policy import RecoveryPolicy

class TestRecoveryQuorum(unittest.TestCase):
    def _db(self, p):
        c=sqlite3.connect(p); c.execute('create table state(v text)'); c.execute('insert into state values ("good")'); c.commit(); c.close()
    def _snapshot(self, root, db):
        b=root/'backups'; b.mkdir(); snap=b/'good.db'; snap.write_bytes(db.read_bytes())
        digest=hashlib.sha256(snap.read_bytes()).hexdigest()
        (b/'good.json').write_text(json.dumps({'path':str(snap),'sha256':digest}), encoding='utf-8')
    def test_forced_recovery_requires_quorum(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); self._snapshot(r,db)
            rp=RecoveryPolicy(db,r/'backups',approval_quorum=2)
            d=rp.decide(force=True); self.assertEqual(d.action,'APPROVAL_REQUIRED')
            self.assertFalse(rp.approve(d,['operator']))
            self.assertFalse(rp.approve(d,['model','operator']))
            self.assertTrue(rp.approve(d,['operator-a','operator-b']))
    def test_model_cannot_satisfy_quorum(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); self._snapshot(r,db); db.write_bytes(b'corrupt')
            rp=RecoveryPolicy(db,r/'backups',approval_quorum=1)
            d=rp.recover(force=True,approvers=['model']); self.assertEqual(d.action,'DENY')
            self.assertTrue(d.approval_required)
    def test_forced_recovery_with_external_quorum(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); db=r/'state.db'; self._db(db); self._snapshot(r,db); db.write_bytes(b'corrupt')
            rp=RecoveryPolicy(db,r/'backups',approval_quorum=2)
            d=rp.recover(force=True,approvers=['operator-a','operator-b'])
            self.assertEqual(d.action,'RECOVERED'); self.assertTrue(rp._integrity(db))

if __name__=='__main__': unittest.main()
