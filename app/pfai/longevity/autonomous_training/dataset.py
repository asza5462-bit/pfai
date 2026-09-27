"""Immutable dataset versioning for autonomous training."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .sanitizer import SANITIZER_VERSION
from .types import DatasetStatus, TrainingExample
from .validator import TrainingExampleValidator


class DatasetBuilder:
    def __init__(self, validator: TrainingExampleValidator | None = None) -> None:
        self.validator = validator or TrainingExampleValidator()

    def build(
        self,
        rows: list[dict[str, Any]],
        *,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
    ) -> dict[str, Any]:
        accepted: list[TrainingExample] = []
        rejected = 0
        seen: set[str] = set()
        for row in rows:
            result = self.validator.validate(row)
            if not result.get("ok"):
                rejected += 1
                continue
            ex = result["example"]
            digest = hashlib.sha256(
                (ex["instruction"] + "\0" + ex["response"]).encode("utf-8")
            ).hexdigest()
            if digest in seen:
                rejected += 1
                continue
            seen.add(digest)
            accepted.append(
                TrainingExample(
                    example_id=digest[:16],
                    instruction=ex["instruction"],
                    response=ex["response"],
                    source=str(ex.get("source") or "unknown"),
                    source_id=str(ex.get("source_id") or ""),
                    timestamp=float(ex.get("timestamp") or time.time()),
                    quality_score=float(ex.get("quality_score") or result.get("quality_score") or 0),
                    validation_status="validated",
                    provenance=dict(ex.get("provenance") or {}),
                    content_hash=digest,
                )
            )

        # Deterministic order by content hash
        accepted.sort(key=lambda e: e.content_hash)
        n = len(accepted)
        ntr = int(n * train_ratio)
        nv = int(n * val_ratio)
        if n >= 3:
            ntr = max(1, ntr)
            nv = max(1, nv)
            nte = max(1, n - ntr - nv)
            while ntr + nv + nte > n and ntr > 1:
                ntr -= 1
        else:
            ntr = max(0, n - 2)
            nv = 1 if n >= 2 else 0
            nte = n - ntr - nv
        splits = {
            "train": accepted[:ntr],
            "validation": accepted[ntr : ntr + nv],
            "test": accepted[ntr + nv : ntr + nv + nte],
        }
        return {
            "examples": accepted,
            "splits": splits,
            "rejected": rejected,
            "accepted": n,
        }


class DatasetVersionRegistry:
    """Immutable dataset versions stored under a root + sqlite index."""

    def __init__(self, root: str = "data/longevity/training/datasets") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "dataset_registry.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._lock:
            db = self._conn()
            try:
                db.execute(
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
                db.commit()
            finally:
                db.close()

    def _next_id(self) -> str:
        with self._lock:
            db = self._conn()
            try:
                row = db.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()
                n = int(row[0] if row else 0) + 1
            finally:
                db.close()
        return f"dataset-v{n:04d}"

    def create_version(
        self,
        built: dict[str, Any],
        *,
        parent_dataset: str | None = None,
        filtering_rules: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_id = self._next_id()
        splits: dict[str, list[TrainingExample]] = built["splits"]
        payload = {
            split: [e.to_dict() for e in examples] for split, examples in splits.items()
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        checksum = hashlib.sha256(raw).hexdigest()
        created_at = time.time()
        version_dir = self.root / dataset_id
        if version_dir.exists():
            raise RuntimeError(f"dataset version already exists: {dataset_id}")
        version_dir.mkdir(parents=True, exist_ok=False)
        for split, examples in splits.items():
            path = version_dir / f"{split}.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                for ex in examples:
                    fh.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")
        manifest = {
            "dataset_id": dataset_id,
            "parent_dataset": parent_dataset,
            "status": DatasetStatus.READY.value,
            "checksum": checksum,
            "train_count": len(splits.get("train") or []),
            "validation_count": len(splits.get("validation") or []),
            "test_count": len(splits.get("test") or []),
            "sanitizer_version": SANITIZER_VERSION,
            "filtering_rules": filtering_rules or {"min_quality": 0.5, "dedupe": True},
            "validation_results": {
                "accepted": built.get("accepted", 0),
                "rejected": built.get("rejected", 0),
            },
            "source_records": sorted(
                {
                    e.source_id or e.source
                    for examples in splits.values()
                    for e in examples
                }
            ),
            "created_at": created_at,
            "meta": meta or {},
        }
        (version_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        with self._lock:
            db = self._conn()
            try:
                db.execute(
                    """INSERT INTO dataset_versions (
                        dataset_id, parent_dataset, status, checksum,
                        train_count, validation_count, test_count,
                        sanitizer_version, filtering_rules, validation_results,
                        source_records, created_at, meta
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        dataset_id,
                        parent_dataset,
                        DatasetStatus.READY.value,
                        checksum,
                        manifest["train_count"],
                        manifest["validation_count"],
                        manifest["test_count"],
                        SANITIZER_VERSION,
                        json.dumps(manifest["filtering_rules"]),
                        json.dumps(manifest["validation_results"]),
                        json.dumps(manifest["source_records"]),
                        created_at,
                        json.dumps(meta or {}),
                    ),
                )
                db.commit()
            finally:
                db.close()
        return manifest

    def get(self, dataset_id: str) -> dict[str, Any] | None:
        path = self.root / dataset_id / "manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_versions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            db = self._conn()
            try:
                rows = db.execute(
                    "SELECT dataset_id, status, checksum, train_count, validation_count, test_count, created_at "
                    "FROM dataset_versions ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            finally:
                db.close()
        return [
            {
                "dataset_id": r[0],
                "status": r[1],
                "checksum": r[2],
                "train_count": r[3],
                "validation_count": r[4],
                "test_count": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]

    def load_split(self, dataset_id: str, split: str = "train") -> list[dict[str, Any]]:
        path = self.root / dataset_id / f"{split}.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out
