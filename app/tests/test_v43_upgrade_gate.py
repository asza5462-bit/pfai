import tempfile, unittest
from pathlib import Path
from pfai.model_upgrade_gate import ModelUpgradeGate

class TestV43UpgradeGate(unittest.TestCase):
    def test_requires_all_gates_and_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); artifact=root/'model.bin'; artifact.write_bytes(b'model-v1')
            g=ModelUpgradeGate(root/'audit', min_score=.8)
            r=g.audit('2.0',artifact,'1.0',.9,True,True,True)
            self.assertEqual(r['decision'],'WAITING_HUMAN_APPROVAL'); self.assertFalse(g.can_promote('2.0'))
            with self.assertRaises(PermissionError): g.approve_after_audit('2.0',artifact,'model')
            r=g.approve_after_audit('2.0',artifact,'human')
            self.assertEqual(r['decision'],'PASS'); self.assertTrue(g.can_promote('2.0'))
    def test_failed_security_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); artifact=root/'model.bin'; artifact.write_bytes(b'x')
            g=ModelUpgradeGate(root/'audit',min_score=.8)
            r=g.audit('2.1',artifact,'1.0',.95,False,True,True)
            self.assertEqual(r['decision'],'REJECT')
            with self.assertRaises(ValueError): g.approve_after_audit('2.1',artifact,'human')
    def test_artifact_change_blocks_approval(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); artifact=root/'model.bin'; artifact.write_bytes(b'a')
            g=ModelUpgradeGate(root/'audit',min_score=.5)
            g.audit('2.2',artifact,'1.0',.9,True,True,True); artifact.write_bytes(b'changed')
            with self.assertRaises(ValueError): g.approve_after_audit('2.2',artifact,'human')

if __name__=='__main__': unittest.main()
