"""Schema migration runner — dry-run by default; apply with backup (PHASE 3)."""
from __future__ import annotations

import json
import threading
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
    ) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrations: dict[int, Migration] = {}
        self._backup_fn = backup_fn
        self._connection = connection
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
        }

    def run(self, target: int | None = None, *, dry_run: bool = True) -> MigrationReport:
        planned = self.plan(target)
        report = MigrationReport(
            from_version=self._current,
            to_version=PFAI_SCHEMA_VERSION if target is None else int(target),
            dry_run=dry_run,
        )
        backup_info: dict[str, Any] | None = None
        if not dry_run and planned:
            if self._backup_fn is None:
                report.ok = False
                report.error = "backup required before applying migrations"
                return report
            try:
                backup_info = self._backup_fn() or {}
            except Exception as exc:
                report.ok = False
                report.error = f"backup failed: {type(exc).__name__}"
                return report

        for mig in planned:
            report.applied.append(f"v{mig.version}:{mig.name}")
            if dry_run:
                continue
            if mig.upgrade is None:
                report.ok = False
                report.error = f"missing upgrade for {mig.name}"
                return report
            try:
                with self._lock:
                    mig.upgrade(self._connection)
                    self._current = mig.version
                    self._persist()
            except Exception as exc:
                report.ok = False
                report.error = f"upgrade {mig.name} failed: {type(exc).__name__}"
                return report
        if not dry_run and planned:
            report.to_version = self._current
        if backup_info is not None:
            # Record backup basename only — never absolute paths or digests that could leak secrets.
            report.applied.append(f"backup:{backup_info.get('path') or backup_info.get('label') or 'ok'}")
        return report
