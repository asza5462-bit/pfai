"""Durable Safe Learning Pipeline — SQLite-backed, reversible, no weight mutation.

Learning → Evaluation → Validation → Memory/Knowledge (versioned) → audit.
Never mutates production code, model weights, security settings, or Core architecture.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from pfai.interfaces.learning import (
    LearningCandidate,
    LearningSource,
    LearningStatus,
)
from pfai.interfaces.versioning import KnowledgeVersion, Provenance, VersionStatus


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LearningAuditLog:
    def __init__(self, path: str = "data/longevity/learning_audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record(self, event: str, **payload: Any) -> None:
        row = {"ts": _now(), "event": event, **payload}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


class KnowledgeVersionStore:
    """Versioned knowledge with activate + rollback (audited new version rows)."""

    def __init__(self, path: str = "data/longevity/knowledge_versions.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS knowledge_versions (
                    knowledge_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    confidence REAL,
                    status TEXT,
                    provenance TEXT,
                    meta TEXT,
                    PRIMARY KEY (knowledge_id, version)
                )"""
            )
            self.db.commit()

    def publish(self, record: KnowledgeVersion) -> KnowledgeVersion:
        with self._lock:
            cur = self.db.execute(
                "SELECT COALESCE(MAX(version), 0) FROM knowledge_versions WHERE knowledge_id=?",
                (record.knowledge_id,),
            )
            nxt = int(cur.fetchone()[0]) + 1
            # supersede prior active
            self.db.execute(
                "UPDATE knowledge_versions SET status=? WHERE knowledge_id=? AND status=?",
                (VersionStatus.SUPERSEDED.value, record.knowledge_id, VersionStatus.ACTIVE.value),
            )
            status = (
                record.status.value if isinstance(record.status, VersionStatus) else str(record.status)
            )
            if status == VersionStatus.DRAFT.value:
                status = VersionStatus.ACTIVE.value
            self.db.execute(
                """INSERT INTO knowledge_versions
                   (knowledge_id, version, content, timestamp, source, confidence, status, provenance, meta)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    record.knowledge_id,
                    nxt,
                    record.content,
                    record.timestamp or _now(),
                    record.source,
                    float(record.confidence),
                    status,
                    json.dumps(
                        {
                            "source": record.provenance.source,
                            "actor": record.provenance.actor,
                            "method": record.provenance.method,
                            "references": record.provenance.references,
                            "extra": record.provenance.extra,
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(record.meta or {}, ensure_ascii=False),
                ),
            )
            self.db.commit()
            record.version = nxt
            record.status = status
            record.timestamp = record.timestamp or _now()
            return record

    def activate(self, knowledge_id: str, version: int, *, approved: bool = False) -> KnowledgeVersion:
        if not approved:
            raise PermissionError("owner approval required to activate knowledge version")
        with self._lock:
            row = self.db.execute(
                "SELECT knowledge_id, version, content, timestamp, source, confidence, status, provenance, meta "
                "FROM knowledge_versions WHERE knowledge_id=? AND version=?",
                (knowledge_id, int(version)),
            ).fetchone()
            if not row:
                raise KeyError("knowledge version not found")
            self.db.execute(
                "UPDATE knowledge_versions SET status=? WHERE knowledge_id=? AND status=?",
                (VersionStatus.SUPERSEDED.value, knowledge_id, VersionStatus.ACTIVE.value),
            )
            self.db.execute(
                "UPDATE knowledge_versions SET status=? WHERE knowledge_id=? AND version=?",
                (VersionStatus.ACTIVE.value, knowledge_id, int(version)),
            )
            self.db.commit()
            return self._row_to_kv(row, status=VersionStatus.ACTIVE.value)

    def rollback(self, knowledge_id: str, to_version: int) -> KnowledgeVersion:
        with self._lock:
            row = self.db.execute(
                "SELECT knowledge_id, version, content, timestamp, source, confidence, status, provenance, meta "
                "FROM knowledge_versions WHERE knowledge_id=? AND version=?",
                (knowledge_id, int(to_version)),
            ).fetchone()
            if not row:
                raise KeyError("knowledge version not found")
            # Mark current active as rolled_back, re-publish prior content as new active version
            self.db.execute(
                "UPDATE knowledge_versions SET status=? WHERE knowledge_id=? AND status=?",
                (VersionStatus.ROLLED_BACK.value, knowledge_id, VersionStatus.ACTIVE.value),
            )
            self.db.commit()
        prov = Provenance(source="rollback", method="knowledge_rollback", extra={"to_version": int(to_version)})
        return self.publish(
            KnowledgeVersion(
                knowledge_id=knowledge_id,
                version=0,
                content=row[2],
                timestamp=_now(),
                source=row[4] or "rollback",
                confidence=float(row[5] or 0),
                status=VersionStatus.ACTIVE,
                provenance=prov,
                meta={"rolled_back_from_active": True, "restored_version": int(to_version)},
            )
        )

    def history(self, knowledge_id: str) -> list[KnowledgeVersion]:
        with self._lock:
            rows = self.db.execute(
                "SELECT knowledge_id, version, content, timestamp, source, confidence, status, provenance, meta "
                "FROM knowledge_versions WHERE knowledge_id=? ORDER BY version ASC",
                (knowledge_id,),
            ).fetchall()
        return [self._row_to_kv(r) for r in rows]

    def active(self, knowledge_id: str) -> KnowledgeVersion | None:
        with self._lock:
            row = self.db.execute(
                "SELECT knowledge_id, version, content, timestamp, source, confidence, status, provenance, meta "
                "FROM knowledge_versions WHERE knowledge_id=? AND status=? ORDER BY version DESC LIMIT 1",
                (knowledge_id, VersionStatus.ACTIVE.value),
            ).fetchone()
        return self._row_to_kv(row) if row else None

    def _row_to_kv(self, row, status: str | None = None) -> KnowledgeVersion:
        prov_raw = json.loads(row[7] or "{}")
        meta = json.loads(row[8] or "{}")
        return KnowledgeVersion(
            knowledge_id=row[0],
            version=int(row[1]),
            content=row[2],
            timestamp=row[3],
            source=row[4] or "",
            confidence=float(row[5] or 0),
            status=status or row[6],
            provenance=Provenance(
                source=prov_raw.get("source", ""),
                actor=prov_raw.get("actor", ""),
                method=prov_raw.get("method", ""),
                references=list(prov_raw.get("references") or []),
                extra=dict(prov_raw.get("extra") or {}),
            ),
            meta=meta,
        )


class DurableSafeLearningPipeline:
    """Persistent learning candidates + gated store into versioned knowledge / memory."""

    def __init__(
        self,
        path: str = "data/longevity/learning.sqlite3",
        *,
        knowledge_store: KnowledgeVersionStore | None = None,
        audit: LearningAuditLog | None = None,
        memory_remember: Callable[..., Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.knowledge = knowledge_store or KnowledgeVersionStore()
        self.audit = audit or LearningAuditLog()
        self.memory_remember = memory_remember
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS learning_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source TEXT,
                    content TEXT,
                    status TEXT,
                    confidence REAL,
                    evaluation TEXT,
                    validation TEXT,
                    provenance TEXT,
                    created_at TEXT,
                    meta TEXT,
                    knowledge_id TEXT
                )"""
            )
            self.db.commit()

    def allows_weight_mutation(self) -> bool:
        return False

    def training_readiness(self) -> dict[str, Any]:
        """Prepare architecture for future fine-tuning without running training."""
        return {
            "weight_training_allowed_now": False,
            "allows_weight_mutation": False,
            "dataset_export_ready": True,
            "note": "Collect validated knowledge only; offline fine-tune is a future optional pipeline.",
            "stored_candidates": self.count_by_status(LearningStatus.STORED.value),
            "validated_candidates": self.count_by_status(LearningStatus.VALIDATED.value),
        }

    def count_by_status(self, status: str) -> int:
        with self._lock:
            row = self.db.execute(
                "SELECT COUNT(*) FROM learning_candidates WHERE status=?", (status,)
            ).fetchone()
        return int(row[0] if row else 0)

    def ingest(
        self,
        source: LearningSource | str,
        content: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> LearningCandidate:
        src = source.value if isinstance(source, LearningSource) else str(source)
        cid = uuid.uuid4().hex[:12]
        cand = LearningCandidate(
            candidate_id=cid,
            source=src,
            content=content,
            status=LearningStatus.PROPOSED.value,
            created_at=_now(),
            meta=dict(meta or {}),
        )
        self._save(cand)
        self.audit.record("ingest", candidate_id=cid, source=src)
        return cand

    def evaluate(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        score = 0.6 if len(cand.content.strip()) >= 8 else 0.2
        # Prefer slightly higher score when provenance marks verified
        if (cand.meta or {}).get("verified"):
            score = max(score, 0.75)
        cand.evaluation = {"score": score, "method": "durable_heuristic_v1"}
        cand.confidence = score
        cand.status = LearningStatus.EVALUATED.value
        self._save(cand)
        self.audit.record("evaluate", candidate_id=candidate_id, score=score)
        return cand

    def validate(self, candidate_id: str, *, approved: bool = False) -> LearningCandidate:
        cand = self._require(candidate_id)
        status = cand.status.value if isinstance(cand.status, LearningStatus) else str(cand.status)
        if status != LearningStatus.EVALUATED.value:
            raise RuntimeError("evaluate before validate")
        if not approved:
            cand.status = LearningStatus.REJECTED.value
            cand.validation = {"approved": False, "reason": "owner_or_policy_rejected"}
            self._save(cand)
            self.audit.record("validate_rejected", candidate_id=candidate_id)
            return cand
        if float((cand.evaluation or {}).get("score", 0)) < 0.5:
            cand.status = LearningStatus.REJECTED.value
            cand.validation = {"approved": False, "reason": "score_below_threshold"}
            self._save(cand)
            self.audit.record("validate_score_reject", candidate_id=candidate_id)
            return cand
        cand.status = LearningStatus.VALIDATED.value
        cand.validation = {"approved": True, "at": _now()}
        self._save(cand)
        self.audit.record("validate_approved", candidate_id=candidate_id)
        return cand

    def store(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        status = cand.status.value if isinstance(cand.status, LearningStatus) else str(cand.status)
        if status != LearningStatus.VALIDATED.value:
            raise RuntimeError("only validated candidates may be stored")
        kid = cand.meta.get("knowledge_id") or f"learn-{candidate_id}"
        kv = self.knowledge.publish(
            KnowledgeVersion(
                knowledge_id=kid,
                version=0,
                content=cand.content,
                timestamp=_now(),
                source=str(cand.source),
                confidence=float(cand.confidence),
                status=VersionStatus.ACTIVE,
                provenance=Provenance(
                    source=str(cand.source),
                    method="safe_learning_store",
                    references=[candidate_id],
                ),
                meta={"candidate_id": candidate_id},
            )
        )
        if self.memory_remember:
            try:
                self.memory_remember(
                    "verified_knowledge",
                    cand.content,
                    source=f"learning:{candidate_id}",
                    confidence=float(cand.confidence),
                )
            except TypeError:
                self.memory_remember("verified_knowledge", cand.content)
            except Exception:
                pass
        cand.status = LearningStatus.STORED.value
        cand.meta["stored"] = True
        cand.meta["knowledge_id"] = kid
        cand.meta["knowledge_version"] = kv.version
        self._save(cand)
        self.audit.record(
            "store",
            candidate_id=candidate_id,
            knowledge_id=kid,
            knowledge_version=kv.version,
        )
        return cand

    def rollback(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        kid = (cand.meta or {}).get("knowledge_id")
        if kid:
            hist = self.knowledge.history(kid)
            if len(hist) >= 2:
                # roll knowledge to previous version when available
                prev = hist[-2].version
                self.knowledge.rollback(kid, prev)
        cand.status = LearningStatus.ROLLED_BACK.value
        cand.meta["rolled_back"] = True
        self._save(cand)
        self.audit.record("rollback", candidate_id=candidate_id, knowledge_id=kid)
        return cand

    def get(self, candidate_id: str) -> LearningCandidate:
        return self._require(candidate_id)

    def list_candidates(self, *, status: str | None = None, limit: int = 50) -> list[LearningCandidate]:
        with self._lock:
            if status:
                rows = self.db.execute(
                    "SELECT candidate_id FROM learning_candidates WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, int(limit)),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT candidate_id FROM learning_candidates ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [self._require(r[0]) for r in rows]

    def _save(self, cand: LearningCandidate) -> None:
        status = cand.status.value if isinstance(cand.status, LearningStatus) else str(cand.status)
        source = cand.source.value if isinstance(cand.source, LearningSource) else str(cand.source)
        with self._lock:
            self.db.execute(
                """INSERT OR REPLACE INTO learning_candidates
                   (candidate_id, source, content, status, confidence, evaluation, validation,
                    provenance, created_at, meta, knowledge_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cand.candidate_id,
                    source,
                    cand.content,
                    status,
                    float(cand.confidence),
                    json.dumps(cand.evaluation or {}, ensure_ascii=False),
                    json.dumps(cand.validation or {}, ensure_ascii=False),
                    json.dumps(cand.provenance or {}, ensure_ascii=False),
                    cand.created_at or _now(),
                    json.dumps(cand.meta or {}, ensure_ascii=False),
                    (cand.meta or {}).get("knowledge_id"),
                ),
            )
            self.db.commit()

    def _require(self, candidate_id: str) -> LearningCandidate:
        with self._lock:
            row = self.db.execute(
                "SELECT candidate_id, source, content, status, confidence, evaluation, validation, "
                "provenance, created_at, meta FROM learning_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        if not row:
            raise KeyError(candidate_id)
        return LearningCandidate(
            candidate_id=row[0],
            source=row[1],
            content=row[2],
            status=row[3],
            confidence=float(row[4] or 0),
            evaluation=json.loads(row[5] or "{}"),
            validation=json.loads(row[6] or "{}"),
            provenance=json.loads(row[7] or "{}"),
            created_at=row[8] or "",
            meta=json.loads(row[9] or "{}"),
        )

