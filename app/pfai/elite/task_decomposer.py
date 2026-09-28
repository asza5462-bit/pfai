"""PHASE 20 Task Decomposer — capability-driven plans; not a single hard-coded example."""
from __future__ import annotations

from typing import Any

from pfai.elite.capability_router import CapabilityRouter
from pfai.elite.types import new_id


# Capability → ordered step templates (composed dynamically)
_CAP_STEPS: dict[str, list[dict[str, str]]] = {
    "planning": [{"action": "plan", "label": "Build execution plan"}],
    "memory_retrieval": [{"action": "memory_retrieve", "label": "Retrieve relevant memory/context"}],
    "knowledge_retrieval": [{"action": "knowledge_retrieve", "label": "Retrieve verified knowledge"}],
    "architecture": [{"action": "inspect_architecture", "label": "Understand architecture"}],
    "coding": [
        {"action": "inspect_repository", "label": "Inspect repository"},
        {"action": "code_search", "label": "Search code"},
        {"action": "understand_code", "label": "Understand code"},
    ],
    "debugging": [
        {"action": "diagnose_bug", "label": "Diagnose bug"},
        {"action": "propose_fix", "label": "Propose fix"},
        {"action": "apply_fix", "label": "Apply bounded fix"},
    ],
    "algorithms": [
        {"action": "algorithm_analyze", "label": "Analyze algorithm"},
        {"action": "algorithm_optimize", "label": "Propose/implement optimization"},
        {"action": "algorithm_test", "label": "Test algorithm implementation"},
    ],
    "application_engineering": [
        {"action": "appeng_build", "label": "Application engineering build/modify"},
    ],
    "security_analysis": [
        {"action": "security_analyze", "label": "Security analysis"},
    ],
    "remediation": [
        {"action": "remediate", "label": "Bounded remediation"},
    ],
    "testing": [
        {"action": "run_tests", "label": "Run tests"},
        {"action": "regression_check", "label": "Regression check"},
    ],
    "research": [
        {"action": "research", "label": "Research workflow"},
    ],
    "web_operations": [
        {"action": "web_ops", "label": "Web operations (if configured)"},
    ],
    "document_processing": [
        {"action": "document_process", "label": "Document processing"},
    ],
    "data_analysis": [
        {"action": "data_analyze", "label": "Data analysis"},
    ],
    "mathematics": [
        {"action": "math_analyze", "label": "Mathematics / calculation"},
    ],
    "tool_execution": [
        {"action": "tool_execute", "label": "Authorized tool execution"},
    ],
    "mcp": [
        {"action": "mcp_execute", "label": "Authorized MCP execution"},
    ],
    "evaluation": [
        {"action": "evaluate", "label": "Evaluate outcome"},
    ],
    "learning": [
        {"action": "record_experience", "label": "Record validated experience"},
    ],
    "reasoning": [
        {"action": "reason", "label": "Reason / explain"},
    ],
}


class TaskDecomposer:
    """Decompose a request into dependency-ordered executable steps."""

    VERSION = "20.0.0"

    def __init__(self, router: CapabilityRouter | None = None) -> None:
        self.router = router or CapabilityRouter()

    def decompose(self, message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = dict(context or {})
        route = self.router.route(message, context=ctx)
        caps = list(route.get("capabilities") or [])

        # Order capabilities for dependency-aware sequencing
        priority = [
            "planning",
            "memory_retrieval",
            "knowledge_retrieval",
            "architecture",
            "coding",
            "algorithms",
            "debugging",
            "application_engineering",
            "security_analysis",
            "remediation",
            "testing",
            "research",
            "web_operations",
            "document_processing",
            "data_analysis",
            "mathematics",
            "tool_execution",
            "mcp",
            "evaluation",
            "learning",
            "reasoning",
        ]
        ordered_caps = [c for c in priority if c in caps]
        for c in caps:
            if c not in ordered_caps:
                ordered_caps.append(c)

        steps: list[dict[str, Any]] = []
        for cap in ordered_caps:
            for tmpl in _CAP_STEPS.get(cap, [{"action": f"cap_{cap}", "label": cap}]):
                step_id = new_id("step")
                deps = [steps[-1]["step_id"]] if steps else []
                # Safe parallel groups: memory/knowledge independent of each other at start
                parallel_safe = cap in ("memory_retrieval", "knowledge_retrieval") and len(steps) <= 1
                steps.append(
                    {
                        "step_id": step_id,
                        "action": tmpl["action"],
                        "label": tmpl["label"],
                        "capability": cap,
                        "depends_on": [] if parallel_safe else deps,
                        "parallel_safe": parallel_safe,
                        "mutates_files": tmpl["action"]
                        in ("apply_fix", "appeng_build", "remediate", "algorithm_optimize"),
                    }
                )

        # Always end with final report if multi-step
        if len(steps) >= 2:
            steps.append(
                {
                    "step_id": new_id("step"),
                    "action": "final_report",
                    "label": "Produce final report",
                    "capability": "evaluation",
                    "depends_on": [steps[-1]["step_id"]],
                    "parallel_safe": False,
                    "mutates_files": False,
                }
            )

        return {
            "ok": True,
            "capabilities": ordered_caps,
            "capability_routing": route,
            "steps": steps,
            "plan_id": new_id("plan"),
            "version": self.VERSION,
            "note": "Plan composed from registries/capabilities; not a single hard-coded script",
        }
