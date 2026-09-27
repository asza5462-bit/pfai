"""Authorized active-defense / red-team orchestration.

This module deliberately models attack actions instead of executing real-world
intrusion. Every operation is bound to an explicit sandbox/authorized scope.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json, os

SAFE_ACTIONS = {
    "asset_inventory", "port_check", "config_audit", "vulnerability_check",
    "exploit_simulation", "credential_exposure_simulation", "lateral_movement_simulation",
    "containment_test", "patch_validation", "recovery_test"
}
DESTRUCTIVE = {"data_delete", "ransomware", "persistence", "credential_theft", "real_exfiltration"}

def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class DefenseOperation:
    operation_id: str
    task_id: str
    action: str
    target: str
    scope: str
    mode: str
    approved_by: str
    status: str
    created_at: str

class ActiveDefenseController:
    """Plans and simulates offensive security actions only in authorized scope."""
    def __init__(self, ledger_path="data/security/active_defense.jsonl"):
        self.ledger_path = ledger_path
        self._chain = "GENESIS"
        self._ops = {}

    def _append(self, kind, payload):
        os.makedirs(os.path.dirname(self.ledger_path) or ".", exist_ok=True)
        body={"kind":kind,"payload":payload,"timestamp":_now(),"prev":self._chain}
        raw=json.dumps(body,sort_keys=True,separators=(",",":"))
        body["hash"]=hashlib.sha256(raw.encode()).hexdigest(); self._chain=body["hash"]
        with open(self.ledger_path,"a",encoding="utf-8") as f: f.write(json.dumps(body,sort_keys=True)+"\n")

    def request(self, *, task_id, action, target, scope, mode="simulation", approver=""):
        if action not in SAFE_ACTIONS: raise PermissionError("action not allowed by active-defense policy")
        if not target or not scope: raise ValueError("target and explicit scope are required")
        if mode not in {"simulation", "sandbox", "authorized_lab"}: raise PermissionError("unsafe mode")
        if not approver or approver in {"model", "agent"}: raise PermissionError("external approval required")
        if target not in scope and scope != "*": raise PermissionError("target outside authorized scope")
        opid=hashlib.sha256(f"{task_id}|{action}|{target}|{scope}|{mode}".encode()).hexdigest()[:24]
        op=DefenseOperation(opid,task_id,action,target,scope,mode,approver,"APPROVED",_now())
        self._ops[opid]=op; self._append("DEFENSE_APPROVED",asdict(op)); return asdict(op)

    def execute_simulation(self, operation_id, *, simulated_result="not_exploited"):
        op=self._ops.get(operation_id)
        if not op: raise PermissionError("unknown operation")
        if op.mode not in {"simulation","sandbox","authorized_lab"}: raise PermissionError("execution mode blocked")
        result={"operation_id":operation_id,"action":op.action,"target":op.target,"result":simulated_result,"executed":True,"real_intrusion":False}
        self._append("DEFENSE_SIMULATION",result); return result

    def verify_ledger(self):
        if not os.path.exists(self.ledger_path): return True
        prev="GENESIS"
        with open(self.ledger_path,encoding="utf-8") as f:
            for line in f:
                row=json.loads(line); saved=row.pop("hash",None)
                if row.get("prev")!=prev: return False
                raw=json.dumps(row,sort_keys=True,separators=(",",":"))
                if hashlib.sha256(raw.encode()).hexdigest()!=saved: return False
                prev=saved
        return True
