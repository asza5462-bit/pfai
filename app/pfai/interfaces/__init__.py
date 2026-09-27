"""PFAI Platform contracts (PHASE 1).

These Protocols and types define the Orchestrator stacking surface.
No runtime wiring into FastAPI/Dashboard lives here — later phases implement
and adapt existing modules behind these contracts without replacing them.
"""

from .types import OrchestratorRequest, OrchestratorResult, TimelineStatus
from .model import ModelRole, ModelRouterProtocol
from .memory import MemorySystemProtocol, MemoryScope
from .knowledge import KnowledgeHit, KnowledgeLayerProtocol
from .planner import PlanStep, TaskPlan, TaskPlannerProtocol
from .skills import Skill, SkillContext, SkillResult, SkillRegistryProtocol
from .tools import ToolPermission
from .evaluation import EvalCase, EvalReport, EvaluationSuiteProtocol
from .self_check import SelfCheckReport, SelfCheckProtocol, SelfHealProtocol
from .goals import Goal, GoalSystemProtocol
from .orchestrator import OrchestratorProtocol

__all__ = [
    "OrchestratorRequest",
    "OrchestratorResult",
    "TimelineStatus",
    "ModelRole",
    "ModelRouterProtocol",
    "MemorySystemProtocol",
    "MemoryScope",
    "KnowledgeHit",
    "KnowledgeLayerProtocol",
    "PlanStep",
    "TaskPlan",
    "TaskPlannerProtocol",
    "Skill",
    "SkillContext",
    "SkillResult",
    "SkillRegistryProtocol",
    "ToolPermission",
    "EvalCase",
    "EvalReport",
    "EvaluationSuiteProtocol",
    "SelfCheckReport",
    "SelfCheckProtocol",
    "SelfHealProtocol",
    "Goal",
    "GoalSystemProtocol",
    "OrchestratorProtocol",
]
