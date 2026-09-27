"""Portable export/import — pfai-export-v1 (PHASE 3 populates from live stores)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.migration import PFAI_SCHEMA_VERSION


class ExportBundleScaffold:
    """Writes/reads a JSON bundle. PHASE 3 fills sections from injectable exporters."""

    MANIFEST = "pfai_export_manifest.json"

    def __init__(
        self,
        *,
        memory_export: Callable[[], list[dict[str, Any]]] | None = None,
        knowledge_export: Callable[[], list[dict[str, Any]]] | None = None,
        config_export: Callable[[], dict[str, Any]] | None = None,
        skills_export: Callable[[], list[dict[str, Any]]] | None = None,
        memory_import: Callable[[list[dict[str, Any]]], int] | None = None,
        knowledge_import: Callable[[list[dict[str, Any]]], int] | None = None,
    ) -> None:
        self._memory_export = memory_export
        self._knowledge_export = knowledge_export
        self._config_export = config_export
        self._skills_export = skills_export
        self._memory_import = memory_import
        self._knowledge_import = knowledge_import

    def export_bundle(self, target_dir: str, *, include: list[str] | None = None) -> dict[str, Any]:
        root = Path(target_dir)
        root.mkdir(parents=True, exist_ok=True)
        sections = include or ["memory", "knowledge", "config", "skills", "schema"]
        counts: dict[str, int] = {}

        for section in sections:
            if section == "memory":
                data = list(self._memory_export() if self._memory_export else [])
            elif section == "knowledge":
                data = list(self._knowledge_export() if self._knowledge_export else [])
            elif section == "config":
                # Never include secrets / API keys / hashes.
                raw = dict(self._config_export() if self._config_export else {})
                data = {k: v for k, v in raw.items() if "secret" not in k.lower() and "key" not in k.lower() and "hash" not in k.lower()}
            elif section == "skills":
                data = list(self._skills_export() if self._skills_export else [])
            elif section == "schema":
                data = {"schema_version": PFAI_SCHEMA_VERSION, "format": "pfai-export-v1"}
            else:
                data = []
            (root / f"{section}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            counts[section] = len(data) if isinstance(data, list) else 1

        manifest = {
            "format": "pfai-export-v1",
            "schema_version": PFAI_SCHEMA_VERSION,
            "sections": sections,
            "counts": counts,
            "note": "Portable memory/knowledge/config — no secrets, no model weights",
        }
        (root / self.MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def import_bundle(self, source_dir: str, *, dry_run: bool = True) -> dict[str, Any]:
        root = Path(source_dir)
        manifest_path = root / self.MANIFEST
        if not manifest_path.exists():
            return {"ok": False, "error": "missing manifest"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "pfai-export-v1":
            return {"ok": False, "error": "unsupported export format"}
        applied: dict[str, int] = {}
        if not dry_run:
            mem_path = root / "memory.json"
            if mem_path.exists() and self._memory_import:
                rows = json.loads(mem_path.read_text(encoding="utf-8") or "[]")
                applied["memory"] = int(self._memory_import(rows) or 0)
            kn_path = root / "knowledge.json"
            if kn_path.exists() and self._knowledge_import:
                rows = json.loads(kn_path.read_text(encoding="utf-8") or "[]")
                applied["knowledge"] = int(self._knowledge_import(rows) or 0)
        return {
            "ok": True,
            "dry_run": dry_run,
            "manifest": manifest,
            "applied": False if dry_run else True,
            "counts": applied,
        }
