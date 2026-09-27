"""PFAI v5.2 unified security autonomy controller.

Defensive decision engine only. It does not grant permissions or execute attacks.
High-impact transitions require an external approver where configured.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import hashlib
import json
import time


class SecurityAction(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ISOLATE = "ISOLATE"
    SIMULATE = "SIMULATE"
    RECOVER = "RECOVER"
    LOCKDOWN = "LOCKDOWN"


@dataclass(frozen=True)
class SecurityDecision:
    action: SecurityAction
    reason: str
    risk: str
    external_approval_required: bool
    evidence_hash: str
    created_at: float = field(default_factory=time.time)


class SecurityAutonomyController:
    """Centralized policy decision point for defensive runtime actions."""
    HIGH_IMPACT = {SecurityAction.SIMULATE, SecurityAction.RECOVER, SecurityAction.LOCKDOWN}
    VALID_TRANSITIONS = {
        None: {SecurityAction.ALLOW, SecurityAction.DENY, SecurityAction.ISOLATE, SecurityAction.LOCKDOWN},
        SecurityAction.ALLOW: {SecurityAction.DENY, SecurityAction.ISOLATE, SecurityAction.SIMULATE, SecurityAction.LOCKDOWN},
        SecurityAction.DENY: {SecurityAction.ALLOW, SecurityAction.ISOLATE, SecurityAction.LOCKDOWN},
        SecurityAction.ISOLATE: {SecurityAction.DENY, SecurityAction.SIMULATE, SecurityAction.RECOVER, SecurityAction.LOCKDOWN},
        SecurityAction.SIMULATE: {SecurityAction.DENY, SecurityAction.ISOLATE, SecurityAction.LOCKDOWN},
        SecurityAction.RECOVER: {SecurityAction.ALLOW, SecurityAction.ISOLATE, SecurityAction.LOCKDOWN},
        SecurityAction.LOCKDOWN: {SecurityAction.DENY, SecurityAction.RECOVER},
    }

    def __init__(self, *, actor: str = "system", require_external_for_high_impact: bool = True):
        self.actor = actor
        self.require_external_for_high_impact = require_external_for_high_impact
        self.state: Optional[SecurityAction] = None
        self.history = []
        self.locked = False

    @staticmethod
    def _evidence_hash(evidence: object) -> str:
        raw = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def decide(self, action: SecurityAction, *, reason: str, risk: str = "LOW",
               evidence: object = None, external_approval: bool = False) -> SecurityDecision:
        if not isinstance(action, SecurityAction):
            action = SecurityAction(str(action))
        if self.state == SecurityAction.LOCKDOWN and action not in self.VALID_TRANSITIONS[SecurityAction.LOCKDOWN]:
            raise PermissionError("security controller is locked down")
        if action not in self.VALID_TRANSITIONS[self.state]:
            raise PermissionError(f"invalid security transition: {self.state} -> {action}")
        needs = self.require_external_for_high_impact and action in self.HIGH_IMPACT
        if needs and not external_approval:
            raise PermissionError(f"external approval required for {action.value}")
        if self.locked and action != SecurityAction.RECOVER:
            raise PermissionError("controller is locked")
        decision = SecurityDecision(action, reason, risk.upper(), needs,
                                    self._evidence_hash(evidence))
        self.state = action
        self.history.append(decision)
        self.locked = action == SecurityAction.LOCKDOWN
        return decision

    def emergency_lockdown(self, *, reason: str, evidence: object = None) -> SecurityDecision:
        # Emergency lockdown is a defensive fail-safe; it never grants capabilities.
        if self.state == SecurityAction.LOCKDOWN:
            return self.history[-1]
        old = self.require_external_for_high_impact
        self.require_external_for_high_impact = False
        try:
            return self.decide(SecurityAction.LOCKDOWN, reason=reason, risk="CRITICAL", evidence=evidence)
        finally:
            self.require_external_for_high_impact = old

    def can_recover(self, *, external_approval: bool) -> bool:
        return self.state == SecurityAction.LOCKDOWN and external_approval
