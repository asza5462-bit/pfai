import unittest

from pfai.config import Config
from pfai.policy import Policy


class TestConfigPolicyKeyContract(unittest.TestCase):
    """Regression test for a real bug: configs/default.json used the key
    'network', but pfai/policy.py's Policy class only ever reads
    'allow_network'. That mismatch meant an operator flipping
    security.network to true in the shipped config file had NO effect --
    Policy.network stayed False silently, forever. Both pfai/app.py and the
    new pfai/research_gate.py wiring in pfai/api.py build their Policy
    straight from this config file, so this contract has to hold for network
    access to ever be enable-able at all."""

    def test_shipped_config_uses_the_key_policy_actually_reads(self):
        cfg = Config.load('configs/default.json')
        security = cfg['security']
        self.assertIn('allow_network', security,
                       "configs/default.json must use 'allow_network' -- "
                       "that's the only key pfai.policy.Policy reads")
        self.assertNotIn('network', security,
                          "'network' is not read by Policy; it silently does nothing")

    def test_flipping_the_shipped_key_actually_changes_policy_behavior(self):
        cfg = Config.load('configs/default.json')
        security = dict(cfg['security'])
        security['allow_network'] = True
        security['allowed_domains'] = ['example.com']
        policy = Policy(security)
        self.assertTrue(policy.allow_url('https://example.com/page'))
        self.assertFalse(policy.allow_url('https://not-allowed.example/page'))


if __name__ == '__main__':
    unittest.main()
