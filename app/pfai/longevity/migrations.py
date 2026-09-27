"""Registered platform migrations (PHASE 3+)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pfai.interfaces.migration import Migration


def _upgrade_v2_longevity_foundation(conn: Any) -> None:
    """Ensure longevity data directories and LTM versions table exist.

    Idempotent. ``conn`` may be None (filesystem-only) or a sqlite3 connection
    used only as a marker that apply mode is active.
    """
    root = Path("data/longevity")
    root.mkdir(parents=True, exist_ok=True)
    (root / ".phase3").write_text("ltm+knowledge+migration\n", encoding="utf-8")
    import sqlite3

    db_path = root / "ltm_versions.sqlite3"
    db = sqlite3.connect(db_path)
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS ltm_versions (
                record_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                confidence REAL,
                status TEXT,
                scope TEXT,
                store_id INTEGER,
                created_at TEXT,
                updated_at TEXT,
                provenance TEXT,
                meta TEXT,
                PRIMARY KEY (record_id, version)
            )"""
        )
        db.commit()
    finally:
        db.close()
    _ = conn


def _upgrade_v3_skill_tool_versions(conn: Any) -> None:
    """PHASE 4: durable skill version metadata + authz/heal audit dirs."""
    root = Path("data/longevity")
    root.mkdir(parents=True, exist_ok=True)
    (root / ".phase4").write_text("planner+skills+heal+authz\n", encoding="utf-8")
    import sqlite3

    db_path = root / "skill_versions.sqlite3"
    db = sqlite3.connect(db_path)
    try:
        db.executescript(
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
        db.commit()
    finally:
        db.close()
    _ = conn


PLATFORM_MIGRATIONS: list[Migration] = [
    Migration(
        version=2,
        name="longevity_ltm_foundation",
        upgrade=_upgrade_v2_longevity_foundation,
        description="PHASE 3: durable LTM versions table + longevity data root",
    ),
    Migration(
        version=3,
        name="skill_tool_versioning",
        upgrade=_upgrade_v3_skill_tool_versions,
        description="PHASE 4: skill version tables + planner/heal durability markers",
    ),
]


def register_platform_migrations(runner) -> None:
    for mig in PLATFORM_MIGRATIONS:
        runner.register(mig)
