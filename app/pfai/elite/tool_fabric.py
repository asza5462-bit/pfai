"""PHASE 12 Tool Fabric — discovery/selection/validation/execution via AuthorizedExecutor."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from pfai.authorized_execution import AuthorizedExecutor, PermissionGate
from pfai.elite.types import RiskLevel, ToolDefinition, now_ts
from pfai.interfaces.tools import ToolPermission
from pfai.tool_router import ToolRouter


Handler = Callable[..., Any]


class ToolFabric:
    def __init__(
        self,
        path: str = "data/longevity/tool_fabric.sqlite3",
        *,
        executor: AuthorizedExecutor | None = None,
        tool_router: ToolRouter | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.tool_router = tool_router
        self._handlers: dict[tuple[str, str], Handler] = {}
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tools (
                    tool_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL,
                    updated_at REAL,
                    PRIMARY KEY (tool_id, version)
                );
                CREATE TABLE IF NOT EXISTS tool_active (
                    tool_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at REAL
                );
                """
            )
            self.db.commit()

    def _perm(self, value: str) -> ToolPermission:
        try:
            return ToolPermission(value)
        except Exception:
            return ToolPermission.READ

    def register(self, definition: ToolDefinition, handler: Handler, *, activate: bool = True) -> dict[str, Any]:
        definition.created_at = definition.created_at or now_ts()
        definition.updated_at = now_ts()
        with self._lock:
            exists = self.db.execute(
                "SELECT 1 FROM tools WHERE tool_id=? AND version=?",
                (definition.tool_id, definition.version),
            ).fetchone()
            if exists:
                return {"ok": False, "error": "version_already_exists"}
            self.db.execute(
                "INSERT INTO tools(tool_id, version, definition, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (
                    definition.tool_id,
                    definition.version,
                    json.dumps(definition.to_dict(), ensure_ascii=False),
                    1 if definition.enabled else 0,
                    definition.created_at,
                    definition.updated_at,
                ),
            )
            self._handlers[(definition.tool_id, definition.version)] = handler
            if activate:
                self.db.execute(
                    "INSERT OR REPLACE INTO tool_active(tool_id, version, updated_at) VALUES (?,?,?)",
                    (definition.tool_id, definition.version, now_ts()),
                )
            self.db.commit()
        return {"ok": True, "tool_id": definition.tool_id, "version": definition.version}

    def get(self, tool_id: str, version: str | None = None) -> ToolDefinition | None:
        with self._lock:
            if version is None:
                row = self.db.execute(
                    "SELECT version FROM tool_active WHERE tool_id=?", (tool_id,)
                ).fetchone()
                if not row:
                    return None
                version = row[0]
            r = self.db.execute(
                "SELECT definition, enabled FROM tools WHERE tool_id=? AND version=?",
                (tool_id, version),
            ).fetchone()
        if not r:
            return None
        d = ToolDefinition.from_dict(json.loads(r[0]))
        d.enabled = bool(r[1])
        return d

    def catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT a.tool_id, a.version, t.definition, t.enabled FROM tool_active a "
                "JOIN tools t ON t.tool_id=a.tool_id AND t.version=a.version"
            ).fetchall()
        out = []
        for tid, ver, blob, enabled in rows:
            d = json.loads(blob)
            d["enabled"] = bool(enabled)
            d["active_version"] = ver
            out.append(d)
        # Merge legacy tool router catalog if present
        if self.tool_router is not None:
            for item in self.tool_router.catalog():
                if not any(x.get("tool_id") == item.get("name") or x.get("name") == item.get("name") for x in out):
                    out.append(
                        {
                            "tool_id": item["name"],
                            "name": item["name"],
                            "version": item.get("version") or "1",
                            "description": item.get("description"),
                            "permissions_required": item.get("permission"),
                            "source": "legacy_tool_router",
                            "enabled": True,
                        }
                    )
        return out

    def discover(self, need: str) -> dict[str, Any]:
        need_l = (need or "").lower()
        matches = []
        for t in self.catalog():
            blob = json.dumps(t).lower()
            if need_l and need_l not in blob:
                continue
            matches.append(t)
        return {"ok": True, "matches": matches, "untrusted_external_default": True}

    def select(self, need: str) -> dict[str, Any]:
        disc = self.discover(need)
        matches = disc.get("matches") or []
        # lowest risk first
        def risk_rank(t: dict[str, Any]) -> int:
            r = str(t.get("risk_level") or "low")
            return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(r, 9)

        matches = sorted(matches, key=risk_rank)
        return {"ok": True, "selected": matches[:1], "rationale": ["capability_match", "lowest_risk_first"], "all": matches}

    def validate_args(self, tool_id: str, args: dict[str, Any] | None) -> dict[str, Any]:
        d = self.get(tool_id)
        if not d and self.tool_router and self.tool_router.get(tool_id):
            return {"ok": True, "legacy": True}
        if not d:
            return {"ok": False, "error": "unknown_tool"}
        if not d.enabled:
            return {"ok": False, "error": "tool_disabled"}
        required = list((d.input_schema or {}).get("required") or [])
        missing = [k for k in required if k not in (args or {})]
        return {"ok": not missing, "missing": missing, "schema": d.input_schema}

    def execute(
        self,
        tool_id: str,
        args: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        actor: str = "",
        version: str | None = None,
    ) -> dict[str, Any]:
        # Prefer fabric handler; else legacy router
        d = self.get(tool_id, version)
        if d is None and self.tool_router is not None and self.tool_router.get(tool_id):
            return self.tool_router.execute(tool_id, args, approved=approved, actor=actor)
        if d is None:
            return {"ok": False, "error": f"unknown tool: {tool_id}"}
        if not d.enabled:
            return {"ok": False, "error": "tool_disabled"}
        validation = self.validate_args(tool_id, args)
        if not validation.get("ok"):
            return {"ok": False, "error": "schema_validation_failed", "validation": validation}
        handler = self._handlers.get((tool_id, d.version))
        if not handler:
            return {"ok": False, "error": "handler_missing"}
        perm = self._perm(d.permissions_required)
        needs = perm.requires_owner_gate()
        started = time.time()
        result = self.executor.execute(
            kind="tool",
            name=f"{tool_id}@{d.version}",
            permission=perm,
            handler=lambda **_k: handler(**(args or {})),
            args=args or {},
            approved=bool(approved) if needs else True,
            actor=actor,
        )
        elapsed = time.time() - started
        if result.get("needs_approval"):
            return {
                "ok": False,
                "needs_approval": True,
                "tool_id": tool_id,
                "error": result.get("error"),
                "permission": perm.value,
            }
        if not result.get("ok"):
            return {
                "ok": False,
                "tool_id": tool_id,
                "error": result.get("error"),
                "latency_seconds": elapsed,
            }
        out = result.get("result")
        verified = self.validate_result(out, d.output_schema)
        return {
            "ok": True,
            "tool_id": tool_id,
            "version": d.version,
            "result": out,
            "latency_seconds": elapsed,
            "result_validation": verified,
        }

    def validate_result(self, result: Any, output_schema: dict[str, Any] | None) -> dict[str, Any]:
        if not output_schema:
            return {"ok": True, "checked": False}
        required = list((output_schema or {}).get("required") or [])
        if not isinstance(result, dict):
            return {"ok": not required, "checked": True, "error": "result_not_object"}
        missing = [k for k in required if k not in result]
        return {"ok": not missing, "missing": missing, "checked": True}

    def bootstrap_safe_tools(self) -> dict[str, Any]:
        """Register a few safe built-in tools (no secrets, no auth mutation)."""
        defs = []

        def echo_tool(text: str = "", **_k: Any) -> dict[str, Any]:
            return {"ok": True, "echo": str(text)[:2000]}

        def hash_tool(text: str = "", **_k: Any) -> dict[str, Any]:
            import hashlib

            return {"ok": True, "sha256": hashlib.sha256(str(text).encode()).hexdigest()}

        def calc_tool(expression: str = "", **_k: Any) -> dict[str, Any]:
            from pfai.elite.elite_library import skill_numerical_reasoning

            return skill_numerical_reasoning(expression=expression)

        for tool_id, desc, handler, schema in [
            ("echo_text", "Echo text safely", echo_tool, {"required": ["text"], "properties": {"text": {"type": "string"}}}),
            ("sha256_text", "Hash text", hash_tool, {"required": ["text"], "properties": {"text": {"type": "string"}}}),
            ("safe_calc", "Safe arithmetic", calc_tool, {"required": ["expression"], "properties": {"expression": {"type": "string"}}}),
        ]:
            d = ToolDefinition(
                tool_id=tool_id,
                name=tool_id,
                description=desc,
                input_schema=schema,
                output_schema={"required": ["ok"]},
                capabilities=[tool_id, "safe"],
                permissions_required=ToolPermission.READ.value,
                risk_level=RiskLevel.LOW.value,
                enabled=True,
                health="healthy",
                provenance={"phase": 12},
            )
            r = self.register(d, handler, activate=True)
            defs.append(r)
        return {"ok": True, "tools": defs}
