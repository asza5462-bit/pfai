"""PFAI Platform + Longevity contracts (Architecture Foundation).

These Protocols define replaceable boundaries for a 20–30 year adaptive platform.
No runtime wiring into FastAPI/Dashboard lives here — later phases implement
adapters behind these contracts without replacing existing features.
"""

from .types import OrchestratorRequest, OrchestratorResult, TimelineStatus
from .model import (
    ModelRole,
    ModelRouterProtocol,
    ProviderSpec,
    ModelRegistration,
    ProviderRegistryProtocol,
    ModelRegistryProtocol,
)
from .memory import (
    MemorySystemProtocol,
    MemoryScope,
    MemoryKind,
    MemoryRecord,
    LongTermMemoryProtocol,
)
from .knowledge import KnowledgeHit, KnowledgeLayerProtocol
from .planner import PlanStep, TaskPlan, TaskPlannerProtocol
from .skills import (
    Skill,
    SkillContext,
    SkillResult,
    SkillRegistryProtocol,
    VersionedSkillRegistryProtocol,
)
from .tools import ToolPermission
from .evaluation import (
    EvalCase,
    EvalReport,
    EvaluationSuiteProtocol,
    VersionCompareReport,
    VersionComparisonProtocol,
)
from .self_check import (
    SelfCheckReport,
    SelfCheckProtocol,
    SelfHealProtocol,
    HealStep,
    HealProposal,
    HealResult,
)
from .goals import Goal, GoalSystemProtocol
from .orchestrator import OrchestratorProtocol
from .ports import (
    StoragePort,
    RelationalStorePort,
    VectorStorePort,
    EmbeddingPort,
    BlobStorePort,
    ExportPort,
    ClockPort,
)
from .learning import (
    LearningSource,
    LearningStage,
    LearningStatus,
    LearningCandidate,
    LearningPipelineProtocol,
)
from .versioning import (
    VersionStatus,
    Provenance,
    KnowledgeVersion,
    ConfigVersion,
    SkillVersion,
    ToolVersion,
    VersionedStoreProtocol,
    KnowledgeVersioningProtocol,
)
from .migration import PFAI_SCHEMA_VERSION, Migration, MigrationReport, MigrationRunnerProtocol
from .backup import BackupRecord, RestoreReport, BackupPort, RestorePort, DisasterRecoveryPort
from .compat import CompatibilityReport, CompatibilityLayerProtocol

__all__ = [
    "OrchestratorRequest",
    "OrchestratorResult",
    "TimelineStatus",
    "ModelRole",
    "ModelRouterProtocol",
    "ProviderSpec",
    "ModelRegistration",
    "ProviderRegistryProtocol",
    "ModelRegistryProtocol",
    "MemorySystemProtocol",
    "MemoryScope",
    "MemoryKind",
    "MemoryRecord",
    "LongTermMemoryProtocol",
    "KnowledgeHit",
    "KnowledgeLayerProtocol",
    "PlanStep",
    "TaskPlan",
    "TaskPlannerProtocol",
    "Skill",
    "SkillContext",
    "SkillResult",
    "SkillRegistryProtocol",
    "VersionedSkillRegistryProtocol",
    "ToolPermission",
    "EvalCase",
    "EvalReport",
    "EvaluationSuiteProtocol",
    "VersionCompareReport",
    "VersionComparisonProtocol",
    "SelfCheckReport",
    "SelfCheckProtocol",
    "SelfHealProtocol",
    "HealStep",
    "HealProposal",
    "HealResult",
    "Goal",
    "GoalSystemProtocol",
    "OrchestratorProtocol",
    "StoragePort",
    "RelationalStorePort",
    "VectorStorePort",
    "EmbeddingPort",
    "BlobStorePort",
    "ExportPort",
    "ClockPort",
    "LearningSource",
    "LearningStage",
    "LearningStatus",
    "LearningCandidate",
    "LearningPipelineProtocol",
    "VersionStatus",
    "Provenance",
    "KnowledgeVersion",
    "ConfigVersion",
    "SkillVersion",
    "ToolVersion",
    "VersionedStoreProtocol",
    "KnowledgeVersioningProtocol",
    "PFAI_SCHEMA_VERSION",
    "Migration",
    "MigrationReport",
    "MigrationRunnerProtocol",
    "BackupRecord",
    "RestoreReport",
    "BackupPort",
    "RestorePort",
    "DisasterRecoveryPort",
    "CompatibilityReport",
    "CompatibilityLayerProtocol",
]
