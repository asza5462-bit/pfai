"""Runtime security monitor: bounded execution, anomaly detection, and kill switch."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json, os


def _now(): return datetime.now(timezone.utc).isoformat()

@dataclass
class RuntimeEvent:
    task_id: str
    capability_id: str
    tool: str
    action: str
    resource: str = ""
    cost: int = 1
    timestamp: str = ""

class RuntimeSecurity:
    def __init__(self, ledger_path="data/security/runtime_security.jsonl", max_events=10000):
        self.ledger_path = ledger_path
        self.max_events = max_events
        self._blocked = {}
        self._usage = {}
        self._chain = "GENESIS"

    def _append(self, kind, payload):
        os.makedirs(os.path.dirname(self.ledger_path) or ".", exist_ok=True)
        body = {"kind": kind, "payload": payload, "timestamp": _now(), "prev": self._chain}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
        body["hash"] = hashlib.sha256(raw.encode()).hexdigest()
        self._chain = body["hash"]
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True) + "\n")

    def inspect(self, event: RuntimeEvent, *, allowed_tools=None, max_cost=10, max_calls=20):
        if not event.timestamp: event.timestamp = _now()
        key = (event.task_id, event.capability_id)
        if self._blocked.get(key):
            self._append("BLOCKED", asdict(event) | {"reason": "kill_switch"})
            return False, "kill_switch"
        if allowed_tools is not None and event.tool not in set(allowed_tools):
            self.kill(event.task_id, event.capability_id, "tool_out_of_scope")
            return False, "tool_out_of_scope"
        usage = self._usage.setdefault(key, {"calls": 0, "cost": 0, "resources": set()})
        if usage["calls"] + 1 > max_calls:
            self.kill(event.task_id, event.capability_id, "call_limit")
            return False, "call_limit"
        if usage["cost"] + max(0, event.cost) > max_cost:
            self.kill(event.task_id, event.capability_id, "resource_budget")
            return False, "resource_budget"
        usage["calls"] += 1
        usage["cost"] += max(0, event.cost)
        if event.resource: usage["resources"].add(event.resource)
        self._append("ALLOWED", asdict(event) | {"calls": usage["calls"], "cost": usage["cost"]})
        return True, "allowed"

    def kill(self, task_id, capability_id, reason):
        self._blocked[(task_id, capability_id)] = str(reason)
        self._append("KILL_SWITCH", {"task_id": task_id, "capability_id": capability_id, "reason": str(reason)})

    def revoke(self, task_id, capability_id, reason="revoked"):
        self.kill(task_id, capability_id, reason)

    def is_blocked(self, task_id, capability_id):
        return (task_id, capability_id) in self._blocked

    def verify_ledger(self):
        if not os.path.exists(self.ledger_path): return True
        prev = "GENESIS"
        with open(self.ledger_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("prev") != prev: return False
                saved = row.pop("hash", None)
                raw = json.dumps(row, sort_keys=True, separators=(",", ":"))
                if hashlib.sha256(raw.encode()).hexdigest() != saved: return False
                prev = saved
        return True
