"""Safe Learning Architecture — Learning → Evaluation → Validation → Memory/Knowledge.

Production never auto-mutates model weights. Learning writes reviewable knowledge
and datasets; weight training (if any) stays offline/scaffolded and owner-gated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class LearningSource(str, Enum):
    EXPERIENCE = "experience"
    TASK_OUTCOME = "task_outcome"
    FEEDBACK = "feedback"
    ERROR = "error"
    CORRECTION = "correction"
    VERIFIED_KNOWLEDGE = "verified_knowledge"
    SUCCESSFUL_WORKFLOW = "successful_workflow"


class LearningStage(str, Enum):
    INGEST = "ingest"
    EVALUATE = "evaluate"
    VALIDATE = "validate"
    STORE = "store"  # Memory / Knowledge only after validation
    IMPROVE = "improve"  # future behavior via knowledge — not silent weight swap


class LearningStatus(str, Enum):
    PROPOSED = "proposed"
    EVALUATED = "evaluated"
    VALIDATED = "validated"
    REJECTED = "rejected"
    STORED = "stored"
    ROLLED_BACK = "rolled_back"


@dataclass
class LearningCandidate:
    candidate_id: str
    source: LearningSource | str
    content: str
    status: LearningStatus | str = LearningStatus.PROPOSED
    confidence: float = 0.0
    evaluation: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LearningPipelineProtocol(Protocol):
    """Gated pipeline. Unsupervised corruption of production state is forbidden."""

    def ingest(self, source: LearningSource | str, content: str, *, meta: dict[str, Any] | None = None) -> LearningCandidate:
        ...

    def evaluate(self, candidate_id: str) -> LearningCandidate:
        ...

    def validate(self, candidate_id: str, *, approved: bool = False) -> LearningCandidate:
        ...

    def store(self, candidate_id: str) -> LearningCandidate:
        """Persist to Memory/Knowledge only when status==validated."""
        ...

    def rollback(self, candidate_id: str) -> LearningCandidate:
        ...

    def allows_weight_mutation(self) -> bool:
        """Must return False for production Core paths."""
        ...
