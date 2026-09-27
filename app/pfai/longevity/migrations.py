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
    # Ensure LTM versions schema exists even before LongTermMemory is constructed.
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
    _ = conn  # reserved for future RelationalStorePort


PLATFORM_MIGRATIONS: list[Migration] = [
    Migration(
        version=2,
        name="longevity_ltm_foundation",
        upgrade=_upgrade_v2_longevity_foundation,
        description="PHASE 3: durable LTM versions table + longevity data root",
    ),
]


def register_platform_migrations(runner) -> None:
    for mig in PLATFORM_MIGRATIONS:
        runner.register(mig)
