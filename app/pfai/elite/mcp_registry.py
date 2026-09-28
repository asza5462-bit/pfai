"""PHASE 23 — Provider-neutral MCP server registry.

External MCP servers are untrusted until explicitly registered and owner-approved.
Never grants owner privileges automatically.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.mcp_adapter import ExternalToolDescriptor, MCPAdapter
from pfai.elite.types import new_id
from pfai.interfaces.tools import ToolPermission


@dataclass
class MCPServerRegistration:
    server_id: str
    name: str
    endpoint: str = ""
    transport: str = "mcp_like"
    trusted: bool = False
    enabled: bool = True
    meta: dict[str, Any] = field(default_factory=dict)
    registered_at: float = 0.0


class MCPServerRegistry:
    """Register / discover / isolate MCP servers; tools stay untrusted by default."""

    VERSION = "23.0.0"

    def __init__(
        self,
        path: str = "data/longevity/elite/mcp_servers.json",
        *,
        adapter: MCPAdapter | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter or MCPAdapter(path=str(self.path.parent / "mcp_adapter.json"))
        self._servers: dict[str, MCPServerRegistration] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("servers") or []:
            try:
                reg = MCPServerRegistration(**{k: row[k] for k in MCPServerRegistration.__dataclass_fields__ if k in row})
            except TypeError:
                continue
            # Force untrusted unless owner_approved_trust persisted
            if not row.get("owner_approved_trust"):
                reg.trusted = False
            self._servers[reg.server_id] = reg

    def _save(self) -> None:
        payload = {
            "servers": [
                {**asdict(s), "owner_approved_trust": bool(s.trusted)}
                for s in self._servers.values()
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_server(
        self,
        server_id: str,
        name: str,
        *,
        endpoint: str = "",
        transport: str = "mcp_like",
        approved: bool = False,
        actor: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not (server_id or "").strip():
            return {"ok": False, "error": "server_id_required"}
        reg = MCPServerRegistration(
            server_id=server_id.strip(),
            name=(name or server_id).strip(),
            endpoint=endpoint,
            transport=transport,
            trusted=False,  # never auto-trust
            enabled=True,
            meta={"registered_by": actor[:80], "privileges_granted": False},
            registered_at=time.time(),
        )
        if approved:
            # Even with approved flag, trust requires explicit approve_trust step
            reg.meta["registration_approved"] = True
        self._servers[reg.server_id] = reg
        self._save()
        discovered = []
        if tools:
            descs = []
            for t in tools:
                eid = str(t.get("external_id") or f"{server_id}.{t.get('name') or 'tool'}")
                descs.append(
                    ExternalToolDescriptor(
                        external_id=eid,
                        name=str(t.get("name") or eid),
                        description=str(t.get("description") or ""),
                        input_schema=dict(t.get("input_schema") or {}),
                        transport=transport,
                        endpoint=endpoint,
                        trusted=False,
                        permissions_required=str(
                            t.get("permissions_required") or ToolPermission.HIGH_RISK_WRITE.value
                        ),
                        meta={"server_id": server_id, "untrusted_default": True},
                    )
                )
            disc = self.adapter.discover(descs)
            discovered = disc.get("tools") or []
        return sanitize_args(
            {
                "ok": True,
                "server": asdict(reg),
                "trusted": False,
                "tools_discovered": len(discovered),
                "note": "MCP server registered untrusted; owner approve_trust required",
                "version": self.VERSION,
            }
        )

    def approve_server(self, server_id: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner_approval_required"}
        reg = self._servers.get(server_id)
        if not reg:
            return {"ok": False, "error": "not_found"}
        reg.trusted = True
        reg.meta["trusted_by"] = actor[:80]
        self._save()
        return {"ok": True, "server_id": server_id, "trusted": True, "privileges_granted": False}

    def list_servers(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self._servers.values()]

    def discover_capabilities(self) -> dict[str, Any]:
        caps = self.adapter.discover_capabilities()
        return {
            **caps,
            "servers": self.list_servers(),
            "server_count": len(self._servers),
            "untrusted_default": True,
            "version": self.VERSION,
        }

    def invoke(
        self,
        external_id: str,
        args: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        actor: str = "",
        timeout: float = 10.0,
        budget: dict[str, Any] | None = None,
        request_id: str = "",
        skill_id: str = "",
    ) -> dict[str, Any]:
        execution_id = new_id("mcpx")
        started = time.time()
        # Server-level trust check if tool maps to a known server
        tool = None
        for t in self.adapter.list_tools():
            if t.get("external_id") == external_id:
                tool = t
                break
        server_id = (tool or {}).get("meta", {}).get("server_id") if tool else None
        if server_id:
            srv = self._servers.get(server_id)
            if srv and not srv.trusted and not (tool or {}).get("trusted"):
                return {
                    "ok": False,
                    "error": "mcp_server_untrusted",
                    "execution_id": execution_id,
                    "request_id": request_id or "",
                    "authorization": {"allowed": False},
                }
        result = self.adapter.invoke(
            external_id,
            args,
            approved=approved,
            actor=actor,
            timeout=timeout,
        )
        return sanitize_args(
            {
                **result,
                "tool_id": external_id,
                "tool_version": "1.0.0",
                "skill_id": skill_id or None,
                "request_id": request_id or new_id("preq"),
                "execution_id": execution_id,
                "authorization": {"allowed": bool(result.get("ok")), "approved": approved},
                "budget": budget or {"timeout_seconds": timeout},
                "start_time": started,
                "end_time": time.time(),
                "result_status": "SUCCESS" if result.get("ok") else "FAILED",
                "failure_reason": result.get("error"),
                "provenance": {"layer": "mcp_registry", "untrusted_default": True},
                "privileges_granted": False,
                "version": self.VERSION,
            }
        )

    def health(self) -> dict[str, Any]:
        base = self.adapter.health()
        return {
            **base,
            "MCP_STATUS": "READY",
            "server_count": len(self._servers),
            "trusted_servers": sum(1 for s in self._servers.values() if s.trusted),
            "untrusted_default": True,
            "authorization_bypass": False,
            "version": self.VERSION,
        }
