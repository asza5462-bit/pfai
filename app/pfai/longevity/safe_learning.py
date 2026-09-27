"""Safe learning pipeline scaffold — never mutates production model weights."""
from __future__ import annotations

import time
import uuid
from typing import Any

from pfai.interfaces.learning import (
    LearningCandidate,
    LearningSource,
    LearningStatus,
)


class SafeLearningPipeline:
    """Learning → Evaluation → Validation → Memory/Knowledge (scaffold).

    `allows_weight_mutation()` is hard-False for production Core paths.
    """

    def __init__(self) -> None:
        self._items: dict[str, LearningCandidate] = {}

    def allows_weight_mutation(self) -> bool:
        return False

    def ingest(
        self,
        source: LearningSource | str,
        content: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> LearningCandidate:
        cid = uuid.uuid4().hex[:12]
        cand = LearningCandidate(
            candidate_id=cid,
            source=source,
            content=content,
            status=LearningStatus.PROPOSED,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            meta=dict(meta or {}),
        )
        self._items[cid] = cand
        return cand

    def evaluate(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        # Scaffold heuristic only — real evaluators land later.
        score = 0.6 if len(cand.content.strip()) >= 8 else 0.2
        cand.evaluation = {"score": score, "method": "scaffold_heuristic"}
        cand.confidence = score
        cand.status = LearningStatus.EVALUATED
        return cand

    def validate(self, candidate_id: str, *, approved: bool = False) -> LearningCandidate:
        cand = self._require(candidate_id)
        if cand.status != LearningStatus.EVALUATED:
            raise RuntimeError("evaluate before validate")
        if not approved:
            cand.status = LearningStatus.REJECTED
            cand.validation = {"approved": False, "reason": "owner_or_policy_rejected"}
            return cand
        if float(cand.evaluation.get("score", 0)) < 0.5:
            cand.status = LearningStatus.REJECTED
            cand.validation = {"approved": False, "reason": "score_below_threshold"}
            return cand
        cand.status = LearningStatus.VALIDATED
        cand.validation = {"approved": True}
        return cand

    def store(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        if cand.status != LearningStatus.VALIDATED:
            raise RuntimeError("only validated candidates may be stored")
        cand.status = LearningStatus.STORED
        cand.meta["stored"] = True
        # Later phases write to LongTermMemory / KnowledgeVersioning.
        return cand

    def rollback(self, candidate_id: str) -> LearningCandidate:
        cand = self._require(candidate_id)
        cand.status = LearningStatus.ROLLED_BACK
        cand.meta["rolled_back"] = True
        return cand

    def _require(self, candidate_id: str) -> LearningCandidate:
        if candidate_id not in self._items:
            raise KeyError(candidate_id)
        return self._items[candidate_id]
