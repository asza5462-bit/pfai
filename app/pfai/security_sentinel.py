"""Autonomous defensive security sentinel for runtime behavior."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import hashlib, json, os

@dataclass(frozen=True)
class SentinelEvent:
    task_id: str
    capability_id: str
    tool: str
    permission: str
    resource: str = ""
    success: bool = True

class SecuritySentinel:
    """Detects behavioral drift and can isolate; it never grants privileges."""
    def __init__(self, ledger_path="data/security/sentinel.jsonl", window=20, failure_threshold=3, tool_threshold=4):
        self.ledger_path = ledger_path
        self.window = window
        self.failure_threshold = failure_threshold
        self.tool_threshold = tool_threshold
        self._history = defaultdict(lambda: deque(maxlen=window))
        self._isolated = {}
        self._chain = "GENESIS"

    def _append(self, kind, payload):
        os.makedirs(os.path.dirname(self.ledger_path) or ".", exist_ok=True)
        body={"kind":kind,"payload":payload,"prev":self._chain}
        raw=json.dumps(body,sort_keys=True,separators=(",",":"))
        body["hash"]=hashlib.sha256(raw.encode()).hexdigest(); self._chain=body["hash"]
        with open(self.ledger_path,"a",encoding="utf-8") as f: f.write(json.dumps(body,sort_keys=True)+"\n")

    def inspect(self, event: SentinelEvent, *, allowed_tools=None, allowed_permissions=None):
        key=(event.task_id,event.capability_id)
        if key in self._isolated:
            self._append("ISOLATED_BLOCK", asdict(event)|{"reason":self._isolated[key]})
            return False, "isolated"
        if allowed_tools is not None and event.tool not in set(allowed_tools):
            return self.isolate(*key, reason="tool_drift"), "tool_drift"
        if allowed_permissions is not None and event.permission not in set(allowed_permissions):
            return self.isolate(*key, reason="permission_drift"), "permission_drift"
        h=self._history[key]; h.append(event)
        failures=sum(not x.success for x in h)
        distinct_tools={x.tool for x in h}
        if failures >= self.failure_threshold:
            self.isolate(*key, reason="repeated_failures")
            return False, "repeated_failures"
        if len(distinct_tools) > self.tool_threshold:
            self.isolate(*key, reason="tool_drift")
            return False, "tool_drift"
        self._append("OBSERVED", asdict(event)|{"window":len(h),"failures":failures,"distinct_tools":len(distinct_tools)})
        return True, "observed"

    def isolate(self, task_id, capability_id, reason="anomaly"):
        self._isolated[(task_id,capability_id)]=str(reason)
        self._append("ISOLATE", {"task_id":task_id,"capability_id":capability_id,"reason":str(reason)})
        return False

    def release(self, task_id, capability_id, approver):
        if approver in {"model","agent",""}: raise PermissionError("external approval required")
        self._isolated.pop((task_id,capability_id),None)
        self._append("RELEASE", {"task_id":task_id,"capability_id":capability_id,"approver":approver})
        return True

    def is_isolated(self, task_id, capability_id): return (task_id,capability_id) in self._isolated

    def verify_ledger(self):
        if not os.path.exists(self.ledger_path): return True
        prev="GENESIS"
        with open(self.ledger_path,encoding="utf-8") as f:
            for line in f:
                row=json.loads(line); saved=row.pop("hash",None)
                if row.get("prev") != prev: return False
                raw=json.dumps(row,sort_keys=True,separators=(",",":"))
                if hashlib.sha256(raw.encode()).hexdigest()!=saved: return False
                prev=saved
        return True
