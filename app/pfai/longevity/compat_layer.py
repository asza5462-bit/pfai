"""Compatibility layer — inventory of swappable kinds + schema pending (PHASE 3)."""
from __future__ import annotations

import sys
from typing import Any

from pfai.interfaces.compat import CompatibilityReport
from pfai.interfaces.migration import PFAI_SCHEMA_VERSION


class CompatibilityLayer:
    def __init__(self, *, current_schema: int | None = None, migration_status: dict[str, Any] | None = None) -> None:
        self._current_schema = current_schema
        self._migration_status = migration_status

    def check(self) -> CompatibilityReport:
        issues: list[str] = []
        if sys.version_info < (3, 10):
            issues.append("python<3.10 unsupported by current codebase")
        schema_ok = True
        if self._migration_status is not None:
            pending = int(self._migration_status.get("pending_count") or 0)
            if pending > 0:
                schema_ok = False
                issues.append(f"schema pending migrations: {pending}")
        elif self._current_schema is not None and int(self._current_schema) < PFAI_SCHEMA_VERSION:
            schema_ok = False
            issues.append(
                f"schema behind target: current={self._current_schema} target={PFAI_SCHEMA_VERSION}"
            )
        return CompatibilityReport(
            python_ok=sys.version_info >= (3, 10),
            dependencies_ok=True,
            schema_ok=schema_ok,
            providers_ok=True,
            storage_ok=True,
            issues=issues,
            recommendations=[
                "Keep Core behind ports; never bake a vendor into product logic",
                "Prefer offline-capable providers for continuity",
                "Bump PFAI_SCHEMA_VERSION only with a registered migration",
                "Apply pending migrations with backup via /platform/migrations/run",
            ],
            meta={
                "python": sys.version.split()[0],
                "schema_version": PFAI_SCHEMA_VERSION,
                "current_schema": self._current_schema,
                "migration": self._migration_status,
            },
        )

    def schema_version(self) -> int:
        return PFAI_SCHEMA_VERSION

    def supported_provider_kinds(self) -> list[str]:
        return ["echo", "mock", "openai_compatible", "anthropic", "local", "custom"]

    def supported_storage_kinds(self) -> list[str]:
        return ["sqlite", "json_files", "filesystem_blobs"]  # future: postgres, s3-compatible, etc.
