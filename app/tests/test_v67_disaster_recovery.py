import tempfile, sqlite3, unittest
from pathlib import Path
from pfai.disaster_recovery import DisasterRecovery

class TestV67(unittest.TestCase):
    def test_snapshot_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d)/'state.db'; s=Path(d)/'snapshots'
            with sqlite3.connect(db) as c:
                c.execute('create table state(k text primary key,v text)'); c.execute("insert into state values('x','1')"); c.commit()
            dr=DisasterRecovery(db,s); snap=dr.create_snapshot('boot')
            db.write_bytes(b'corrupt'); self.assertFalse(dr.integrity()['ok'])
            out=dr.recover(); self.assertTrue(out['recovered']); self.assertEqual(Path(snap).read_bytes(), db.read_bytes())
    def test_invalid_snapshot_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'state.db'; s=Path(d)/'snapshots'; s.mkdir()
            bad=s/'bad.db'; bad.write_bytes(b'nope')
            dr=DisasterRecovery(db,s); self.assertIsNone(dr.latest_valid_snapshot())

if __name__=='__main__': unittest.main()
