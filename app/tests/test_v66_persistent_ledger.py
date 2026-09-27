import tempfile, unittest
from pathlib import Path
from pfai.persistent_ledger import PersistentLedger

class TestPersistentLedger(unittest.TestCase):
    def test_state_survives_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.db'
            with PersistentLedger(p) as x:
                x.set_state('job',{'status':'RUNNING','checkpoint':'c1'}); x.append_event('JOB_STARTED',{'job':'j1'})
            with PersistentLedger(p) as y:
                self.assertEqual(y.get_state('job')['checkpoint'],'c1'); self.assertTrue(y.verify_chain())

    def test_chain_detects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.db'
            with PersistentLedger(p) as x: x.append_event('X',{'n':1})
            import sqlite3
            c=sqlite3.connect(p); c.execute("UPDATE events SET payload='{}' WHERE id=1"); c.commit(); c.close()
            with PersistentLedger(p) as y: self.assertFalse(y.verify_chain())

    def test_transactional_updates(self):
        with tempfile.TemporaryDirectory() as d:
            with PersistentLedger(Path(d)/'state.db') as x:
                x.set_state('a',1); x.set_state('a',2); self.assertEqual(x.get_state('a'),2); self.assertTrue(x.verify_chain())

if __name__=='__main__': unittest.main()
