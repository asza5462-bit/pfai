"""PHASE 12 — Elite Skills + Tools + Models fabric shared types."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"
    DISABLED = "disabled"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    LKG = "lkg"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"


class EvidenceKind(str, Enum):
    FACT = "FACT"
    SOURCE_DERIVED_CLAIM = "SOURCE-DERIVED CLAIM"
    MODEL_INFERENCE = "MODEL INFERENCE"
    USER_PROVIDED_INFORMATION = "USER-PROVIDED INFORMATION"
    UNCERTAIN_RESULT = "UNCERTAIN RESULT"
    # Legacy aliases retained for Phase 12 compatibility
    INFERENCE = "INFERENCE"
    OPINION = "OPINION"
    UNCERTAINTY = "UNCERTAINTY"


class ToolStatusClass(str, Enum):
    REAL_PRODUCTION_TOOL = "REAL_PRODUCTION_TOOL"
    TEST_TOOL = "TEST_TOOL"
    MOCK_TOOL = "MOCK_TOOL"
    LEGACY_TOOL = "LEGACY_TOOL"


class SkillLifecycleOp(str, Enum):
    DISCOVER = "DISCOVER"
    SELECT = "SELECT"
    COMPOSE = "COMPOSE"
    EXECUTE = "EXECUTE"
    EVALUATE = "EVALUATE"
    LEARN = "LEARN"
    VERSION = "VERSION"
    PROMOTE = "PROMOTE"
    ROLLBACK = "ROLLBACK"


class OrchestratorMode(str, Enum):
    CHAT = "CHAT"
    REASON = "REASON"
    CODE = "CODE"
    RESEARCH = "RESEARCH"
    DATA = "DATA"
    DOCUMENT = "DOCUMENT"
    PLAN = "PLAN"
    SKILL = "SKILL"
    TOOL = "TOOL"
    LEARN = "LEARN"
    EVALUATE = "EVALUATE"
    SELF_CHECK = "SELF_CHECK"
    SELF_HEAL = "SELF_HEAL"


@dataclass
class SkillDefinition:
    skill_id: str
    name: str
    description: str
    version: str = "1.0.0"
    category: str = "general"
    capabilities: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    produced_outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    compatible_models: list[str] = field(default_factory=lambda: ["echo", "mock", "local", "open_weight"])
    compatible_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_model_capabilities: list[str] = field(default_factory=list)
    permissions_required: str = "READ"
    permissions: list[str] = field(default_factory=list)
    risk_level: str = RiskLevel.LOW.value
    execution_mode: str = "in_process"
    evaluation_suite: str = "skill_smoke"
    training_sources: list[str] = field(default_factory=list)
    training_metadata: dict[str, Any] = field(default_factory=dict)
    quality_metrics: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    status: str = SkillStatus.DRAFT.value
    created_at: float = 0.0
    updated_at: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)
    health: str = "unknown"
    evaluation_state: str = "unverified"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillDefinition":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ToolDefinition:
    tool_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    permissions_required: str = "READ"
    required_permissions: list[str] = field(default_factory=list)
    risk_level: str = RiskLevel.LOW.value
    owner_approval_required: bool = False
    network_access: bool = False
    filesystem_access: bool = False
    secret_access: bool = False
    execution_environment: str = "in_process"
    timeout: float = 30.0
    resource_limits: dict[str, Any] = field(default_factory=dict)
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"max_retries": 1, "backoff_seconds": 0.1})
    audit_policy: str = "always"
    tool_status_class: str = ToolStatusClass.REAL_PRODUCTION_TOOL.value
    enabled: bool = True
    health: str = "unknown"
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolDefinition":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SkillCandidate:
    skill_id: str
    name: str
    version: str
    score: float
    rationale: list[str] = field(default_factory=list)
    definition: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompositionNode:
    node_id: str
    skill_id: str
    skill_version: str = ""
    depends_on: list[str] = field(default_factory=list)
    args_map: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillGraph:
    graph_id: str
    nodes: list[CompositionNode] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "rationale": list(self.rationale),
            "version": self.version,
        }


@dataclass
class EvidenceItem:
    kind: str
    statement: str
    confidence: float = 0.5
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_ts() -> float:
    return time.time()
