"""Versioned SkillRegistry (PHASE 4).

Keeps prior skill versions invokable; activate/rollback via audited active pointer.
Handlers remain in-process (no dynamic code loading from disk/network).
HIGH_RISK_WRITE+ requires explicit owner approval via AuthorizedExecutor.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.migration import PFAI_SCHEMA_VERSION
from pfai.interfaces.skills import Skill, SkillContext, SkillResult
from pfai.interfaces.tools import ToolPermission
from pfai.interfaces.versioning import VersionStatus
from pfai.authorized_execution import AuthorizedExecutor, PermissionGate

__all__ = ["SkillRegistry", "Skill", "SkillContext", "SkillResult"]

PHASE = 4

Handler = Callable[..., Any]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class SkillRegistry:
    """Name → versioned (Skill, handler) registry with durable metadata."""

    def __init__(
        self,
        path: str = "data/longevity/skill_versions.sqlite3",
        *,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self._lock = threading.RLock()
        self._handlers: dict[tuple[str, str], Handler] = {}
        self._skills: dict[tuple[str, str], Skill] = {}
        self._compat: dict[tuple[str, str], dict[str, Any]] = {}
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_versions (
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT,
                    permission TEXT,
                    status TEXT,
                    changelog TEXT,
                    min_schema_version INTEGER,
                    offline_ok INTEGER,
                    provider_kinds TEXT,
                    meta TEXT,
                    created_at TEXT,
                    PRIMARY KEY (name, version)
                );
                CREATE TABLE IF NOT EXISTS skill_active (
                    name TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at TEXT
                );
                """
            )
            self.db.commit()

    def register(self, skill: Skill, handler: Handler) -> None:
        """Register (or replace) a skill version and mark it active."""
        self.register_version(skill, handler, activate=True)

    def register_version(
        self,
        skill: Skill,
        handler: Handler,
        *,
        activate: bool = False,
        min_schema_version: int = 1,
        offline_ok: bool = True,
        provider_kinds: list[str] | None = None,
        changelog: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        if not skill.name:
            raise ValueError("skill.name required")
        if skill.permission not in ToolPermission:
            raise ValueError(f"invalid permission: {skill.permission}")
        version = skill.version or "1"
        key = (skill.name, version)
        meta_d = dict(meta or {})
        min_schema = int(meta_d.get("min_schema_version") or min_schema_version or 1)
        offline = bool(meta_d.get("offline_ok", offline_ok))
        kinds = list(meta_d.get("provider_kinds") or provider_kinds or [])
        with self._lock:
            self._skills[key] = skill
            self._handlers[key] = handler
            self._compat[key] = {
                "min_schema_version": min_schema,
                "offline_ok": offline,
                "provider_kinds": kinds,
            }
            self.db.execute(
                """INSERT OR REPLACE INTO skill_versions
                   (name, version, description, permission, status, changelog,
                    min_schema_version, offline_ok, provider_kinds, meta, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    skill.name,
                    version,
                    skill.description,
                    skill.permission.value,
                    VersionStatus.ACTIVE.value if activate else VersionStatus.DRAFT.value,
                    changelog or meta_d.get("changelog") or "",
                    min_schema,
                    1 if offline else 0,
                    json.dumps(kinds),
                    json.dumps(meta_d, ensure_ascii=False),
                    _now(),
                ),
            )
            if activate:
                self._set_active_unlocked(skill.name, version)
            self.db.commit()

    def _set_active_unlocked(self, name: str, version: str) -> None:
        self.db.execute(
            "UPDATE skill_versions SET status=? WHERE name=? AND status=?",
            (VersionStatus.SUPERSEDED.value, name, VersionStatus.ACTIVE.value),
        )
        self.db.execute(
            "UPDATE skill_versions SET status=? WHERE name=? AND version=?",
            (VersionStatus.ACTIVE.value, name, version),
        )
        self.db.execute(
            "INSERT OR REPLACE INTO skill_active(name, version, updated_at) VALUES (?,?,?)",
            (name, version, _now()),
        )

    def list_skills(self) -> list[Skill]:
        """Active skills only (latest active pointer)."""
        out: list[Skill] = []
        with self._lock:
            rows = self.db.execute("SELECT name, version FROM skill_active").fetchall()
        for name, version in rows:
            skill = self.get_version(name, version)
            if skill:
                out.append(skill)
        # Include in-memory-only registrations not yet flushed (tests)
        if not out:
            seen = set()
            for (name, ver), skill in self._skills.items():
                if name in seen:
                    continue
                active = self.active_version(name)
                if active == ver or active is None:
                    out.append(skill)
                    seen.add(name)
        return out

    def get(self, name: str) -> Skill | None:
        ver = self.active_version(name)
        if ver:
            return self.get_version(name, ver)
        # fallback latest registered
        versions = self.list_versions(name)
        return versions[-1] if versions else None

    def get_version(self, name: str, version: str) -> Skill | None:
        return self._skills.get((name, version))

    def list_versions(self, name: str) -> list[Skill]:
        items = [s for (n, _), s in self._skills.items() if n == name]
        items.sort(key=lambda s: s.version)
        return items

    def active_version(self, name: str) -> str | None:
        with self._lock:
            row = self.db.execute("SELECT version FROM skill_active WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def activate(self, name: str, version: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required to activate skill version"}
        if (name, version) not in self._skills:
            return {"ok": False, "error": "skill version not found"}
        with self._lock:
            self._set_active_unlocked(name, version)
            self.db.commit()
        self.executor.audit.record(
            kind="skill_activate",
            name=f"{name}@{version}",
            permission=ToolPermission.HIGH_RISK_WRITE,
            allowed=True,
            approved=True,
            actor=actor,
            reason="skill version activated",
        )
        return {"ok": True, "name": name, "version": version, "status": "active"}

    def rollback(self, name: str, to_version: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        return self.activate(name, to_version, approved=approved, actor=actor)

    def _compat_ok(self, name: str, version: str) -> tuple[bool, str]:
        meta = self._compat.get((name, version)) or {}
        min_schema = int(meta.get("min_schema_version") or 1)
        if min_schema > int(PFAI_SCHEMA_VERSION):
            return False, f"incompatible: skill requires schema>={min_schema}, platform={PFAI_SCHEMA_VERSION}"
        return True, "ok"

    def invoke(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        ctx: SkillContext | None = None,
        approved: bool = False,
        actor: str = "",
        version: str | None = None,
    ) -> SkillResult:
        ver = version or self.active_version(name)
        if not ver:
            # last resort: any registered
            vers = self.list_versions(name)
            if not vers:
                return SkillResult(ok=False, error=f"unknown skill: {name}")
            ver = vers[-1].version
        return self.invoke_version(name, ver, args, ctx=ctx, approved=approved, actor=actor)

    def invoke_version(
        self,
        name: str,
        version: str,
        args: dict[str, Any] | None = None,
        *,
        ctx: SkillContext | None = None,
        approved: bool = False,
        actor: str = "",
    ) -> SkillResult:
        skill = self._skills.get((name, version))
        handler = self._handlers.get((name, version))
        if not skill or not handler:
            return SkillResult(ok=False, error=f"unknown skill version: {name}@{version}")
        ok_compat, reason = self._compat_ok(name, version)
        if not ok_compat:
            self.executor.audit.record(
                kind="skill",
                name=f"{name}@{version}",
                permission=skill.permission,
                allowed=False,
                approved=approved,
                actor=actor,
                reason=reason,
                args=args,
            )
            return SkillResult(ok=False, error=reason, meta={"compatibility": False, "skill": name, "version": version})

        def _run(**_kwargs: Any) -> Any:
            try:
                return handler(**(args or {}), ctx=ctx or SkillContext())
            except TypeError:
                return handler(**(args or {}))

        # HIGH_RISK+ must have approved=True; READ may run without.
        needs = skill.permission.requires_owner_gate()
        result = self.executor.execute(
            kind="skill",
            name=f"{name}@{version}",
            permission=skill.permission,
            handler=_run,
            args=args or {},
            approved=bool(approved) if needs else True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return SkillResult(
                ok=False,
                error="owner approval required before skill execution",
                meta={
                    "needs_approval": True,
                    "skill": name,
                    "version": version,
                    "permission": skill.permission.value,
                    "decision_id": result.get("decision_id"),
                },
            )
        if not result.get("ok"):
            return SkillResult(
                ok=False,
                error=result.get("error"),
                meta={"skill": name, "version": version, "decision_id": result.get("decision_id")},
            )
        return SkillResult(
            ok=True,
            output=result.get("result"),
            meta={"skill": name, "version": version, "decision_id": result.get("decision_id")},
        )
