from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import secrets

@dataclass(frozen=True)
class Capability:
    token_id: str
    task_id: str
    tool: str
    permissions: tuple[str, ...]
    resource: str
    expires_at: str
    max_calls: int
    issued_to: str

class ZeroTrustGateway:
    """Per-call zero-trust enforcement. Possessing a permission is not sufficient."""
    def __init__(self, permission_gate, audit=None):
        self.permission_gate = permission_gate
        self.audit = audit
        self._caps = {}
        self._usage = {}
        self._request_ids = {}

    @staticmethod
    def _now(): return datetime.now(timezone.utc)

    def issue(self, *, request_id, task_id, tool, resource='', ttl_seconds=300,
              max_calls=1, issued_to='model'):
        if ttl_seconds <= 0 or ttl_seconds > 3600: raise ValueError('invalid capability TTL')
        if max_calls < 1 or max_calls > 100: raise ValueError('invalid max_calls')
        if issued_to in {'root', 'kernel'}: raise PermissionError('invalid issuer')
        permissions = tuple(self.permission_gate.active_permissions(request_id))
        if not permissions: raise PermissionError('no active permissions')
        token_id = secrets.token_urlsafe(18)
        cap = Capability(token_id, task_id, tool, permissions, resource,
                         (self._now()+timedelta(seconds=ttl_seconds)).isoformat(), max_calls, issued_to)
        self._caps[token_id] = cap; self._usage[token_id] = 0
        self._audit('capability_issued', {'token_id':token_id,'task_id':task_id,'tool':tool,'request_id':request_id,'expires_at':cap.expires_at})
        return asdict(cap)

    def authorize(self, token_id, *, task_id, tool, permission, resource=''):
        cap = self._caps.get(token_id)
        if not cap: raise PermissionError('unknown capability')
        if cap.task_id != task_id or cap.tool != tool: raise PermissionError('capability scope mismatch')
        if permission not in cap.permissions: raise PermissionError('permission not granted')
        if cap.resource and resource != cap.resource: raise PermissionError('resource scope mismatch')
        if self._now() >= datetime.fromisoformat(cap.expires_at): raise PermissionError('capability expired')
        if self._usage[token_id] >= cap.max_calls: raise PermissionError('capability call limit exceeded')
        # Re-check live permission state on every call so revocation is immediate.
        if permission not in self.permission_gate.active_permissions(self._request_id_for(cap)):
            raise PermissionError('permission revoked')
        self._usage[token_id] += 1
        self._audit('tool_authorized', {'token_id':token_id,'task_id':task_id,'tool':tool,'permission':permission,'resource':resource})
        return True

    def bind_request(self, token_id, request_id):
        if token_id not in self._caps: raise ValueError('unknown capability')
        self._caps[token_id] = self._caps[token_id]  # immutable cap; mapping held separately
        self._request_ids[token_id] = request_id

    def _request_id_for(self, cap):
        rid = self._request_ids.get(cap.token_id)
        if not rid: raise PermissionError('capability not bound to approval')
        return rid

    def _audit(self, event, data):
        if self.audit and hasattr(self.audit, 'record'): self.audit.record('security', event, data)
