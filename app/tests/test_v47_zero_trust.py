import tempfile, unittest
from pathlib import Path
from pfai.permission_gate import PermissionGate
from pfai.zero_trust_gateway import ZeroTrustGateway

class TestZeroTrustGateway(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(); p=Path(self.td.name)/'ledger.jsonl'
        self.pg=PermissionGate(str(p))
        self.req=self.pg.request('model','tool:x',[],['filesystem_write'],'task')
        self.pg.approve(self.req['request_id'],'human')
        self.g=ZeroTrustGateway(self.pg)

    def tearDown(self): self.td.cleanup()

    def test_scope_and_single_use(self):
        c=self.g.issue(request_id=self.req['request_id'],task_id='T1',tool='tool.x',resource='/tmp/a',max_calls=1)
        self.g.bind_request(c['token_id'],self.req['request_id'])
        self.assertTrue(self.g.authorize(c['token_id'],task_id='T1',tool='tool.x',permission='filesystem_write',resource='/tmp/a'))
        with self.assertRaises(PermissionError): self.g.authorize(c['token_id'],task_id='T1',tool='tool.x',permission='filesystem_write',resource='/tmp/a')

    def test_cross_task_denied(self):
        c=self.g.issue(request_id=self.req['request_id'],task_id='T1',tool='tool.x')
        self.g.bind_request(c['token_id'],self.req['request_id'])
        with self.assertRaises(PermissionError): self.g.authorize(c['token_id'],task_id='T2',tool='tool.x',permission='filesystem_write')

    def test_revocation_is_immediate(self):
        c=self.g.issue(request_id=self.req['request_id'],task_id='T1',tool='tool.x')
        self.g.bind_request(c['token_id'],self.req['request_id'])
        self.pg.revoke(self.req['request_id'],'human')
        with self.assertRaises(PermissionError): self.g.authorize(c['token_id'],task_id='T1',tool='tool.x',permission='filesystem_write')

if __name__=='__main__': unittest.main()
