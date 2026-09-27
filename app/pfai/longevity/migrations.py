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


def _downgrade_v2_longevity_foundation(conn: Any) -> None:
    """Best-effort reverse: remove phase marker only (keep data tables for safety)."""
    marker = Path("data/longevity/.phase3")
    if marker.exists():
        marker.unlink()
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


def _downgrade_v3_skill_tool_versions(conn: Any) -> None:
    """Best-effort reverse: remove phase marker only (tables retained)."""
    marker = Path("data/longevity/.phase4")
    if marker.exists():
        marker.unlink()
    _ = conn


def _upgrade_v4_autonomous_training(conn: Any) -> None:
    """PHASE 6: autonomous training directories + registry placeholders (idempotent)."""
    root = Path("data/longevity")
    root.mkdir(parents=True, exist_ok=True)
    train_root = root / "training"
    for sub in ("datasets", "models", "checkpoints", "artifacts", "jobs"):
        (train_root / sub).mkdir(parents=True, exist_ok=True)
    (root / ".phase6").write_text("autonomous-training+model-registry\n", encoding="utf-8")
    import sqlite3

    # Ensure registry DBs exist even before first orchestrator init.
    ds = sqlite3.connect(train_root / "datasets" / "dataset_registry.sqlite3")
    try:
        ds.execute(
            """CREATE TABLE IF NOT EXISTS dataset_versions (
                dataset_id TEXT PRIMARY KEY,
                parent_dataset TEXT,
                status TEXT,
                checksum TEXT,
                train_count INTEGER,
                validation_count INTEGER,
                test_count INTEGER,
                sanitizer_version TEXT,
                filtering_rules TEXT,
                validation_results TEXT,
                source_records TEXT,
                created_at REAL,
                meta TEXT
            )"""
        )
        ds.commit()
    finally:
        ds.close()
    ms = sqlite3.connect(train_root / "models" / "model_registry.sqlite3")
    try:
        ms.executescript(
            """
            CREATE TABLE IF NOT EXISTS model_versions (
                model_id TEXT PRIMARY KEY,
                base_model TEXT,
                base_model_hash TEXT,
                dataset_version TEXT,
                training_config TEXT,
                training_code_version TEXT,
                checkpoint_ref TEXT,
                tokenizer_version TEXT,
                evaluation TEXT,
                status TEXT,
                created_at REAL,
                meta TEXT
            );
            CREATE TABLE IF NOT EXISTS model_active (
                slot TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                activated_at REAL,
                previous_model_id TEXT
            );
            """
        )
        ms.commit()
    finally:
        ms.close()
    _ = conn


def _downgrade_v4_autonomous_training(conn: Any) -> None:
    marker = Path("data/longevity/.phase6")
    if marker.exists():
        marker.unlink()
    _ = conn


def _upgrade_v5_skill_packs_control_center(conn: Any) -> None:
    """PHASE 7: skill pack registry + active runtime pointer dirs."""
    root = Path("data/longevity")
    root.mkdir(parents=True, exist_ok=True)
    (root / "training").mkdir(parents=True, exist_ok=True)
    (root / ".phase7").write_text("skill-packs+runtime-detector+control-center\n", encoding="utf-8")
    import sqlite3

    db = sqlite3.connect(root / "skill_packs.sqlite3")
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_packs (
                pack_id TEXT NOT NULL,
                version TEXT NOT NULL,
                description TEXT,
                skills TEXT,
                permission TEXT,
                status TEXT,
                changelog TEXT,
                meta TEXT,
                created_at REAL,
                PRIMARY KEY (pack_id, version)
            );
            CREATE TABLE IF NOT EXISTS skill_pack_active (
                pack_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL,
                previous_version TEXT
            );
            """
        )
        db.commit()
    finally:
        db.close()
    _ = conn


def _downgrade_v5_skill_packs_control_center(conn: Any) -> None:
    marker = Path("data/longevity/.phase7")
    if marker.exists():
        marker.unlink()
    _ = conn


def verify_platform_schema(current: int) -> dict[str, Any]:
    """Integrity checks used by MigrationRunner after apply."""
    root = Path("data/longevity")
    checks: dict[str, Any] = {"ok": True, "current": current}
    if current >= 2:
        db = root / "ltm_versions.sqlite3"
        checks["ltm_versions_db"] = db.exists()
        if not db.exists():
            checks["ok"] = False
            checks["error"] = "ltm_versions.sqlite3 missing"
    if current >= 3:
        db = root / "skill_versions.sqlite3"
        checks["skill_versions_db"] = db.exists()
        if not db.exists():
            checks["ok"] = False
            checks["error"] = "skill_versions.sqlite3 missing"
    if current >= 4:
        train = root / "training"
        checks["training_root"] = train.exists()
        checks["dataset_registry"] = (train / "datasets" / "dataset_registry.sqlite3").exists()
        checks["model_registry"] = (train / "models" / "model_registry.sqlite3").exists()
        if not checks["training_root"] or not checks["dataset_registry"] or not checks["model_registry"]:
            checks["ok"] = False
            checks["error"] = "autonomous training registries missing"
    if current >= 5:
        checks["skill_packs_db"] = (root / "skill_packs.sqlite3").exists()
        if not checks["skill_packs_db"]:
            checks["ok"] = False
            checks["error"] = "skill_packs.sqlite3 missing"
    return checks


PLATFORM_MIGRATIONS: list[Migration] = [
    Migration(
        version=2,
        name="longevity_ltm_foundation",
        upgrade=_upgrade_v2_longevity_foundation,
        downgrade=_downgrade_v2_longevity_foundation,
        description="PHASE 3: durable LTM versions table + longevity data root",
    ),
    Migration(
        version=3,
        name="skill_tool_versioning",
        upgrade=_upgrade_v3_skill_tool_versions,
        downgrade=_downgrade_v3_skill_tool_versions,
        description="PHASE 4: skill version tables + planner/heal durability markers",
    ),
    Migration(
        version=4,
        name="autonomous_training_foundation",
        upgrade=_upgrade_v4_autonomous_training,
        downgrade=_downgrade_v4_autonomous_training,
        description="PHASE 6: autonomous training dirs + dataset/model registries",
    ),
    Migration(
        version=5,
        name="skill_packs_control_center",
        upgrade=_upgrade_v5_skill_packs_control_center,
        downgrade=_downgrade_v5_skill_packs_control_center,
        description="PHASE 7: skill packs + control-center durability markers",
    ),
]


def register_platform_migrations(runner) -> None:
    for mig in PLATFORM_MIGRATIONS:
        runner.register(mig)
