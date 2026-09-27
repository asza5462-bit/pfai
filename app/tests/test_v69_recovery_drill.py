import sqlite3, tempfile, unittest
from pathlib import Path
from pfai.recovery_drill import RecoveryDrill

class TestRecoveryDrill(unittest.TestCase):
    def test_valid_snapshot_restores_in_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); db = d/'state.db'
            c = sqlite3.connect(db); c.execute('create table state(k text, v text)'); c.execute('insert into state values (?,?)', ('x','1')); c.commit(); c.close()
            r = RecoveryDrill(d).drill_sqlite('state.db')
            self.assertTrue(r.verified); self.assertTrue(r.restored); self.assertTrue(r.integrity_ok); self.assertEqual(r.state_rows, 1)

    def test_bad_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); (d/'x.db').write_bytes(b'not-a-db')
            r = RecoveryDrill(d).drill_sqlite('x.db', '0'*64)
            self.assertFalse(r.verified); self.assertFalse(r.restored)

    def test_live_file_is_not_modified(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); db = d/'state.db'
            c = sqlite3.connect(db); c.execute('create table state(v integer)'); c.execute('insert into state values (7)'); c.commit(); c.close()
            before = db.read_bytes(); RecoveryDrill(d).drill_sqlite('state.db'); self.assertEqual(before, db.read_bytes())

if __name__ == '__main__': unittest.main()
