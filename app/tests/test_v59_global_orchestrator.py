import tempfile, unittest, time
from pathlib import Path
from pfai.global_fabric import GlobalFabric
from pfai.global_orchestrator import GlobalOrchestrator

class TestV59(unittest.TestCase):
    def test_heartbeat_and_routing(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json'))
            g.register('eu1','eu','ssh://owned/eu1','owner',True,{'cpu':8})
            g.register('us1','us','ssh://owned/us1','owner',True,{'cpu':16})
            o=GlobalOrchestrator(g,str(Path(d)/'orch.jsonl'))
            o.heartbeat('eu1',load=.8); o.heartbeat('us1',load=.2)
            r=o.route_job('j1'); self.assertEqual(r['server_id'],'us1'); self.assertTrue(o.verify_chain())
    def test_stale_node_not_used(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json')); g.register('a','eu','x','owner',True)
            o=GlobalOrchestrator(g,str(Path(d)/'orch.jsonl'),heartbeat_timeout=1)
            o.heartbeat('a'); h=o.health(now=time.time()+2); self.assertEqual(h[0]['state'],'STALE')
            self.assertEqual(o.route_job('j', now=time.time()+2)['status'],'WAITING_FOR_WORKER')
    def test_no_unauthorized_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json')); o=GlobalOrchestrator(g,str(Path(d)/'orch.jsonl'))
            with self.assertRaises(PermissionError): o.heartbeat('x')

if __name__=='__main__': unittest.main()
