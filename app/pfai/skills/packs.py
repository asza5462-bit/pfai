"""Skill Pack registry — versioned groups of skills with enable/disable/rollback.

Skills never bypass AuthorizedExecutor / owner auth.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pfai.authorized_execution import AuthorizedExecutor, PermissionGate
from pfai.interfaces.tools import ToolPermission


@dataclass
class SkillPackVersion:
    pack_id: str
    version: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    permission: str = ToolPermission.READ.value
    status: str = "registered"
    changelog: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SkillPackRegistry:
    def __init__(
        self,
        path: str = "data/longevity/skill_packs.sqlite3",
        *,
        executor: AuthorizedExecutor | None = None,
        skill_registry: Any | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.skill_registry = skill_registry
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_packs (
                    pack_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT,
                    skills TEXT,
                    permission TEXT,
                    status TEXT,
                    changelog TEXT,
                    meta TEXT,
                    created_at REAL,
                    PRIMARY KEY (pack_id, version)
                );
                CREATE TABLE IF NOT EXISTS skill_pack_active (
                    pack_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL,
                    previous_version TEXT
                );
                """
            )
            self.db.commit()

    def register_pack(self, pack: SkillPackVersion, *, activate: bool = False) -> dict[str, Any]:
        pack.created_at = pack.created_at or time.time()
        # Skills cannot self-elevate: clamp to known permissions
        try:
            ToolPermission(pack.permission)
        except Exception:
            pack.permission = ToolPermission.READ.value
        with self._lock:
            self.db.execute(
                """INSERT OR REPLACE INTO skill_packs
                   (pack_id, version, description, skills, permission, status, changelog, meta, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    pack.pack_id,
                    pack.version,
                    pack.description,
                    json.dumps(pack.skills),
                    pack.permission,
                    pack.status,
                    pack.changelog,
                    json.dumps(pack.meta or {}),
                    pack.created_at,
                ),
            )
            self.db.commit()
        if activate:
            return self.activate(pack.pack_id, pack.version, approved=True, actor="system")
        return {"ok": True, "pack": pack.to_dict()}

    def list_packs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT pack_id, version, description, skills, permission, status, created_at FROM skill_packs ORDER BY pack_id, version"
            ).fetchall()
            active = {
                r[0]: {"version": r[1], "enabled": bool(r[2])}
                for r in self.db.execute(
                    "SELECT pack_id, version, enabled FROM skill_pack_active"
                ).fetchall()
            }
        out = []
        for r in rows:
            item = {
                "pack_id": r[0],
                "version": r[1],
                "description": r[2],
                "skills": json.loads(r[3] or "[]"),
                "permission": r[4],
                "status": r[5],
                "created_at": r[6],
                "active": active.get(r[0], {}).get("version") == r[1],
                "enabled": active.get(r[0], {}).get("enabled", False) if active.get(r[0], {}).get("version") == r[1] else False,
            }
            out.append(item)
        return out

    def get(self, pack_id: str, version: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if version is None:
                row = self.db.execute(
                    "SELECT version FROM skill_pack_active WHERE pack_id=?", (pack_id,)
                ).fetchone()
                if not row:
                    return None
                version = row[0]
            r = self.db.execute(
                "SELECT pack_id, version, description, skills, permission, status, changelog, meta, created_at FROM skill_packs WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
        if not r:
            return None
        return {
            "pack_id": r[0],
            "version": r[1],
            "description": r[2],
            "skills": json.loads(r[3] or "[]"),
            "permission": r[4],
            "status": r[5],
            "changelog": r[6],
            "meta": json.loads(r[7] or "{}"),
            "created_at": r[8],
        }

    def activate(
        self,
        pack_id: str,
        version: str,
        *,
        approved: bool = False,
        actor: str = "",
        enable: bool = True,
    ) -> dict[str, Any]:
        # HIGH_RISK packs need approval via executor gate
        pack = self.get(pack_id, version)
        if not pack:
            return {"ok": False, "error": "pack_not_found"}
        perm = pack.get("permission") or ToolPermission.READ.value
        if perm in (
            ToolPermission.HIGH_RISK_WRITE.value,
            ToolPermission.PRODUCTION.value,
            ToolPermission.SECRETS.value,
            ToolPermission.DATA_DELETE.value,
        ) and not approved:
            return {"ok": False, "error": "owner_approval_required", "needs_approval": True}
        # Never allow pack to claim SECRETS/auth permissions beyond registered value —
        # executor still gates each skill invoke separately.
        with self._lock:
            prev = self.db.execute(
                "SELECT version FROM skill_pack_active WHERE pack_id=?", (pack_id,)
            ).fetchone()
            previous = prev[0] if prev else None
            self.db.execute(
                """INSERT INTO skill_pack_active(pack_id, version, enabled, updated_at, previous_version)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(pack_id) DO UPDATE SET
                     version=excluded.version,
                     enabled=excluded.enabled,
                     updated_at=excluded.updated_at,
                     previous_version=excluded.previous_version
                """,
                (pack_id, version, 1 if enable else 0, time.time(), previous),
            )
            self.db.commit()
        return {"ok": True, "pack_id": pack_id, "version": version, "enabled": enable, "previous_version": previous, "actor": actor}

    def rollback(self, pack_id: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        with self._lock:
            row = self.db.execute(
                "SELECT previous_version FROM skill_pack_active WHERE pack_id=?", (pack_id,)
            ).fetchone()
        if not row or not row[0]:
            return {"ok": False, "error": "no_previous_version"}
        return self.activate(pack_id, row[0], approved=approved, actor=actor)

    def set_enabled(self, pack_id: str, enabled: bool, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        with self._lock:
            row = self.db.execute(
                "SELECT version FROM skill_pack_active WHERE pack_id=?", (pack_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "pack_not_active"}
            self.db.execute(
                "UPDATE skill_pack_active SET enabled=?, updated_at=? WHERE pack_id=?",
                (1 if enabled else 0, time.time(), pack_id),
            )
            self.db.commit()
        return {"ok": True, "pack_id": pack_id, "enabled": enabled, "actor": actor}

    def bootstrap_defaults(self) -> None:
        defaults = [
            SkillPackVersion(
                pack_id="coding",
                version="1.0.0",
                description="Coding / debugging / review skills",
                skills=["coding_teach", "coding_review", "coding_assess"],
                permission=ToolPermission.LOW_RISK_WRITE.value,
            ),
            SkillPackVersion(
                pack_id="planning",
                version="1.0.0",
                description="Planning and task decomposition",
                skills=["plan"],
                permission=ToolPermission.READ.value,
            ),
            SkillPackVersion(
                pack_id="knowledge",
                version="1.0.0",
                description="Knowledge management and retrieval",
                skills=["knowledge_search", "remember_knowledge"],
                permission=ToolPermission.LOW_RISK_WRITE.value,
            ),
            SkillPackVersion(
                pack_id="training_ops",
                version="1.0.0",
                description="Training observability helpers (no auth mutation)",
                skills=["training_status"],
                permission=ToolPermission.READ.value,
            ),
            SkillPackVersion(
                pack_id="evaluation",
                version="1.0.0",
                description="Model evaluation helpers",
                skills=["eval_run"],
                permission=ToolPermission.READ.value,
            ),
        ]
        for pack in defaults:
            existing = self.get(pack.pack_id, pack.version)
            if not existing:
                self.register_pack(pack, activate=True)


def skill_cannot_elevate(requested_permission: str, registered_permission: str) -> bool:
    """Return True if requested permission is an illegal elevation."""
    order = [
        ToolPermission.READ.value,
        ToolPermission.LOW_RISK_WRITE.value,
        ToolPermission.HIGH_RISK_WRITE.value,
        ToolPermission.PRODUCTION.value,
        ToolPermission.SECRETS.value,
        ToolPermission.DATA_DELETE.value,
    ]
    try:
        return order.index(requested_permission) > order.index(registered_permission)
    except ValueError:
        return True
