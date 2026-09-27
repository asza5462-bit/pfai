"""Immutable model registry for candidate/active/LKG/rollback lifecycle."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .types import ModelStatus


class ModelRegistry:
    def __init__(self, root: str = "data/longevity/training/models") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "model_registry.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._lock:
            db = self._conn()
            try:
                db.executescript(
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
                    CREATE TABLE IF NOT EXISTS model_lkg (
                        slot TEXT PRIMARY KEY,
                        model_id TEXT NOT NULL,
                        marked_at REAL,
                        reason TEXT
                    );
                    """
                )
                # Soft-migrate older DBs: ignore if columns already exist via separate ALTER attempts.
                for col, typ in (
                    ("metrics", "TEXT"),
                    ("training_backend", "TEXT"),
                    ("parent_model_id", "TEXT"),
                    ("base_model_revision", "TEXT"),
                ):
                    try:
                        db.execute(f"ALTER TABLE model_versions ADD COLUMN {col} {typ}")
                    except sqlite3.OperationalError:
                        pass
                db.commit()
            finally:
                db.close()

    def _next_id(self) -> str:
        with self._lock:
            db = self._conn()
            try:
                n = int(db.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]) + 1
            finally:
                db.close()
        return f"model-v{n:04d}"

    def register(
        self,
        *,
        base_model: str,
        dataset_version: str,
        training_config: dict[str, Any],
        checkpoint_ref: str,
        status: ModelStatus | str = ModelStatus.CANDIDATE,
        evaluation: dict[str, Any] | None = None,
        base_model_hash: str = "",
        base_model_revision: str = "",
        training_code_version: str = "phase8-v1",
        training_backend: str = "",
        tokenizer_version: str = "",
        metrics: dict[str, Any] | None = None,
        parent_model_id: str | None = None,
        meta: dict[str, Any] | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        mid = model_id or self._next_id()
        created = time.time()
        status_s = status.value if isinstance(status, ModelStatus) else str(status)
        active = self.active()
        if parent_model_id is None and active:
            parent_model_id = active.get("model_id")
        rec = {
            "model_id": mid,
            "base_model": base_model,
            "base_model_hash": base_model_hash,
            "base_model_revision": base_model_revision,
            "dataset_version": dataset_version,
            "training_config": training_config,
            "training_code_version": training_code_version,
            "training_backend": training_backend,
            "checkpoint_ref": checkpoint_ref,
            "tokenizer_version": tokenizer_version,
            "evaluation": evaluation or {},
            "metrics": metrics or {},
            "parent_model_id": parent_model_id,
            "status": status_s,
            "created_at": created,
            "meta": meta or {},
        }
        model_dir = self.root / mid
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "manifest.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        with self._lock:
            db = self._conn()
            try:
                existing = db.execute(
                    "SELECT model_id FROM model_versions WHERE model_id=?", (mid,)
                ).fetchone()
                if existing:
                    raise RuntimeError(f"immutable model version exists: {mid}")
                db.execute(
                    """INSERT INTO model_versions (
                        model_id, base_model, base_model_hash, dataset_version,
                        training_config, training_code_version, checkpoint_ref,
                        tokenizer_version, evaluation, status, created_at, meta,
                        metrics, training_backend, parent_model_id, base_model_revision
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mid,
                        base_model,
                        base_model_hash,
                        dataset_version,
                        json.dumps(training_config),
                        training_code_version,
                        checkpoint_ref,
                        tokenizer_version,
                        json.dumps(evaluation or {}),
                        status_s,
                        created,
                        json.dumps(meta or {}),
                        json.dumps(metrics or {}),
                        training_backend,
                        parent_model_id,
                        base_model_revision,
                    ),
                )
                db.commit()
            finally:
                db.close()
        return rec

    def update_status(self, model_id: str, status: ModelStatus | str, *, evaluation: dict[str, Any] | None = None) -> None:
        status_s = status.value if isinstance(status, ModelStatus) else str(status)
        with self._lock:
            db = self._conn()
            try:
                if evaluation is not None:
                    db.execute(
                        "UPDATE model_versions SET status=?, evaluation=? WHERE model_id=?",
                        (status_s, json.dumps(evaluation), model_id),
                    )
                else:
                    db.execute(
                        "UPDATE model_versions SET status=? WHERE model_id=?",
                        (status_s, model_id),
                    )
                db.commit()
            finally:
                db.close()
        path = self.root / model_id / "manifest.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["status"] = status_s
            if evaluation is not None:
                data["evaluation"] = evaluation
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, model_id: str) -> dict[str, Any] | None:
        path = self.root / model_id / "manifest.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def list_models(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            db = self._conn()
            try:
                rows = db.execute(
                    "SELECT model_id, base_model, dataset_version, status, checkpoint_ref, created_at "
                    "FROM model_versions ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "model_id": r[0],
                "base_model": r[1],
                "dataset_version": r[2],
                "status": r[3],
                "checkpoint_ref": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def active(self, slot: str = "default") -> dict[str, Any] | None:
        with self._lock:
            db = self._conn()
            try:
                row = db.execute(
                    "SELECT model_id, activated_at, previous_model_id FROM model_active WHERE slot=?",
                    (slot,),
                ).fetchone()
            finally:
                db.close()
        if not row:
            return None
        model = self.get(row[0]) or {"model_id": row[0]}
        return {
            **model,
            "activated_at": row[1],
            "previous_model_id": row[2],
            "slot": slot,
        }

    def mark_lkg(self, model_id: str, *, slot: str = "default", reason: str = "successful_activation") -> dict[str, Any]:
        """Mark immutable LKG pointer. Never deletes prior checkpoints."""
        model = self.get(model_id)
        if not model:
            return {"ok": False, "error": "model_not_found"}
        with self._lock:
            db = self._conn()
            try:
                db.execute(
                    """INSERT INTO model_lkg(slot, model_id, marked_at, reason)
                       VALUES(?,?,?,?)
                       ON CONFLICT(slot) DO UPDATE SET
                         model_id=excluded.model_id,
                         marked_at=excluded.marked_at,
                         reason=excluded.reason
                    """,
                    (slot, model_id, time.time(), reason),
                )
                db.commit()
            finally:
                db.close()
        # Annotate meta; keep status ACTIVE/VALIDATED as-is (LKG is a pointer, not exclusive state)
        path = self.root / model_id / "manifest.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = dict(data.get("meta") or {})
            meta["lkg"] = True
            meta["lkg_marked_at"] = time.time()
            meta["lkg_reason"] = reason
            data["meta"] = meta
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"ok": True, "model_id": model_id, "slot": slot, "reason": reason}

    def last_known_good(self, slot: str = "default") -> dict[str, Any] | None:
        with self._lock:
            db = self._conn()
            try:
                row = db.execute(
                    "SELECT model_id, marked_at, reason FROM model_lkg WHERE slot=?",
                    (slot,),
                ).fetchone()
            finally:
                db.close()
        if row:
            model = self.get(row[0])
            if model:
                return {**model, "lkg_marked_at": row[1], "lkg_reason": row[2], "is_lkg": True}
        # Fallback: previous_model_id on active slot (legacy)
        active = self.active(slot)
        if active and active.get("previous_model_id"):
            prev = self.get(active["previous_model_id"])
            if prev:
                return {**prev, "is_lkg": True, "lkg_reason": "previous_active_fallback"}
        return None

    def activate(
        self,
        model_id: str,
        *,
        slot: str = "default",
        mark_as_lkg: bool = False,
        preserve_outgoing_as_lkg: bool = True,
    ) -> dict[str, Any]:
        current = self.active(slot)
        previous_id = current.get("model_id") if current else None
        # Before switching: optionally preserve current ACTIVE as LKG (never delete checkpoints).
        # Rollback paths set preserve_outgoing_as_lkg=False so a failed candidate is not promoted to LKG.
        if preserve_outgoing_as_lkg and previous_id and previous_id != model_id:
            self.mark_lkg(previous_id, slot=slot, reason="preserved_before_activation")
        with self._lock:
            db = self._conn()
            try:
                if previous_id and previous_id != model_id:
                    db.execute(
                        "UPDATE model_versions SET status=? WHERE model_id=?",
                        (ModelStatus.VALIDATED.value, previous_id),
                    )
                db.execute(
                    "UPDATE model_versions SET status=? WHERE model_id=?",
                    (ModelStatus.ACTIVE.value, model_id),
                )
                db.execute(
                    """INSERT INTO model_active(slot, model_id, activated_at, previous_model_id)
                       VALUES(?,?,?,?)
                       ON CONFLICT(slot) DO UPDATE SET
                         model_id=excluded.model_id,
                         activated_at=excluded.activated_at,
                         previous_model_id=excluded.previous_model_id
                    """,
                    (slot, model_id, time.time(), previous_id),
                )
                db.commit()
            finally:
                db.close()
        if previous_id and previous_id != model_id:
            # Leave ROLLED_BACK status if already set by rollback manager; else VALIDATED
            cur_manifest = self.get(previous_id) or {}
            if cur_manifest.get("status") != ModelStatus.ROLLED_BACK.value:
                self.update_status(previous_id, ModelStatus.VALIDATED)
        self.update_status(model_id, ModelStatus.ACTIVE)
        # First successful activation becomes the initial LKG.
        if previous_id is None or mark_as_lkg:
            self.mark_lkg(
                model_id,
                slot=slot,
                reason="first_successful_activation" if previous_id is None else "explicit_lkg",
            )
        return self.active(slot) or {"model_id": model_id}
