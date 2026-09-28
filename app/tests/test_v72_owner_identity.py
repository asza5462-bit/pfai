import os, tempfile, unittest
from pathlib import Path
from pfai.owner_control import OwnerControl


class TestOwnerIdentity(unittest.TestCase):
    def _clean_env(self, *names):
        saved = {n: os.environ.pop(n, None) for n in names}
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v) for n, v in saved.items()])

    def test_identity_reports_username_and_secret_state_without_leaking_secret(self):
        self._clean_env('PFAI_OWNER_USERNAME', 'PFAI_OWNER_EMAIL', 'PFAI_OWNER_PASSWORD_HASH')
        with tempfile.TemporaryDirectory() as d:
            o = OwnerControl(str(Path(d) / 'owner.jsonl'))
            self.assertEqual(o.identity(), {'username': '', 'secret_configured': False})
            os.environ['PFAI_OWNER_USERNAME'] = 'owneruser'
            os.environ['PFAI_OWNER_PASSWORD_HASH'] = OwnerControl.hash_secret('a-strong-secret')
            ident = o.identity()
            self.assertEqual(ident['username'], 'owneruser')
            self.assertTrue(ident['secret_configured'])
            self.assertNotIn('secret', ident)
            self.assertNotIn('hash', ident)

    def test_authenticate_fails_closed_without_username_or_secret(self):
        self._clean_env('PFAI_OWNER_USERNAME', 'PFAI_OWNER_EMAIL', 'PFAI_OWNER_PASSWORD_HASH')
        with tempfile.TemporaryDirectory() as d:
            o = OwnerControl(str(Path(d) / 'owner.jsonl'))
            self.assertFalse(o.authenticate('anything'))
            self.assertFalse(o.authenticate(''))

    def test_owner_username_is_recorded_in_authorize_audit_trail(self):
        self._clean_env('PFAI_OWNER_USERNAME', 'PFAI_OWNER_EMAIL', 'PFAI_OWNER_PASSWORD_HASH')
        with tempfile.TemporaryDirectory() as d:
            os.environ['PFAI_OWNER_USERNAME'] = 'owneruser'
            o = OwnerControl(str(Path(d) / 'owner.jsonl'))
            event = o.authorize('DEPLOY_PROMOTE', 'owneruser promoted v2')
            self.assertEqual(event['data']['owner_username'], 'owneruser')
            self.assertTrue(o.verify_chain())


if __name__ == '__main__':
    unittest.main()
