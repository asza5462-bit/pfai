"""Compatibility layer scaffold — inventory of swappable kinds."""
from __future__ import annotations

import sys

from pfai.interfaces.compat import CompatibilityReport
from pfai.interfaces.migration import PFAI_SCHEMA_VERSION


class CompatibilityLayer:
    def check(self) -> CompatibilityReport:
        issues: list[str] = []
        if sys.version_info < (3, 10):
            issues.append("python<3.10 unsupported by current codebase")
        return CompatibilityReport(
            python_ok=sys.version_info >= (3, 10),
            dependencies_ok=True,
            schema_ok=True,
            providers_ok=True,
            storage_ok=True,
            issues=issues,
            recommendations=[
                "Keep Core behind ports; never bake a vendor into product logic",
                "Prefer offline-capable providers for continuity",
                "Bump PFAI_SCHEMA_VERSION only with a registered migration",
            ],
            meta={"python": sys.version.split()[0], "schema_version": PFAI_SCHEMA_VERSION},
        )

    def schema_version(self) -> int:
        return PFAI_SCHEMA_VERSION

    def supported_provider_kinds(self) -> list[str]:
        return ["echo", "mock", "openai_compatible", "anthropic", "local", "custom"]

    def supported_storage_kinds(self) -> list[str]:
        return ["sqlite", "json_files", "filesystem_blobs"]  # future: postgres, s3-compatible, etc.
