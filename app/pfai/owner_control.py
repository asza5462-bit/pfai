from __future__ import annotations
import hashlib, hmac, json, os, secrets, time
from pathlib import Path

class OwnerControl:
    """Top-level operator control, without disabling safety, audit, or authorization boundaries.

    Identity (who the owner is, e.g. an email address) and the secret (what proves it's
    them) are deliberately separate. The identity is not sensitive and may live in a
    config file; the secret must never be committed to source and is only ever read
    from the environment (or an env-managed secret store) at runtime.
    """
    def __init__(self, ledger_path='data/security/owner_control.jsonl', secret_env='PFAI_OWNER_SECRET_HASH',
                 email_env='PFAI_OWNER_EMAIL'):
        self.ledger=Path(ledger_path); self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.secret_env=secret_env
        self.email_env=email_env
    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()
    def configure_from_environment(self):
        if not os.environ.get(self.secret_env):
            raise RuntimeError(f'{self.secret_env} must be configured outside source code')
    def owner_email(self) -> str:
        return os.environ.get(self.email_env, '')
    def identity(self) -> dict:
        """Non-sensitive identity snapshot: who the owner is and whether a secret is set.
        Never returns the secret or its hash."""
        return {'email': self.owner_email(), 'secret_configured': bool(os.environ.get(self.secret_env))}
    def authenticate(self, presented_secret: str) -> bool:
        configured=os.environ.get(self.secret_env, '')
        if not configured or not presented_secret: return False
        ok=hmac.compare_digest(self.hash_secret(presented_secret), configured)
        self._audit('AUTH_SUCCESS' if ok else 'AUTH_FAILURE', {'email': self.owner_email()})
        return ok
    def authorize(self, action: str, reason: str, *, safety_policy_may_block=True):
        if not action or not reason: raise ValueError('action and reason required')
        event={'action':action,'reason':reason,'owner_authorized':True,'owner_email':self.owner_email(),
               'safety_policy_may_block':safety_policy_may_block,'nonce':secrets.token_hex(8),'ts':time.time()}
        return self._audit('OWNER_COMMAND', event)
    def _audit(self, action, data=None):
        prev=''
        if self.ledger.exists():
            lines=self.ledger.read_text(encoding='utf-8').splitlines()
            if lines: prev=json.loads(lines[-1])['hash']
        e={'event':action,'data':data or {},'prev_hash':prev,'ts':time.time()}
        e['hash']=hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.ledger.open('a',encoding='utf-8') as f: f.write(json.dumps(e,sort_keys=True)+'\n')
        return e
    def verify_chain(self):
        prev=''
        if not self.ledger.exists(): return True
        for line in self.ledger.read_text(encoding='utf-8').splitlines():
            e=json.loads(line); h=e.pop('hash')
            if e.get('prev_hash','') != prev or hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=h: return False
            prev=h
        return True
