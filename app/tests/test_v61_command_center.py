import tempfile, unittest, time
from pathlib import Path
from pfai.global_fabric import GlobalFabric
from pfai.global_orchestrator import GlobalOrchestrator
from pfai.command_center import CommandCenter

class TestV61(unittest.TestCase):
    def test_snapshot_and_alert(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json')); g.register('a','eu','owned://a','owner',True)
            o=GlobalOrchestrator(g,str(Path(d)/'orch.jsonl'),heartbeat_timeout=1); o.heartbeat('a')
            c=CommandCenter(g,o,str(Path(d)/'cc.jsonl'))
            self.assertEqual(c.snapshot(now=time.time())['state'],'HEALTHY')
            alerts=c.alerts(now=time.time()+2)
            self.assertEqual(alerts[0]['type'],'STALE_WORKER')
            self.assertTrue(c.verify_chain())
    def test_empty_fabric_is_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            g=GlobalFabric(str(Path(d)/'servers.json')); o=GlobalOrchestrator(g,str(Path(d)/'orch.jsonl'))
            c=CommandCenter(g,o,str(Path(d)/'cc.jsonl'))
            self.assertEqual(c.snapshot()['state'],'HEALTHY'); self.assertEqual(c.alerts(),[])

if __name__=='__main__': unittest.main()
