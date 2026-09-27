"""PFAI v5.4 defensive Security Learning Loop.
Incident-derived material is quarantined until provenance, integrity, and safety gates pass.
No automatic model promotion is performed here.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib, json, time

@dataclass(frozen=True)
class LearningItem:
    item_id: str
    incident_id: str
    kind: str
    content_hash: str
    provenance: str
    status: str
    created_at: float

class SecurityLearningLoop:
    def __init__(self, ledger_path="data/security/security_learning_ledger.jsonl"):
        self.ledger_path = Path(ledger_path)
        self.state_path = self.ledger_path.with_suffix(".state.json")
        self.state = {}
        if self.state_path.exists(): self.state = json.loads(self.state_path.read_text())

    @staticmethod
    def _hash(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def _append(self, event):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        prev="GENESIS"
        if self.ledger_path.exists() and self.ledger_path.read_text().strip():
            prev=json.loads(self.ledger_path.read_text().splitlines()[-1])["event_hash"]
        body={"prev_hash":prev, **event}; body["event_hash"]=self._hash(body)
        with self.ledger_path.open("a") as f: f.write(json.dumps(body, sort_keys=True)+"\n")
        return body["event_hash"]

    def verify_chain(self):
        if not self.ledger_path.exists(): return True
        prev="GENESIS"
        for line in self.ledger_path.read_text().splitlines():
            item=json.loads(line)
            if item.get("prev_hash") != prev: return False
            if self._hash({k:v for k,v in item.items() if k!="event_hash"}) != item.get("event_hash"): return False
            prev=item["event_hash"]
        return True

    def quarantine(self, incident_id, kind, content, provenance):
        if not self.verify_chain(): raise RuntimeError("security learning ledger integrity failure")
        if not incident_id or not provenance: raise ValueError("incident_id and provenance required")
        if kind.lower() in {"credential", "secret", "malware_payload", "exploit_payload"}:
            raise PermissionError("unsafe material cannot enter learning pipeline")
        item_id=self._hash({"incident_id":incident_id,"kind":kind,"content":content,"provenance":provenance})[:24]
        item=LearningItem(item_id, incident_id, kind, self._hash(content), provenance, "QUARANTINED", time.time())
        self.state[item_id]=asdict(item); self._persist(); self._append({"type":"LEARNING_QUARANTINED","item":asdict(item)})
        return item

    def verify(self, item_id, verifier):
        if verifier in {"model","agent","system",""}: raise PermissionError("external verifier required")
        self._require(item_id)
        if self.state[item_id]["status"] != "QUARANTINED": raise PermissionError("item is not quarantined")
        self.state[item_id]["status"]="VERIFIED"; self.state[item_id]["verifier"]=verifier
        self._persist(); self._append({"type":"LEARNING_VERIFIED","item_id":item_id,"verifier":verifier,"timestamp":time.time()})

    def admit(self, item_id):
        self._require(item_id)
        if self.state[item_id]["status"] != "VERIFIED": raise PermissionError("external verification required")
        self.state[item_id]["status"]="ADMITTED"; self._persist(); self._append({"type":"LEARNING_ADMITTED","item_id":item_id,"timestamp":time.time()})

    def reject(self, item_id, reason, reviewer="external"):
        self._require(item_id)
        if reviewer in {"model","agent","system",""}: raise PermissionError("external reviewer required")
        self.state[item_id]["status"]="REJECTED"; self.state[item_id]["reason"]=reason; self._persist()
        self._append({"type":"LEARNING_REJECTED","item_id":item_id,"reviewer":reviewer,"reason":reason,"timestamp":time.time()})

    def _require(self, item_id):
        if not self.verify_chain(): raise RuntimeError("security learning ledger integrity failure")
        if item_id not in self.state: raise KeyError("unknown learning item")
    def _persist(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True); self.state_path.write_text(json.dumps(self.state, sort_keys=True, indent=2))
