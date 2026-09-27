import tempfile, unittest
from pathlib import Path
from pfai.permission_gate import PermissionGate

class TestPermissionGate(unittest.TestCase):
    def test_request_is_pending_and_model_cannot_self_approve(self):
        with tempfile.TemporaryDirectory() as d:
            g=PermissionGate(str(Path(d)/'ledger.jsonl'))
            r=g.request('model','worker',['read'],['network'],'need research')
            self.assertEqual(r['status'],'PENDING')
            with self.assertRaises(PermissionError): g.approve(r['request_id'],'model')
            self.assertEqual(g.active_permissions(r['request_id']),[])

    def test_human_approval_and_revoke(self):
        with tempfile.TemporaryDirectory() as d:
            g=PermissionGate(str(Path(d)/'ledger.jsonl'))
            r=g.request('model','worker',['read'],['network'],'research')
            g.approve(r['request_id'],'external-human')
            self.assertEqual(g.active_permissions(r['request_id']),['network'])
            g.revoke(r['request_id'],'external-human')
            self.assertEqual(g.active_permissions(r['request_id']),[])
            self.assertTrue(g.verify_chain())

    def test_forbidden_self_grant(self):
        with tempfile.TemporaryDirectory() as d:
            g=PermissionGate(str(Path(d)/'ledger.jsonl'))
            with self.assertRaises(PermissionError): g.request('model','self',[],['root'],'need power')

if __name__=='__main__': unittest.main()
