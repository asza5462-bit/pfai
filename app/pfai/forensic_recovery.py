"""PFAI v5.3 forensic evidence and controlled recovery.
Defensive only: collects structured evidence, creates recovery plans, and
requires external approval for restoration from isolation/lockdown.
"""
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib, json, time
from pathlib import Path

class RecoveryState(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    RECOVERY_PLANNED = "RECOVERY_PLANNED"
    RECOVERY_APPROVED = "RECOVERY_APPROVED"
    RECOVERED = "RECOVERED"
    CLOSED = "CLOSED"

@dataclass(frozen=True)
class Evidence:
    incident_id: str
    kind: str
    subject: str
    data_hash: str
    timestamp: float
    source: str

@dataclass(frozen=True)
class RecoveryPlan:
    incident_id: str
    steps: tuple
    risk: str
    plan_hash: str
    created_at: float

class ForensicRecoveryCenter:
    def __init__(self, ledger_path="data/security/forensic_ledger.jsonl"):
        self.ledger_path = Path(ledger_path)
        self.state_path = self.ledger_path.with_suffix(".state.json")
        self.state = {}
        self._load()

    @staticmethod
    def _hash(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def _load(self):
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())

    def _append(self, event):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        prev = "GENESIS"
        if self.ledger_path.exists():
            lines = self.ledger_path.read_text().splitlines()
            if lines:
                prev = json.loads(lines[-1])["event_hash"]
        body = {"prev_hash": prev, **event}
        body["event_hash"] = self._hash(body)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")
        return body["event_hash"]

    def verify_chain(self):
        if not self.ledger_path.exists():
            return True
        prev = "GENESIS"
        for line in self.ledger_path.read_text().splitlines():
            item = json.loads(line)
            if item.get("prev_hash") != prev:
                return False
            expected = self._hash({k:v for k,v in item.items() if k != "event_hash"})
            if expected != item.get("event_hash"):
                return False
            prev = item["event_hash"]
        return True

    def open_incident(self, incident_id, subject, reason):
        if not self.verify_chain():
            raise RuntimeError("forensic ledger integrity failure")
        self.state[incident_id] = {"state": RecoveryState.OPEN.value, "subject": subject, "reason": reason}
        self._persist()
        self._append({"type":"INCIDENT_OPENED","incident_id":incident_id,"subject":subject,"reason":reason,"timestamp":time.time()})
        return self.state[incident_id]

    def collect(self, incident_id, kind, subject, data, source="runtime"):
        self._require(incident_id)
        ev = Evidence(incident_id, kind, subject, self._hash(data), time.time(), source)
        self._append({"type":"EVIDENCE","evidence":asdict(ev)})
        return ev

    def contain(self, incident_id, reason):
        self._require(incident_id)
        self.state[incident_id]["state"] = RecoveryState.CONTAINED.value
        self._persist(); self._append({"type":"CONTAINED","incident_id":incident_id,"reason":reason,"timestamp":time.time()})

    def plan_recovery(self, incident_id, steps, risk="MEDIUM"):
        self._require(incident_id)
        if self.state[incident_id]["state"] not in {RecoveryState.CONTAINED.value, RecoveryState.RECOVERY_PLANNED.value}:
            raise PermissionError("incident must be contained before recovery planning")
        steps = tuple(steps)
        plan_hash = self._hash({"incident_id":incident_id,"steps":steps,"risk":risk})
        plan = RecoveryPlan(incident_id, steps, risk.upper(), plan_hash, time.time())
        self.state[incident_id]["state"] = RecoveryState.RECOVERY_PLANNED.value
        self.state[incident_id]["plan_hash"] = plan_hash
        self._persist(); self._append({"type":"RECOVERY_PLAN","plan":asdict(plan)})
        return plan

    def approve_recovery(self, incident_id, approver, plan_hash):
        self._require(incident_id)
        if approver in {"model", "agent", "system", ""}:
            raise PermissionError("external approver required")
        if self.state[incident_id].get("plan_hash") != plan_hash:
            raise PermissionError("recovery plan changed or does not match")
        self.state[incident_id]["state"] = RecoveryState.RECOVERY_APPROVED.value
        self.state[incident_id]["approver"] = approver
        self._persist(); self._append({"type":"RECOVERY_APPROVED","incident_id":incident_id,"approver":approver,"plan_hash":plan_hash,"timestamp":time.time()})

    def recover(self, incident_id, plan_hash):
        self._require(incident_id)
        if self.state[incident_id]["state"] != RecoveryState.RECOVERY_APPROVED.value:
            raise PermissionError("external recovery approval required")
        if self.state[incident_id].get("plan_hash") != plan_hash:
            raise PermissionError("recovery plan mismatch")
        self.state[incident_id]["state"] = RecoveryState.RECOVERED.value
        self._persist(); self._append({"type":"RECOVERED","incident_id":incident_id,"plan_hash":plan_hash,"timestamp":time.time()})

    def close(self, incident_id):
        self._require(incident_id)
        if self.state[incident_id]["state"] != RecoveryState.RECOVERED.value:
            raise PermissionError("incident must be recovered before close")
        self.state[incident_id]["state"] = RecoveryState.CLOSED.value
        self._persist(); self._append({"type":"INCIDENT_CLOSED","incident_id":incident_id,"timestamp":time.time()})

    def _require(self, incident_id):
        if not self.verify_chain():
            raise RuntimeError("forensic ledger integrity failure")
        if incident_id not in self.state:
            raise KeyError("unknown incident")

    def _persist(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, sort_keys=True, indent=2))
