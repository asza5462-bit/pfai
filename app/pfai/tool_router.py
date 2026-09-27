"""Tool Router — Brain calls tools; Heart (PFAI core) executes them.

PHASE 4: ToolPermission ladder + AuthorizedExecutor choke-point.
Sensitive tools never auto-run: Owner approval required for HIGH_RISK_WRITE+.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pfai.interfaces.tools import ToolPermission
from pfai.authorized_execution import AuthorizedExecutor, PermissionGate, risk_to_permission


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str  # legacy: read | write | sensitive
    requires_approval: bool
    args_schema: dict
    permission: ToolPermission | None = None
    version: str = "1"
    min_schema_version: int = 1
    offline_ok: bool = True
    provider_kinds: tuple[str, ...] = ()

    def resolved_permission(self) -> ToolPermission:
        if self.permission is not None:
            return self.permission
        return risk_to_permission(self.risk, name=self.name, requires_approval=self.requires_approval)


class ToolRouter:
    """Dispatch whitelist tools to injected heart callbacks via AuthorizedExecutor."""

    def __init__(
        self,
        handlers: dict[str, Callable[..., Any]],
        specs: list[ToolSpec] | None = None,
        *,
        executor: AuthorizedExecutor | None = None,
    ):
        self.handlers = dict(handlers)
        self.specs = {s.name: s for s in (specs or DEFAULT_TOOLS)}
        self.executor = executor or AuthorizedExecutor(PermissionGate())

    def catalog(self) -> list[dict]:
        out = []
        for s in self.specs.values():
            if s.name not in self.handlers:
                continue
            perm = s.resolved_permission()
            out.append(
                {
                    "name": s.name,
                    "description": s.description,
                    "risk": s.risk,
                    "requires_approval": s.requires_approval or perm.requires_owner_gate(),
                    "permission": perm.value,
                    "version": s.version,
                    "args_schema": s.args_schema,
                    "min_schema_version": s.min_schema_version,
                    "offline_ok": s.offline_ok,
                }
            )
        return out

    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

    def requires_approval(self, name: str) -> bool:
        spec = self.specs.get(name)
        if not spec:
            return False
        return bool(spec.requires_approval or spec.resolved_permission().requires_owner_gate())

    def execute(
        self,
        name: str,
        args: dict | None = None,
        *,
        approved: bool = False,
        actor: str = "",
    ) -> dict:
        spec = self.specs.get(name)
        if not spec or name not in self.handlers:
            return {"ok": False, "error": f"unknown or unregistered tool: {name}"}
        perm = spec.resolved_permission()
        # HIGH_RISK_WRITE+ always needs explicit approval (even if legacy flag was loose).
        needs = perm.requires_owner_gate() or spec.requires_approval
        result = self.executor.execute(
            kind="tool",
            name=name,
            permission=perm,
            handler=self.handlers[name],
            args=args or {},
            approved=bool(approved) if needs else True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return {
                "ok": False,
                "needs_approval": True,
                "tool": name,
                "args": args or {},
                "error": result.get("error") or "owner approval required before execution",
                "permission": perm.value,
                "decision_id": result.get("decision_id"),
            }
        if not result.get("ok"):
            return {
                "ok": False,
                "tool": name,
                "error": result.get("error"),
                "permission": perm.value,
                "decision_id": result.get("decision_id"),
            }
        return {
            "ok": True,
            "tool": name,
            "result": result.get("result"),
            "permission": perm.value,
            "decision_id": result.get("decision_id"),
        }


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
    # Sensitive — Owner Gate (HIGH_RISK_WRITE+)
    ToolSpec("continuous_start", "Start continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_pause", "Pause continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_resume", "Resume continuous learning service", "sensitive", True, {}),
    ToolSpec("continuous_stop", "Stop continuous learning service", "sensitive", True, {}),
    ToolSpec("remember_knowledge", "Persist approved knowledge/preference/decision", "write", True, {"kind": "string", "content": "string"}),
    ToolSpec("forget_memory", "Forget/delete a durable memory id", "sensitive", True, {"memory_id": "int"}),
    ToolSpec("correct_memory", "Correct an existing durable memory id", "write", True, {"memory_id": "int", "content": "string"}),
    ToolSpec("save_owner_correction", "Save an owner correction as durable learning", "write", True, {"content": "string"}),
]
