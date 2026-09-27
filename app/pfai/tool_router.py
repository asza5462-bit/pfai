"""Tool Router — Brain calls tools; Heart (PFAI core) executes them.

Sensitive tools never auto-run: the Command Agent must obtain Owner approval first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str  # read | write | sensitive
    requires_approval: bool
    args_schema: dict


class ToolRouter:
    """Dispatch whitelist tools to injected heart callbacks."""

    def __init__(self, handlers: dict[str, Callable[..., Any]], specs: list[ToolSpec] | None = None):
        self.handlers = dict(handlers)
        self.specs = {s.name: s for s in (specs or DEFAULT_TOOLS)}

    def catalog(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "risk": s.risk,
                "requires_approval": s.requires_approval,
                "args_schema": s.args_schema,
            }
            for s in self.specs.values()
            if s.name in self.handlers
        ]

    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

    def requires_approval(self, name: str) -> bool:
        spec = self.specs.get(name)
        return bool(spec and spec.requires_approval)

    def execute(self, name: str, args: dict | None = None, *, approved: bool = False) -> dict:
        spec = self.specs.get(name)
        if not spec or name not in self.handlers:
            return {"ok": False, "error": f"unknown or unregistered tool: {name}"}
        if spec.requires_approval and not approved:
            return {
                "ok": False,
                "needs_approval": True,
                "tool": name,
                "args": args or {},
                "error": "owner approval required before execution",
            }
        try:
            result = self.handlers[name](**(args or {}))
            return {"ok": True, "tool": name, "result": result}
        except TypeError:
            # Some heart callbacks take no kwargs
            try:
                result = self.handlers[name]()
                return {"ok": True, "tool": name, "result": result}
            except Exception as exc:
                return {"ok": False, "tool": name, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "tool": name, "error": str(exc)}


DEFAULT_TOOLS: list[ToolSpec] = [
    ToolSpec("health_check", "Run PFAI /health snapshot", "read", False, {}),
    ToolSpec("system_status", "Full system status (health, metrics, recovery, continuous gate)", "read", False, {}),
    ToolSpec("metrics_snapshot", "Current metrics counters and latency", "read", False, {}),
    ToolSpec("modules_list", "List registered capability modules", "read", False, {}),
    ToolSpec("continuous_status", "Continuous learning service status + safety gate", "read", False, {}),
    ToolSpec("deployments_list", "Deployment history", "read", False, {}),
    ToolSpec("knowledge_search", "Search vector knowledge store", "read", False, {"q": "string", "limit": "int?"}),
    ToolSpec("memory_search", "Search durable memory", "read", False, {"q": "string", "limit": "int?"}),
    ToolSpec("recovery_verify", "Verify recovery ledger integrity", "read", False, {}),
    ToolSpec("research_verify", "Verify research ledger + network policy", "read", False, {}),
    ToolSpec("regression_pending", "List pending regression cases", "read", False, {}),
    ToolSpec("chat_audit_recent", "Recent command-chat audit events", "read", False, {"limit": "int?"}),
    ToolSpec("propose_improvement", "Draft an improvement suggestion (no mutation)", "read", False, {"topic": "string?"}),
    # Sensitive — Owner Gate
    ToolSpec("continuous_start", "Start continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_pause", "Pause continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_resume", "Resume continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_stop", "Stop continuous learning service", "sensitive", True, {}),
    ToolSpec("remember_knowledge", "Persist approved knowledge/preference/decision", "write", True, {"kind": "string", "content": "string"}),
    ToolSpec("forget_memory", "Forget/delete a durable memory id", "sensitive", True, {"memory_id": "int"}),
    ToolSpec("correct_memory", "Correct an existing durable memory id", "write", True, {"memory_id": "int", "content": "string"}),
    ToolSpec("save_owner_correction", "Save an owner correction as durable learning", "write", True, {"content": "string"}),
]
