"""PHASE 12 Skill Registry 2.0 — versioned definitions with promotion history.

Does not silently overwrite versions. Invoke path always goes through
AuthorizedExecutor via the existing SkillRegistry handlers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from pfai.authorized_execution import AuthorizedExecutor, PermissionGate
from pfai.elite.types import SkillDefinition, SkillStatus, new_id, now_ts
from pfai.interfaces.skills import Skill, SkillContext, SkillResult
from pfai.interfaces.tools import ToolPermission
from pfai.skills.registry import SkillRegistry

Handler = Callable[..., Any]


class SkillPromotionHistory:
    """Append-only skill promotion / rollback ledger."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record(self, event_type: str, **detail: Any) -> dict[str, Any]:
        row = {
            "event_type": event_type,
            "event_id": new_id("skhist"),
            "timestamp": now_ts(),
            **detail,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def list_events(self, skill_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if skill_id and row.get("skill_id") != skill_id:
                continue
            out.append(row)
        return out

    def previous_version(self, skill_id: str, current_version: str) -> str | None:
        for ev in reversed(self.list_events(skill_id)):
            if ev.get("event_type") != "PROMOTION":
                continue
            if ev.get("new_version") == current_version:
                return ev.get("previous_version")
        return None


class SkillRegistry2:
    """Production-grade versioned skill definitions + invoke via SkillRegistry."""

    def __init__(
        self,
        path: str = "data/longevity/skill_registry_v2.sqlite3",
        *,
        legacy: SkillRegistry | None = None,
        executor: AuthorizedExecutor | None = None,
        history_path: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.legacy = legacy or SkillRegistry(
            path=str(self.path.parent / "skill_versions_legacy_bridge.sqlite3"),
            executor=self.executor,
        )
        self.history = SkillPromotionHistory(
            history_path or str(self.path.parent / "skill_promotion_history.jsonl")
        )
        self._lock = threading.RLock()
        self._handlers: dict[tuple[str, str], Handler] = {}
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_definitions (
                    skill_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    created_at REAL,
                    updated_at REAL,
                    PRIMARY KEY (skill_id, version)
                );
                CREATE TABLE IF NOT EXISTS skill_active_v2 (
                    skill_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    previous_version TEXT,
                    lkg_version TEXT,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS skill_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    event TEXT,
                    skill_id TEXT,
                    version TEXT,
                    detail TEXT
                );
                """
            )
            self.db.commit()

    def _perm(self, value: str) -> ToolPermission:
        try:
            return ToolPermission(value)
        except Exception:
            return ToolPermission.READ

    def register(
        self,
        definition: SkillDefinition,
        handler: Handler,
        *,
        activate: bool = False,
    ) -> dict[str, Any]:
        """Register a new immutable version. Never overwrites an existing (id, version)."""
        if not definition.skill_id or not definition.version:
            return {"ok": False, "error": "skill_id_and_version_required"}
        definition.created_at = definition.created_at or now_ts()
        definition.updated_at = now_ts()
        with self._lock:
            exists = self.db.execute(
                "SELECT 1 FROM skill_definitions WHERE skill_id=? AND version=?",
                (definition.skill_id, definition.version),
            ).fetchone()
            if exists:
                return {
                    "ok": False,
                    "error": "version_already_exists",
                    "skill_id": definition.skill_id,
                    "version": definition.version,
                }
            status = SkillStatus.ACTIVE.value if activate else SkillStatus.DRAFT.value
            definition.status = status
            self.db.execute(
                """INSERT INTO skill_definitions
                   (skill_id, version, name, definition, enabled, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    definition.skill_id,
                    definition.version,
                    definition.name,
                    json.dumps(definition.to_dict(), ensure_ascii=False),
                    1 if definition.enabled else 0,
                    status,
                    definition.created_at,
                    definition.updated_at,
                ),
            )
            self._handlers[(definition.skill_id, definition.version)] = handler
            # Bridge to legacy SkillRegistry for AuthorizedExecutor invoke path
            legacy_skill = Skill(
                name=definition.skill_id,
                description=definition.description,
                permission=self._perm(definition.permissions_required),
                tags=tuple(definition.tags or definition.capabilities),
                version=definition.version,
            )
            self.legacy.register_version(
                legacy_skill,
                handler,
                activate=activate,
                changelog=f"phase12:{definition.category}",
                meta={
                    "skill_definition": definition.to_dict(),
                    "category": definition.category,
                    "risk_level": definition.risk_level,
                },
            )
            if activate:
                self._activate_unlocked(definition.skill_id, definition.version, reason="register_activate")
            self._audit("register", definition.skill_id, definition.version, {"activate": activate})
            self.db.commit()
        return {"ok": True, "skill_id": definition.skill_id, "version": definition.version, "activated": activate}

    def _activate_unlocked(self, skill_id: str, version: str, *, reason: str) -> None:
        row = self.db.execute(
            "SELECT version, previous_version, lkg_version FROM skill_active_v2 WHERE skill_id=?",
            (skill_id,),
        ).fetchone()
        prev = row[0] if row else None
        lkg = (row[2] if row and row[2] else prev) if row else None
        self.db.execute(
            """INSERT INTO skill_active_v2(skill_id, version, previous_version, lkg_version, updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(skill_id) DO UPDATE SET
                 version=excluded.version,
                 previous_version=excluded.previous_version,
                 lkg_version=COALESCE(skill_active_v2.lkg_version, excluded.lkg_version),
                 updated_at=excluded.updated_at
            """,
            (skill_id, version, prev, lkg or version, now_ts()),
        )
        self.db.execute(
            "UPDATE skill_definitions SET status=?, updated_at=? WHERE skill_id=? AND version=?",
            (SkillStatus.ACTIVE.value, now_ts(), skill_id, version),
        )
        if prev and prev != version:
            self.db.execute(
                "UPDATE skill_definitions SET status=?, updated_at=? WHERE skill_id=? AND version=?",
                (SkillStatus.SUPERSEDED.value, now_ts(), skill_id, prev),
            )
            self.history.record(
                "PROMOTION",
                skill_id=skill_id,
                previous_version=prev,
                new_version=version,
                previous_lkg=lkg,
                reason=reason,
            )

    def _audit(self, event: str, skill_id: str, version: str, detail: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO skill_audit(ts, event, skill_id, version, detail) VALUES (?,?,?,?,?)",
            (now_ts(), event, skill_id, version, json.dumps(detail, ensure_ascii=False)),
        )

    def get(self, skill_id: str, version: str | None = None) -> SkillDefinition | None:
        with self._lock:
            if version is None:
                row = self.db.execute(
                    "SELECT version FROM skill_active_v2 WHERE skill_id=?", (skill_id,)
                ).fetchone()
                if not row:
                    # latest by created_at
                    row = self.db.execute(
                        "SELECT version FROM skill_definitions WHERE skill_id=? ORDER BY created_at DESC LIMIT 1",
                        (skill_id,),
                    ).fetchone()
                if not row:
                    return None
                version = row[0]
            r = self.db.execute(
                "SELECT definition FROM skill_definitions WHERE skill_id=? AND version=?",
                (skill_id, version),
            ).fetchone()
        if not r:
            return None
        return SkillDefinition.from_dict(json.loads(r[0]))

    def list_skills(self, *, enabled_only: bool = True, category: str | None = None) -> list[SkillDefinition]:
        with self._lock:
            rows = self.db.execute(
                "SELECT a.skill_id, a.version, d.definition, d.enabled FROM skill_active_v2 a "
                "JOIN skill_definitions d ON d.skill_id=a.skill_id AND d.version=a.version"
            ).fetchall()
        out: list[SkillDefinition] = []
        for _sid, _ver, blob, enabled in rows:
            if enabled_only and not enabled:
                continue
            d = SkillDefinition.from_dict(json.loads(blob))
            if category and d.category != category:
                continue
            out.append(d)
        return out

    def list_versions(self, skill_id: str) -> list[SkillDefinition]:
        with self._lock:
            rows = self.db.execute(
                "SELECT definition FROM skill_definitions WHERE skill_id=? ORDER BY created_at",
                (skill_id,),
            ).fetchall()
        return [SkillDefinition.from_dict(json.loads(r[0])) for r in rows]

    def active_pointer(self, skill_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.db.execute(
                "SELECT version, previous_version, lkg_version, updated_at FROM skill_active_v2 WHERE skill_id=?",
                (skill_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "skill_id": skill_id,
            "ACTIVE_SKILL_VERSION": row[0],
            "PREVIOUS_SKILL_VERSION": row[1],
            "LKG_SKILL_VERSION": row[2] or row[0],
            "updated_at": row[3],
        }

    def activate(
        self,
        skill_id: str,
        version: str,
        *,
        approved: bool = False,
        actor: str = "",
        mark_lkg: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required"}
        if not self.get(skill_id, version):
            return {"ok": False, "error": "skill_version_not_found"}
        with self._lock:
            self._activate_unlocked(skill_id, version, reason=f"activate:{actor or 'owner'}")
            if mark_lkg:
                self.db.execute(
                    "UPDATE skill_active_v2 SET lkg_version=?, updated_at=? WHERE skill_id=?",
                    (version, now_ts(), skill_id),
                )
                self.history.record(
                    "LKG_MARK",
                    skill_id=skill_id,
                    version=version,
                    actor=actor,
                )
            self.legacy.activate(skill_id, version, approved=True, actor=actor)
            self._audit("activate", skill_id, version, {"actor": actor, "mark_lkg": mark_lkg})
            self.db.commit()
        return {"ok": True, "skill_id": skill_id, "version": version, "pointer": self.active_pointer(skill_id)}

    def deactivate(self, skill_id: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required"}
        with self._lock:
            ptr = self.active_pointer(skill_id)
            if not ptr:
                return {"ok": False, "error": "not_active"}
            ver = ptr["ACTIVE_SKILL_VERSION"]
            self.db.execute(
                "UPDATE skill_definitions SET enabled=0, status=?, updated_at=? WHERE skill_id=? AND version=?",
                (SkillStatus.DISABLED.value, now_ts(), skill_id, ver),
            )
            self._audit("deactivate", skill_id, ver, {"actor": actor})
            self.db.commit()
        return {"ok": True, "skill_id": skill_id, "version": ver, "enabled": False}

    def rollback(self, skill_id: str, *, approved: bool = False, actor: str = "", to_version: str | None = None) -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required"}
        ptr = self.active_pointer(skill_id)
        if not ptr:
            return {"ok": False, "error": "no_active_skill"}
        current = ptr["ACTIVE_SKILL_VERSION"]
        target = to_version or ptr.get("PREVIOUS_SKILL_VERSION") or ptr.get("LKG_SKILL_VERSION")
        if not target or target == current:
            # history fallback
            target = self.history.previous_version(skill_id, current) or target
        if not target or target == current:
            return {"ok": False, "error": "no_previous_skill_version", "active": current}
        if not self.get(skill_id, target):
            return {"ok": False, "error": "rollback_target_missing", "target": target}
        # Verify current artifact still present (definition row)
        if not self.get(skill_id, current):
            return {"ok": False, "error": "active_definition_missing"}
        result = self.activate(skill_id, target, approved=True, actor=actor, mark_lkg=False)
        if result.get("ok"):
            self.history.record(
                "ROLLBACK",
                skill_id=skill_id,
                from_version=current,
                to_version=target,
                actor=actor,
            )
            with self._lock:
                self.db.execute(
                    "UPDATE skill_definitions SET status=?, updated_at=? WHERE skill_id=? AND version=?",
                    (SkillStatus.ROLLED_BACK.value, now_ts(), skill_id, current),
                )
                self.db.commit()
        return {**result, "rolled_back_from": current, "restored_version": target}

    def mark_lkg(self, skill_id: str, version: str | None = None, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        if not approved:
            return {"ok": False, "needs_approval": True, "error": "owner approval required"}
        ptr = self.active_pointer(skill_id)
        ver = version or (ptr or {}).get("ACTIVE_SKILL_VERSION")
        if not ver or not self.get(skill_id, ver):
            return {"ok": False, "error": "version_not_found"}
        with self._lock:
            self.db.execute(
                """INSERT INTO skill_active_v2(skill_id, version, previous_version, lkg_version, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(skill_id) DO UPDATE SET lkg_version=excluded.lkg_version, updated_at=excluded.updated_at
                """,
                (skill_id, ver, (ptr or {}).get("PREVIOUS_SKILL_VERSION"), ver, now_ts()),
            )
            self.history.record("LKG_MARK", skill_id=skill_id, version=ver, actor=actor)
            self.db.commit()
        return {"ok": True, "skill_id": skill_id, "LKG_SKILL_VERSION": ver}

    def validate_dependencies(self, skill_id: str, version: str | None = None) -> dict[str, Any]:
        d = self.get(skill_id, version)
        if not d:
            return {"ok": False, "error": "not_found"}
        missing = []
        for dep in d.dependencies:
            if not self.get(dep):
                missing.append(dep)
        return {"ok": not missing, "missing": missing, "dependencies": list(d.dependencies)}

    def health(self, skill_id: str | None = None) -> dict[str, Any]:
        skills = [self.get(skill_id)] if skill_id else self.list_skills(enabled_only=False)
        skills = [s for s in skills if s]
        return {
            "ok": True,
            "count": len(skills),
            "skills": [
                {
                    "skill_id": s.skill_id,
                    "version": s.version,
                    "enabled": s.enabled,
                    "status": s.status,
                    "health": s.health,
                    "evaluation_state": s.evaluation_state,
                    "pointer": self.active_pointer(s.skill_id),
                }
                for s in skills
            ],
        }

    def invoke(
        self,
        skill_id: str,
        args: dict[str, Any] | None = None,
        *,
        version: str | None = None,
        approved: bool = False,
        actor: str = "",
        ctx: SkillContext | None = None,
    ) -> SkillResult:
        d = self.get(skill_id, version)
        if not d:
            return SkillResult(ok=False, error=f"unknown skill: {skill_id}")
        if not d.enabled:
            return SkillResult(ok=False, error="skill_disabled", meta={"skill_id": skill_id})
        # Skills cannot grant themselves privileges — invoke through legacy AuthorizedExecutor path
        return self.legacy.invoke_version(
            skill_id,
            d.version,
            args,
            ctx=ctx,
            approved=approved,
            actor=actor,
        )

    def audit_history(self, skill_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if skill_id:
                rows = self.db.execute(
                    "SELECT ts, event, skill_id, version, detail FROM skill_audit WHERE skill_id=? ORDER BY id DESC LIMIT ?",
                    (skill_id, int(limit)),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT ts, event, skill_id, version, detail FROM skill_audit ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [
            {
                "ts": r[0],
                "event": r[1],
                "skill_id": r[2],
                "version": r[3],
                "detail": json.loads(r[4] or "{}"),
            }
            for r in rows
        ]
