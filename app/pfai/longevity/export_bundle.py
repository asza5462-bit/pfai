"""Portable export/import scaffold — prevents vendor lock-in of memory/knowledge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExportBundleScaffold:
    """Writes/reads a JSON bundle. Full adapters land in later phases."""

    MANIFEST = "pfai_export_manifest.json"

    def export_bundle(self, target_dir: str, *, include: list[str] | None = None) -> dict[str, Any]:
        root = Path(target_dir)
        root.mkdir(parents=True, exist_ok=True)
        sections = include or ["memory", "knowledge", "config", "skills", "schema"]
        manifest = {
            "format": "pfai-export-v1",
            "schema_version": 1,
            "sections": sections,
            "note": "Scaffold only — populate from stores in later phases",
        }
        for section in sections:
            (root / f"{section}.json").write_text("[]\n", encoding="utf-8")
        (root / self.MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def import_bundle(self, source_dir: str, *, dry_run: bool = True) -> dict[str, Any]:
        root = Path(source_dir)
        manifest_path = root / self.MANIFEST
        if not manifest_path.exists():
            return {"ok": False, "error": "missing manifest"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "dry_run": dry_run,
            "manifest": manifest,
            "applied": False if dry_run else True,
        }
