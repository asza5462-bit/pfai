import os, tempfile, unittest
from pathlib import Path
from pfai.owner_control import OwnerControl
from pfai.global_fabric import GlobalFabric

class TestV58(unittest.TestCase):
    def test_owner_auth_external_secret(self):
        with tempfile.TemporaryDirectory() as d:
            old=os.environ.get('PFAI_OWNER_SECRET_HASH'); os.environ['PFAI_OWNER_SECRET_HASH']=OwnerControl.hash_secret('test-secret')
            try:
                o=OwnerControl(str(Path(d)/'owner.jsonl'))
                self.assertTrue(o.authenticate('test-secret')); self.assertFalse(o.authenticate('wrong')); self.assertTrue(o.verify_chain())
            finally:
                if old is None: os.environ.pop('PFAI_OWNER_SECRET_HASH',None)
                else: os.environ['PFAI_OWNER_SECRET_HASH']=old
    def test_owner_commands_keep_safety_gate(self):
        with tempfile.TemporaryDirectory() as d:
            o=OwnerControl(str(Path(d)/'owner.jsonl'))
            e=o.authorize('DEPLOY','operator request')
            self.assertTrue(e['data']['safety_policy_may_block'])
    def test_fabric_requires_authorization(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json'))
            with self.assertRaises(PermissionError): g.register('s1','eu','ssh://x','owner',False)
            g.register('s1','eu','ssh://x','owner',True,{'cpu':8})
            self.assertEqual(g.plan_distribution()['count'],1)

if __name__=='__main__': unittest.main()
