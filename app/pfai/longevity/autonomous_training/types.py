"""PHASE 6 autonomous training types — provider-independent contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class JobState(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    DATA_VALIDATION = "DATA_VALIDATION"
    TRAINING = "TRAINING"
    RUNNING = "RUNNING"  # legacy alias of TRAINING
    CHECKPOINTING = "CHECKPOINTING"
    EVALUATING = "EVALUATING"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"
    TRAINING_RUNTIME_UNAVAILABLE = "TRAINING_RUNTIME_UNAVAILABLE"
    NO_COMPATIBLE_MODEL = "NO_COMPATIBLE_MODEL"


class ModelStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    TRAINING = "TRAINING"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"
    LKG = "LKG"  # marked last-known-good (may also be ACTIVE)


class ModelServingTier(str, Enum):
    """Semantic serving tier — ACTIVE ≠ production-ready."""

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    INTERNAL_ACTIVE = "internal_active"  # active pointer for lab/eval; not production
    PRODUCTION_READY = "production_ready"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class DatasetStatus(str, Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class SplitName(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class TriggerKind(str, Enum):
    MIN_EXAMPLES = "min_examples"
    PERFORMANCE_OPPORTUNITY = "performance_opportunity"
    SCHEDULED = "scheduled"
    OWNER_REQUESTED = "owner_requested"
    EXPLICIT_RETRAIN = "explicit_retrain"
    REGRESSION_RECOVERY = "regression_recovery"


class LearningEligibility(str, Enum):
    """Explicit eligibility for LearningCandidate records."""

    INELIGIBLE = "INELIGIBLE"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    USED_IN_DATASET = "USED_IN_DATASET"


class ExperienceSource(str, Enum):
    """Source attribution — not all sources are equally trustworthy."""

    USER_APPROVED = "USER_APPROVED"
    TASK_SUCCESS = "TASK_SUCCESS"
    CODE_TEST_PASS = "CODE_TEST_PASS"
    KNOWLEDGE_VERIFIED = "KNOWLEDGE_VERIFIED"
    FEEDBACK = "FEEDBACK"
    TOOL_SUCCESS = "TOOL_SUCCESS"
    SKILL_SUCCESS = "SKILL_SUCCESS"
    SELF_CHECK = "SELF_CHECK"
    CORRECTED_FAILURE = "CORRECTED_FAILURE"
    EVALUATION = "EVALUATION"
    # Internal / legacy collectors map onto the above where possible
    APPROVED_SEED = "APPROVED_SEED"


# Higher = more trustworthy for auto-accept (0..1). Below threshold → PENDING_REVIEW.
EXPERIENCE_TRUST: dict[str, float] = {
    ExperienceSource.CODE_TEST_PASS.value: 0.95,
    ExperienceSource.CORRECTED_FAILURE.value: 0.92,
    ExperienceSource.KNOWLEDGE_VERIFIED.value: 0.90,
    ExperienceSource.USER_APPROVED.value: 0.88,
    ExperienceSource.FEEDBACK.value: 0.85,
    ExperienceSource.TASK_SUCCESS.value: 0.80,
    ExperienceSource.EVALUATION.value: 0.78,
    ExperienceSource.SKILL_SUCCESS.value: 0.72,
    ExperienceSource.TOOL_SUCCESS.value: 0.70,
    ExperienceSource.SELF_CHECK.value: 0.65,
    ExperienceSource.APPROVED_SEED.value: 0.90,
}

# Auto-accept when trust >= this (else PENDING_REVIEW after quality gates).
AUTO_ACCEPT_TRUST = 0.75


@dataclass
class TrainingExample:
    example_id: str
    instruction: str
    response: str
    source: str
    source_id: str = ""
    timestamp: float = 0.0
    quality_score: float = 0.0
    validation_status: str = "pending"
    provenance: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingConfig:
    method: str = "lora"  # lora | qlora | full | mock
    base_model: str = "local"
    epochs: float = 1.0
    learning_rate: float = 2e-5
    batch_size: int = 1
    max_runtime_seconds: int = 3600
    max_dataset_size: int = 50000
    checkpoint_every_steps: int = 50
    require_gpu: bool = False
    max_retries: int = 2
    allow_mock_backend: bool = False  # tests only; never auto-activate as "real"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingResult:
    ok: bool
    job_id: str
    status: str
    backend: str
    checkpoint_path: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    is_mock: bool = False
    real_training: bool = False
    real_weight_update: bool = False
    runtime_status: str | None = None
    base_model: str | None = None
    model_revision: str | None = None
    dataset_version: str | None = None
    training_config: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FORBIDDEN_AUTHORITY_PATHS = frozenset(
    {
        "owner_auth",
        "owner_control",
        "permission_gate",
        "authorized_execution",
        "email_provider",
        "secrets",
        "security_middleware",
        "migration_safety",
        "otp",
        "pfai_owner_session",
    }
)
