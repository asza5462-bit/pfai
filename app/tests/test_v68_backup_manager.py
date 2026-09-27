import tempfile, unittest
from pathlib import Path
from pfai.backup_manager import BackupManager

class TestBackupManager(unittest.TestCase):
    def test_create_verify_and_rotate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'state.db'; src.write_bytes(b'one')
            bm=BackupManager(str(src), str(root/'backups'), retention=2)
            bm.create('a'); src.write_bytes(b'two'); bm.create('b'); src.write_bytes(b'three'); bm.create('c')
            self.assertGreaterEqual(len(bm.verified()), 2)
            self.assertLessEqual(len(bm._load()), 2)
    def test_tamper_is_rejected_and_latest_valid_restored(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'state.db'; src.write_bytes(b'good')
            bm=BackupManager(str(src), str(root/'backups'), retention=3)
            rec=bm.create('good'); src.write_bytes(b'bad')
            (root/'backups'/rec['path']).write_bytes(b'tampered')
            self.assertEqual(bm.verified(), [])
    def test_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'state.db'; src.write_bytes(b'good')
            bm=BackupManager(str(src), str(root/'backups'), retention=3); bm.create('good')
            src.write_bytes(b'corrupt'); rec=bm.restore_latest(); self.assertEqual(src.read_bytes(), b'good'); self.assertTrue(bm.verify(rec))

if __name__ == '__main__': unittest.main()
