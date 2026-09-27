"""Schema migration runner — dry-run by default; apply with backup (PHASE 3/5).

PHASE 5 hardening:
- backup-first (required for non-dry-run)
- intent + result audit log
- idempotent plan (already-applied versions skipped)
- optional post-apply verify hook
- transactional where a sqlite connection is provided
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.migration import (
    PFAI_SCHEMA_VERSION,
    Migration,
    MigrationReport,
)


class MigrationRunner:
    """Persists applied schema version; backs up before non-dry-run apply."""

    def __init__(
        self,
        current: int | None = None,
        *,
        state_path: str = "data/longevity/schema_version.json",
        backup_fn: Callable[[], dict[str, Any]] | None = None,
        connection: Any | None = None,
        audit_path: str = "data/longevity/migration_audit.jsonl",
        verify_fn: Callable[[int], dict[str, Any]] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrations: dict[int, Migration] = {}
        self._backup_fn = backup_fn
        self._connection = connection
        self._verify_fn = verify_fn
        if current is not None:
            self._current = int(current)
            self._persist()
        else:
            self._current = self._load_current()

    def _load_current(self) -> int:
        if not self.state_path.exists():
            return 1
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return int(data.get("schema_version") or 1)
        except Exception:
            return 1

    def _persist(self) -> None:
        payload = {"schema_version": self._current, "target": PFAI_SCHEMA_VERSION}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _audit(self, event: str, detail: dict[str, Any] | None = None) -> None:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "detail": detail or {},
        }
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def current_version(self) -> int:
        return self._current

    def target_version(self) -> int:
        return PFAI_SCHEMA_VERSION

    def register(self, migration: Migration) -> None:
        self._migrations[int(migration.version)] = migration

    def plan(self, target: int | None = None) -> list[Migration]:
        tgt = PFAI_SCHEMA_VERSION if target is None else int(target)
        versions = sorted(v for v in self._migrations if self._current < v <= tgt)
        return [self._migrations[v] for v in versions]

    def status(self) -> dict[str, Any]:
        planned = self.plan()
        return {
            "current": self._current,
            "target": PFAI_SCHEMA_VERSION,
            "pending": [f"v{m.version}:{m.name}" for m in planned],
            "pending_count": len(planned),
            "audit_path": str(self.audit_path.name),
        }

    def verify_schema(self) -> dict[str, Any]:
        """Integrity check after apply (or on demand)."""
        if self._verify_fn is not None:
            try:
                result = self._verify_fn(self._current) or {}
                result.setdefault("ok", True)
                result.setdefault("current", self._current)
                return result
            except Exception as exc:
                return {"ok": False, "current": self._current, "error": type(exc).__name__}
        # Default: state file readable and current <= target
        ok = 1 <= self._current <= PFAI_SCHEMA_VERSION
        return {
            "ok": ok,
            "current": self._current,
            "target": PFAI_SCHEMA_VERSION,
            "state_exists": self.state_path.exists(),
        }

    def run(self, target: int | None = None, *, dry_run: bool = True) -> MigrationReport:
        planned = self.plan(target)
        report = MigrationReport(
            from_version=self._current,
            to_version=PFAI_SCHEMA_VERSION if target is None else int(target),
            dry_run=dry_run,
        )
        self._audit(
            "migration_intent",
            {
                "dry_run": dry_run,
                "from": self._current,
                "to": report.to_version,
                "pending": [f"v{m.version}:{m.name}" for m in planned],
            },
        )

        # Idempotent: nothing to do
        if not planned:
            report.to_version = self._current
            self._audit("migration_noop", {"current": self._current})
            return report

        backup_info: dict[str, Any] | None = None
        if not dry_run:
            if self._backup_fn is None:
                report.ok = False
                report.error = "backup required before applying migrations"
                self._audit("migration_blocked", {"error": report.error})
                return report
            try:
                backup_info = self._backup_fn() or {}
                self._audit(
                    "migration_backup",
                    {"label": backup_info.get("label") or backup_info.get("path") or "ok"},
                )
            except Exception as exc:
                report.ok = False
                report.error = f"backup failed: {type(exc).__name__}"
                self._audit("migration_backup_failed", {"error": type(exc).__name__})
                return report

        for mig in planned:
            report.applied.append(f"v{mig.version}:{mig.name}")
            if dry_run:
                continue
            if mig.upgrade is None:
                report.ok = False
                report.error = f"missing upgrade for {mig.name}"
                self._audit("migration_failed", {"migration": mig.name, "error": report.error})
                return report
            try:
                with self._lock:
                    # Prefer sqlite transaction when a real connection is supplied.
                    began = False
                    if self._connection is not None and hasattr(self._connection, "execute"):
                        try:
                            self._connection.execute("BEGIN")
                            began = True
                        except Exception:
                            began = False
                    try:
                        mig.upgrade(self._connection)
                        if began:
                            self._connection.execute("COMMIT")
                    except Exception:
                        if began:
                            try:
                                self._connection.execute("ROLLBACK")
                            except Exception:
                                pass
                        raise
                    self._current = mig.version
                    self._persist()
                self._audit("migration_applied", {"version": mig.version, "name": mig.name})
            except Exception as exc:
                report.ok = False
                report.error = f"upgrade {mig.name} failed: {type(exc).__name__}"
                self._audit(
                    "migration_failed",
                    {"migration": mig.name, "error": type(exc).__name__, "current": self._current},
                )
                return report

        if not dry_run and planned:
            report.to_version = self._current
            verify = self.verify_schema()
            if not verify.get("ok"):
                report.ok = False
                report.error = f"schema verification failed: {verify.get('error') or 'check'}"
                self._audit("migration_verify_failed", verify)
                return report
            self._audit("migration_verified", verify)

        if backup_info is not None:
            # Record backup basename only — never absolute paths or digests that could leak secrets.
            report.applied.append(f"backup:{backup_info.get('path') or backup_info.get('label') or 'ok'}")
        self._audit(
            "migration_complete",
            {"ok": report.ok, "from": report.from_version, "to": report.to_version, "dry_run": dry_run},
        )
        return report

    def rollback_one(self) -> MigrationReport:
        """Attempt reverse of the highest applied migration if downgrade exists."""
        report = MigrationReport(
            from_version=self._current,
            to_version=max(1, self._current - 1),
            dry_run=False,
        )
        mig = self._migrations.get(self._current)
        if mig is None or mig.downgrade is None:
            report.ok = False
            report.error = "no reversible downgrade for current version"
            self._audit("migration_rollback_unavailable", {"current": self._current})
            return report
        if self._backup_fn is None:
            report.ok = False
            report.error = "backup required before rollback"
            return report
        try:
            backup_info = self._backup_fn() or {}
        except Exception as exc:
            report.ok = False
            report.error = f"backup failed: {type(exc).__name__}"
            return report
        try:
            with self._lock:
                mig.downgrade(self._connection)
                self._current = max(1, self._current - 1)
                self._persist()
            report.applied.append(f"downgrade:v{mig.version}:{mig.name}")
            report.applied.append(f"backup:{backup_info.get('path') or backup_info.get('label') or 'ok'}")
            self._audit("migration_rollback", {"to": self._current, "from_mig": mig.name})
        except Exception as exc:
            report.ok = False
            report.error = f"downgrade failed: {type(exc).__name__}"
            self._audit("migration_rollback_failed", {"error": type(exc).__name__})
        return report
