import unittest
from pfai.security_autonomy import SecurityAction, SecurityAutonomyController

class SecurityAutonomyTests(unittest.TestCase):
    def test_allow_then_deny(self):
        c = SecurityAutonomyController()
        self.assertEqual(c.decide(SecurityAction.ALLOW, reason="normal").action, SecurityAction.ALLOW)
        self.assertEqual(c.decide(SecurityAction.DENY, reason="policy").action, SecurityAction.DENY)

    def test_high_impact_requires_external(self):
        c = SecurityAutonomyController()
        c.decide(SecurityAction.ALLOW, reason="normal")
        with self.assertRaises(PermissionError):
            c.decide(SecurityAction.SIMULATE, reason="test")
        d = c.decide(SecurityAction.SIMULATE, reason="authorized test", external_approval=True)
        self.assertTrue(d.external_approval_required)

    def test_lockdown_blocks_unsafe_transition(self):
        c = SecurityAutonomyController()
        c.decide(SecurityAction.ALLOW, reason="normal")
        c.emergency_lockdown(reason="integrity failure", evidence={"ledger": "broken"})
        with self.assertRaises(PermissionError):
            c.decide(SecurityAction.SIMULATE, reason="must not run", external_approval=True)

    def test_recovery_requires_external_approval(self):
        c = SecurityAutonomyController()
        c.emergency_lockdown(reason="critical anomaly")
        self.assertFalse(c.can_recover(external_approval=False))
        self.assertTrue(c.can_recover(external_approval=True))

if __name__ == "__main__":
    unittest.main()
