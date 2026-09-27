from __future__ import annotations
import hashlib, json, time
from pathlib import Path

class DeceptionEngine:
    """Defensive deception registry for assets owned/authorized by the operator."""
    def __init__(self, ledger_path="data/security/deception_ledger.jsonl"):
        self.ledger = Path(ledger_path); self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self._last = "0" * 64

    def _append(self, event):
        event = dict(event, ts=time.time(), prev_hash=self._last)
        raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        event["hash"] = hashlib.sha256(raw).hexdigest()
        self._last = event["hash"]
        with self.ledger.open("a", encoding="utf-8") as f: f.write(json.dumps(event, sort_keys=True)+"\n")
        return event

    def create_honeypot(self, asset_id, owner, services, scope="lab"):
        if not asset_id or not owner or scope not in {"lab", "owned", "authorized"}:
            raise PermissionError("deception asset must be owned/authorized")
        return self._append({"action":"CREATE","asset":asset_id,"owner":owner,"services":sorted(set(services)),"scope":scope})

    def record_interaction(self, asset_id, source, indicator, interaction="probe"):
        if not asset_id or not source or not indicator:
            raise ValueError("asset, source and indicator are required")
        return self._append({"action":"INTERACTION","asset":asset_id,"source":source,"indicator":indicator,"interaction":interaction})

    def disable(self, asset_id, reason):
        return self._append({"action":"DISABLE","asset":asset_id,"reason":reason})

    def verify_chain(self):
        prev="0"*64
        if not self.ledger.exists(): return True
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            e=json.loads(line); h=e.pop("hash"); raw=json.dumps(e, sort_keys=True, separators=(",", ":")).encode()
            if e.get("prev_hash") != prev or hashlib.sha256(raw).hexdigest()!=h: return False
            prev=h
        self._last=prev
        return True
