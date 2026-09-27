"""LearningCandidate pipeline — observation → accept into training datasets.

Never trains on every chat. Never stores secrets/OTP/auth material.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .sanitizer import TrainingDataSanitizer
from .validator import TrainingExampleValidator


ObservationFn = Callable[[], Iterable[dict[str, Any]]]


@dataclass
class LearningCandidateRecord:
    candidate_id: str
    instruction: str
    response: str
    source: str
    source_id: str = ""
    outcome: str = "unknown"  # success | corrected | failed_then_fixed | approved | evaluated
    eligibility: str = "pending"  # pending | accepted | rejected
    rejection_reason: str = ""
    quality_score: float = 0.0
    content_hash: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    evaluated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_training_row(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "response": self.response,
            "source": self.source,
            "source_id": self.source_id or self.candidate_id,
            "verified": True,
            "provenance": {
                **dict(self.provenance or {}),
                "candidate_id": self.candidate_id,
                "outcome": self.outcome,
                "eligibility": self.eligibility,
                "labels": dict(self.labels or {}),
            },
        }


class LearningCandidateStore:
    """Immutable-ish candidate ledger with aggregate statistics."""

    def __init__(self, root: str = "data/longevity/training/candidates") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "candidates.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._lock:
            db = self._conn()
            try:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS candidates (
                        candidate_id TEXT PRIMARY KEY,
                        content_hash TEXT UNIQUE,
                        source TEXT,
                        source_id TEXT,
                        outcome TEXT,
                        eligibility TEXT,
                        rejection_reason TEXT,
                        quality_score REAL,
                        instruction TEXT,
                        response TEXT,
                        provenance TEXT,
                        labels TEXT,
                        created_at REAL,
                        evaluated_at REAL
                    )"""
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cand_elig ON candidates(eligibility)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cand_source ON candidates(source)"
                )
                db.commit()
            finally:
                db.close()

    def get_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self._lock:
            db = self._conn()
            try:
                row = db.execute(
                    "SELECT candidate_id FROM candidates WHERE content_hash=?",
                    (content_hash,),
                ).fetchone()
            finally:
                db.close()
        if not row:
            return None
        return self.get(row[0])

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        path = self.root / f"{candidate_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            db = self._conn()
            try:
                row = db.execute(
                    "SELECT candidate_id, content_hash, source, source_id, outcome, eligibility, "
                    "rejection_reason, quality_score, instruction, response, provenance, labels, "
                    "created_at, evaluated_at FROM candidates WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchone()
            finally:
                db.close()
        if not row:
            return None
        return {
            "candidate_id": row[0],
            "content_hash": row[1],
            "source": row[2],
            "source_id": row[3],
            "outcome": row[4],
            "eligibility": row[5],
            "rejection_reason": row[6],
            "quality_score": row[7],
            "instruction": row[8],
            "response": row[9],
            "provenance": json.loads(row[10] or "{}"),
            "labels": json.loads(row[11] or "{}"),
            "created_at": row[12],
            "evaluated_at": row[13],
        }

    def upsert(self, rec: LearningCandidateRecord) -> dict[str, Any]:
        data = rec.to_dict()
        path = self.root / f"{rec.candidate_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        with self._lock:
            db = self._conn()
            try:
                db.execute(
                    """INSERT INTO candidates (
                        candidate_id, content_hash, source, source_id, outcome, eligibility,
                        rejection_reason, quality_score, instruction, response, provenance,
                        labels, created_at, evaluated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                        eligibility=excluded.eligibility,
                        rejection_reason=excluded.rejection_reason,
                        quality_score=excluded.quality_score,
                        evaluated_at=excluded.evaluated_at,
                        labels=excluded.labels
                    """,
                    (
                        rec.candidate_id,
                        rec.content_hash,
                        rec.source,
                        rec.source_id,
                        rec.outcome,
                        rec.eligibility,
                        rec.rejection_reason,
                        rec.quality_score,
                        rec.instruction,
                        rec.response,
                        json.dumps(rec.provenance),
                        json.dumps(rec.labels),
                        rec.created_at,
                        rec.evaluated_at,
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                # duplicate content_hash — treat as duplicate reject
                db.rollback()
                existing = self.get_by_hash(rec.content_hash)
                if existing:
                    return {**existing, "duplicate_of": existing.get("candidate_id")}
                raise
            finally:
                db.close()
        return data

    def list_accepted(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        with self._lock:
            db = self._conn()
            try:
                rows = db.execute(
                    "SELECT candidate_id FROM candidates WHERE eligibility='accepted' "
                    "ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            finally:
                db.close()
        out = []
        for (cid,) in rows:
            item = self.get(cid)
            if item:
                out.append(item)
        return out

    def statistics(self) -> dict[str, Any]:
        with self._lock:
            db = self._conn()
            try:
                total = int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
                accepted = int(
                    db.execute(
                        "SELECT COUNT(*) FROM candidates WHERE eligibility='accepted'"
                    ).fetchone()[0]
                )
                rejected = int(
                    db.execute(
                        "SELECT COUNT(*) FROM candidates WHERE eligibility='rejected'"
                    ).fetchone()[0]
                )
                pending = int(
                    db.execute(
                        "SELECT COUNT(*) FROM candidates WHERE eligibility='pending'"
                    ).fetchone()[0]
                )
                by_source = {
                    r[0]: r[1]
                    for r in db.execute(
                        "SELECT source, COUNT(*) FROM candidates GROUP BY source"
                    ).fetchall()
                }
                by_reason = {
                    (r[0] or "none"): r[1]
                    for r in db.execute(
                        "SELECT rejection_reason, COUNT(*) FROM candidates "
                        "WHERE eligibility='rejected' GROUP BY rejection_reason"
                    ).fetchall()
                }
                by_outcome = {
                    r[0]: r[1]
                    for r in db.execute(
                        "SELECT outcome, COUNT(*) FROM candidates GROUP BY outcome"
                    ).fetchall()
                }
                qualities = [
                    float(r[0])
                    for r in db.execute(
                        "SELECT quality_score FROM candidates WHERE eligibility='accepted'"
                    ).fetchall()
                ]
            finally:
                db.close()
        avg_q = (sum(qualities) / len(qualities)) if qualities else 0.0
        buckets = {"0.0-0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, "0.85-1.0": 0}
        for q in qualities:
            if q < 0.5:
                buckets["0.0-0.5"] += 1
            elif q < 0.7:
                buckets["0.5-0.7"] += 1
            elif q < 0.85:
                buckets["0.7-0.85"] += 1
            else:
                buckets["0.85-1.0"] += 1
        return {
            "total_candidates": total,
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "pending_candidates": pending,
            "duplicates_tracked_via_hash": True,
            "rejection_reasons": by_reason,
            "source_distribution": by_source,
            "outcome_distribution": by_outcome,
            "quality_distribution": buckets,
            "avg_accepted_quality": round(avg_q, 4),
        }


class LearningCandidatePipeline:
    """Strict multi-step gate before any example can enter a dataset version."""

    def __init__(
        self,
        root: str = "data/longevity/training/candidates",
        *,
        min_quality: float | None = None,
        sanitizer: TrainingDataSanitizer | None = None,
        validator: TrainingExampleValidator | None = None,
    ) -> None:
        self.store = LearningCandidateStore(root)
        self.sanitizer = sanitizer or TrainingDataSanitizer()
        self.validator = validator or TrainingExampleValidator()
        self.min_quality = float(
            min_quality
            if min_quality is not None
            else os.environ.get("LEARNING_CANDIDATE_MIN_QUALITY", "0.55")
        )
        self._observers: dict[str, ObservationFn] = {}
        self._last_run: dict[str, Any] = {}

    def register_observer(self, name: str, fn: ObservationFn) -> None:
        self._observers[name] = fn

    def process_observation(self, raw: dict[str, Any]) -> LearningCandidateRecord:
        now = time.time()
        source = str(raw.get("source") or "unknown")
        source_id = str(raw.get("source_id") or raw.get("id") or "")
        outcome = str(raw.get("outcome") or raw.get("label") or "unknown")

        # Hidden system / security material hard reject before sanitize
        blob = json.dumps(raw, ensure_ascii=False).lower()
        for banned in (
            "pfai_owner_secret",
            "system prompt",
            "hidden system",
            "x-owner-secret",
            "authorization: bearer",
            "smtp_password",
        ):
            if banned in blob:
                return self._reject_shell(
                    source=source,
                    source_id=source_id,
                    outcome=outcome,
                    reason="security_or_hidden_material",
                    now=now,
                    raw=raw,
                )

        cleaned = self.sanitizer.sanitize_example(raw)
        if cleaned is None:
            return self._reject_shell(
                source=source,
                source_id=source_id,
                outcome=outcome,
                reason="sanitizer_rejected",
                now=now,
                raw=raw,
            )

        # PII / secret tags from sanitizer
        tags = list((cleaned.get("provenance") or {}).get("sanitizer_tags") or [])
        if "secret_redacted" in tags or "pii_redacted" in tags:
            # Single redaction may be OK if validator still passes and text remains useful;
            # hard-drop when response is mostly redacted or contains session/cookie markers.
            resp = cleaned.get("response") or ""
            if resp.count("[REDACTED]") >= 1 and len(resp.replace("[REDACTED]", "").strip()) < 20:
                return self._reject_shell(
                    source=source,
                    source_id=source_id,
                    outcome=outcome,
                    reason="secret_or_pii_dominant",
                    now=now,
                    raw=raw,
                )

        if self.sanitizer.contains_forbidden_authority(
            f"{cleaned.get('instruction','')}\n{cleaned.get('response','')}"
        ):
            return self._reject_shell(
                source=source,
                source_id=source_id,
                outcome=outcome,
                reason="authority_isolation_violation",
                now=now,
                raw=raw,
            )

        validated = self.validator.validate({**cleaned, "verified": bool(raw.get("verified", True))})
        if not validated.get("ok"):
            return self._reject_shell(
                source=source,
                source_id=source_id,
                outcome=outcome,
                reason=str(validated.get("reason") or "quality_failed"),
                now=now,
                raw=raw,
                instruction=cleaned.get("instruction", ""),
                response=cleaned.get("response", ""),
            )

        ex = validated["example"]
        quality = float(validated.get("quality_score") or ex.get("quality_score") or 0)
        if quality < self.min_quality:
            return self._reject_shell(
                source=source,
                source_id=source_id,
                outcome=outcome,
                reason="below_quality_threshold",
                now=now,
                raw=raw,
                instruction=ex["instruction"],
                response=ex["response"],
                quality=quality,
            )

        digest = hashlib.sha256(
            (ex["instruction"] + "\0" + ex["response"]).encode("utf-8")
        ).hexdigest()
        existing = self.store.get_by_hash(digest)
        if existing:
            return LearningCandidateRecord(
                candidate_id=existing["candidate_id"],
                instruction=existing["instruction"],
                response=existing["response"],
                source=existing["source"],
                source_id=existing.get("source_id") or "",
                outcome=existing.get("outcome") or outcome,
                eligibility="rejected",
                rejection_reason="duplicate",
                quality_score=float(existing.get("quality_score") or quality),
                content_hash=digest,
                provenance=dict(existing.get("provenance") or {}),
                labels={"duplicate": True},
                created_at=float(existing.get("created_at") or now),
                evaluated_at=now,
            )

        cand_id = f"lc-{digest[:16]}"
        provenance = dict(ex.get("provenance") or {})
        provenance.update(
            {
                "source": source,
                "source_id": source_id,
                "eligible_for_learning": True,
                "observation_ts": float(raw.get("timestamp") or now),
                "pipeline": "LearningCandidatePipeline",
            }
        )
        labels = {
            "outcome": outcome,
            "category": str(raw.get("category") or provenance.get("category") or source),
        }
        rec = LearningCandidateRecord(
            candidate_id=cand_id,
            instruction=ex["instruction"],
            response=ex["response"],
            source=source,
            source_id=source_id,
            outcome=outcome,
            eligibility="accepted",
            rejection_reason="",
            quality_score=quality,
            content_hash=digest,
            provenance=provenance,
            labels=labels,
            created_at=now,
            evaluated_at=now,
        )
        stored = self.store.upsert(rec)
        if stored.get("duplicate_of"):
            rec.eligibility = "rejected"
            rec.rejection_reason = "duplicate"
            rec.labels["duplicate"] = True
        return rec

    def _reject_shell(
        self,
        *,
        source: str,
        source_id: str,
        outcome: str,
        reason: str,
        now: float,
        raw: dict[str, Any],
        instruction: str = "",
        response: str = "",
        quality: float = 0.0,
    ) -> LearningCandidateRecord:
        # Use unstable hash including reason so rejects don't collide with accepts
        base = (instruction or str(raw.get("instruction") or "")) + "\0" + (
            response or str(raw.get("response") or raw.get("content") or "")
        )
        digest = hashlib.sha256((base + "\0" + reason + "\0" + source_id).encode()).hexdigest()
        cand_id = f"lc-rej-{digest[:14]}"
        rec = LearningCandidateRecord(
            candidate_id=cand_id,
            instruction=(instruction or str(raw.get("instruction") or ""))[:2000],
            response=(response or str(raw.get("response") or ""))[:2000],
            source=source,
            source_id=source_id,
            outcome=outcome,
            eligibility="rejected",
            rejection_reason=reason,
            quality_score=quality,
            content_hash=digest,
            provenance={"eligible_for_learning": False, "rejection_reason": reason},
            labels={"rejected": True},
            created_at=now,
            evaluated_at=now,
        )
        # Best-effort persist rejects for stats (ignore hash collisions)
        try:
            self.store.upsert(rec)
        except Exception:
            pass
        return rec

    def collect_and_process(self, *, sources: list[str] | None = None) -> dict[str, Any]:
        names = sources or list(self._observers.keys())
        observed = 0
        accepted = 0
        rejected = 0
        duplicates = 0
        reasons: dict[str, int] = {}
        accepted_rows: list[dict[str, Any]] = []
        for name in names:
            fn = self._observers.get(name)
            if not fn:
                continue
            try:
                batch = list(fn() or [])
            except Exception:
                continue
            for item in batch:
                observed += 1
                row = dict(item)
                row.setdefault("source", name)
                rec = self.process_observation(row)
                if rec.eligibility == "accepted":
                    accepted += 1
                    accepted_rows.append(rec.to_training_row())
                else:
                    rejected += 1
                    if rec.rejection_reason == "duplicate":
                        duplicates += 1
                    reasons[rec.rejection_reason or "unknown"] = (
                        reasons.get(rec.rejection_reason or "unknown", 0) + 1
                    )
        stats = self.store.statistics()
        result = {
            "ok": True,
            "observed": observed,
            "accepted_this_run": accepted,
            "rejected_this_run": rejected,
            "duplicates_this_run": duplicates,
            "rejection_reasons_this_run": reasons,
            "accepted_rows": accepted_rows,
            "store_statistics": stats,
            "at": time.time(),
        }
        self._last_run = {k: v for k, v in result.items() if k != "accepted_rows"}
        return result

    def accepted_training_rows(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        rows = []
        for item in self.store.list_accepted(limit=limit):
            rows.append(
                LearningCandidateRecord(
                    candidate_id=item["candidate_id"],
                    instruction=item["instruction"],
                    response=item["response"],
                    source=item["source"],
                    source_id=item.get("source_id") or "",
                    outcome=item.get("outcome") or "unknown",
                    eligibility="accepted",
                    quality_score=float(item.get("quality_score") or 0),
                    content_hash=item.get("content_hash") or "",
                    provenance=dict(item.get("provenance") or {}),
                    labels=dict(item.get("labels") or {}),
                    created_at=float(item.get("created_at") or 0),
                    evaluated_at=float(item.get("evaluated_at") or 0),
                ).to_training_row()
            )
        return rows

    def last_run_summary(self) -> dict[str, Any]:
        return dict(self._last_run or {})
