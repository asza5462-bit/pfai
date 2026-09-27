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
