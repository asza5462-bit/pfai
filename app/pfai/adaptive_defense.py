from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json, os

LEVELS = ("observe", "harden", "isolate", "simulate")
@dataclass(frozen=True)
class DefenseDecision:
    task_id: str; level: str; reason: str; score: int; requires_approval: bool; timestamp: str

def _now(): return datetime.now(timezone.utc).isoformat()

class AdaptiveDefenseOrchestrator:
    """Defensive response planner; never performs real intrusion or grants privileges."""
    def __init__(self, ledger_path="data/security/adaptive_defense.jsonl"):
        self.ledger_path=ledger_path; self._chain="GENESIS"
    def _append(self, kind, payload):
        os.makedirs(os.path.dirname(self.ledger_path) or ".", exist_ok=True)
        row={"kind":kind,"payload":payload,"timestamp":_now(),"prev":self._chain}
        raw=json.dumps(row,sort_keys=True,separators=(",",":")); row["hash"]=hashlib.sha256(raw.encode()).hexdigest(); self._chain=row["hash"]
        with open(self.ledger_path,"a",encoding="utf-8") as f:f.write(json.dumps(row,sort_keys=True)+"\n")
    def assess(self, task_id, *, anomaly_score=0, repeated_denials=0, capability_violation=False, integrity_failure=False):
        score=max(0,int(anomaly_score))+max(0,int(repeated_denials))*10+(40 if capability_violation else 0)+(80 if integrity_failure else 0)
        if integrity_failure or score>=80: level="isolate"
        elif score>=50: level="simulate"
        elif score>=20: level="harden"
        else: level="observe"
        d=DefenseDecision(task_id,level,"adaptive risk assessment",score,level in {"isolate","simulate"},_now())
        self._append("DEFENSE_DECISION",asdict(d)); return asdict(d)
    def approve_simulation(self, decision, approver):
        if decision["level"]!="simulate": raise PermissionError("simulation not required by decision")
        if not approver or approver in {"model","agent"}: raise PermissionError("external approval required")
        self._append("SIMULATION_APPROVED",{"task_id":decision["task_id"],"approver":approver}); return True
    def verify_ledger(self):
        if not os.path.exists(self.ledger_path): return True
        prev="GENESIS"
        with open(self.ledger_path,encoding="utf-8") as f:
            for line in f:
                row=json.loads(line); saved=row.pop("hash",None)
                if row.get("prev")!=prev:return False
                raw=json.dumps(row,sort_keys=True,separators=(",",":"))
                if hashlib.sha256(raw.encode()).hexdigest()!=saved:return False
                prev=saved
        return True
