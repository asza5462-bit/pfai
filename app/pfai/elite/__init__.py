"""PHASE 12/13 Elite AI Skills + Tool Fabric.

EliteOrchestrator is lazy-imported to avoid circular imports with
pfai.engineering (engineering → sandbox → elite → orchestrator → engineering).
"""

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.discovery import SkillDiscoveryEngine
from pfai.elite.composer import SkillComposer
from pfai.elite.tool_fabric import ToolFabric
from pfai.elite.mcp_adapter import MCPAdapter
from pfai.elite.sandbox import Sandbox
from pfai.elite.web_fabric import (
    WebInformationFabric,
    WEB_PROVIDER_UNAVAILABLE,
    WebProviderRegistry,
    WebResearchExecutor,
)

__all__ = [
    "EliteOrchestrator",
    "SkillRegistry2",
    "SkillDiscoveryEngine",
    "SkillComposer",
    "ToolFabric",
    "MCPAdapter",
    "Sandbox",
    "WebInformationFabric",
    "WEB_PROVIDER_UNAVAILABLE",
    "WebProviderRegistry",
    "WebResearchExecutor",
    "WebProvider",
    "SearchProvider",
    "FetchProvider",
    "MockWebProvider",
]


def __getattr__(name: str):
    if name == "EliteOrchestrator":
        from pfai.elite.unified_orchestrator import EliteOrchestrator

        return EliteOrchestrator
    if name in ("WebProvider", "SearchProvider", "FetchProvider", "MockWebProvider"):
        from pfai.elite import web_fabric as wf

        return getattr(wf, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
