"""Schema migration runner scaffold — dry-run by default."""
from __future__ import annotations

from pfai.interfaces.migration import (
    PFAI_SCHEMA_VERSION,
    Migration,
    MigrationReport,
)


class MigrationRunner:
    def __init__(self, current: int = 1) -> None:
        self._current = int(current)
        self._migrations: dict[int, Migration] = {}

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

    def run(self, target: int | None = None, *, dry_run: bool = True) -> MigrationReport:
        planned = self.plan(target)
        report = MigrationReport(
            from_version=self._current,
            to_version=PFAI_SCHEMA_VERSION if target is None else int(target),
            dry_run=dry_run,
        )
        for mig in planned:
            report.applied.append(f"v{mig.version}:{mig.name}")
            if dry_run:
                continue
            if mig.upgrade is None:
                report.ok = False
                report.error = f"missing upgrade for {mig.name}"
                return report
            mig.upgrade(None)
            self._current = mig.version
        if not dry_run and planned:
            report.to_version = self._current
        return report
