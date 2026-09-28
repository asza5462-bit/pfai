"""PHASE 12 MCP / external tool adapter — provider-agnostic, untrusted by default."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pfai.authorized_execution import AuthorizedExecutor, PermissionGate
from pfai.elite.tool_fabric import ToolFabric
from pfai.elite.types import ToolDefinition
from pfai.interfaces.tools import ToolPermission


@dataclass
class ExternalToolDescriptor:
    external_id: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    transport: str = "mcp_like"
    endpoint: str = ""
    trusted: bool = False  # ALWAYS false unless explicitly set by owner
    permissions_required: str = ToolPermission.HIGH_RISK_WRITE.value
    meta: dict[str, Any] = field(default_factory=dict)


class MCPAdapter:
    """Abstraction for external tool protocols (MCP-like). Untrusted by default."""

    def __init__(
        self,
        path: str = "data/longevity/mcp_adapter.json",
        *,
        executor: AuthorizedExecutor | None = None,
        fabric: ToolFabric | None = None,
        invokers: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.fabric = fabric
        self.invokers = dict(invokers or {})
        self._lock = threading.RLock()
        self._tools: dict[str, ExternalToolDescriptor] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for row in data.get("tools") or []:
            desc = ExternalToolDescriptor(**{k: row[k] for k in ExternalToolDescriptor.__dataclass_fields__ if k in row})  # type: ignore[attr-defined]
            # Force untrusted unless explicitly stored trusted AND owner-approved flag
            if not row.get("owner_approved_trust"):
                desc.trusted = False
            self._tools[desc.external_id] = desc

    def _save(self) -> None:
        payload = {
            "tools": [
                {
                    **t.__dict__,
                    "owner_approved_trust": bool(t.trusted),
                }
                for t in self._tools.values()
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def discover(self, descriptors: list[ExternalToolDescriptor] | None = None) -> dict[str, Any]:
        """Register discovered external descriptors as untrusted candidates."""
        found = list(descriptors or [])
        with self._lock:
            for d in found:
                d.trusted = False
                d.permissions_required = d.permissions_required or ToolPermission.HIGH_RISK_WRITE.value
                self._tools[d.external_id] = d
            self._save()
        return {
            "ok": True,
            "count": len(found),
            "tools": [t.__dict__ for t in found],
            "default_trust": False,
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [t.__dict__ for t in self._tools.values()]

    def inspect(self, external_id: str) -> dict[str, Any]:
        t = self._tools.get(external_id)
        if not t:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "tool": t.__dict__, "trusted": t.trusted}

    def approve_trust(self, external_id: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required to trust external tool"}
        t = self._tools.get(external_id)
        if not t:
            return {"ok": False, "error": "not_found"}
        t.trusted = True
        with self._lock:
            self._save()
        self.executor.audit.record(
            kind="mcp_trust",
            name=external_id,
            permission=ToolPermission.HIGH_RISK_WRITE,
            allowed=True,
            approved=True,
            actor=actor,
            reason="external_tool_trusted",
        )
        return {"ok": True, "external_id": external_id, "trusted": True}

    def register_into_fabric(self, external_id: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required"}
        t = self._tools.get(external_id)
        if not t:
            return {"ok": False, "error": "not_found"}
        if not t.trusted:
            return {"ok": False, "error": "external_tool_untrusted"}
        if self.fabric is None:
            return {"ok": False, "error": "fabric_unavailable"}

        invoker = self.invokers.get(external_id)
        if invoker is None:
            # Default fail-closed invoker
            def invoker(**_kwargs: Any) -> dict[str, Any]:
                return {"ok": False, "error": "external_invoker_not_configured"}

        definition = ToolDefinition(
            tool_id=f"ext_{t.external_id}",
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            output_schema=t.output_schema,
            capabilities=["external", t.transport],
            permissions_required=t.permissions_required,
            risk_level="high",
            execution_environment="external",
            enabled=True,
            health="unknown",
            provenance={"external_id": t.external_id, "trusted": t.trusted, "actor": actor},
        )
        return self.fabric.register(definition, invoker, activate=True)

    def invoke(
        self,
        external_id: str,
        args: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        actor: str = "",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        t = self._tools.get(external_id)
        if not t:
            return {"ok": False, "error": "not_found"}
        if not t.trusted:
            return {"ok": False, "error": "refused_untrusted_external_tool"}
        invoker = self.invokers.get(external_id)
        if invoker is None:
            return {"ok": False, "error": "invoker_missing"}
        try:
            perm = ToolPermission(t.permissions_required)
        except Exception:
            perm = ToolPermission.HIGH_RISK_WRITE
        started = time.time()
        if time.time() - started > timeout:
            return {"ok": False, "error": "timeout"}
        result = self.executor.execute(
            kind="mcp_tool",
            name=external_id,
            permission=perm,
            handler=lambda **_k: invoker(**(args or {})),
            args=args or {},
            approved=bool(approved) if perm.requires_owner_gate() else True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return {"ok": False, "needs_approval": True, "error": result.get("error")}
        return {
            "ok": bool(result.get("ok")),
            "result": result.get("result"),
            "error": result.get("error"),
            "latency_seconds": time.time() - started,
            "external_id": external_id,
        }

    def health(self) -> dict[str, Any]:
        tools = self.list_tools()
        trusted = sum(1 for t in tools if t.get("trusted"))
        return {
            "ok": True,
            "MCP_STATUS": "READY",
            "tool_count": len(tools),
            "trusted_count": trusted,
            "untrusted_default": True,
            "authorization_bypass": False,
            "note": "Untrusted MCP servers remain untrusted until owner approval",
        }

    def discover_capabilities(self) -> dict[str, Any]:
        """Capability discovery over registered descriptors (schema + permissions)."""
        caps = []
        for t in self.list_tools():
            caps.append(
                {
                    "external_id": t.get("external_id"),
                    "name": t.get("name"),
                    "description": t.get("description"),
                    "input_schema": t.get("input_schema") or {},
                    "permissions_required": t.get("permissions_required"),
                    "trusted": bool(t.get("trusted")),
                    "timeout_default": 10.0,
                }
            )
        return {"ok": True, "capabilities": caps, "count": len(caps), "untrusted_default": True}
