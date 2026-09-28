"""PHASE 20/21 Task Decomposer — smart complexity; avoid unnecessary decomposition."""
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

_PARALLEL_SAFE_CAPS = frozenset(
    {"memory_retrieval", "knowledge_retrieval", "tool_execution", "mcp", "mathematics", "document_processing"}
)
_MUTATING = frozenset({"apply_fix", "appeng_build", "remediate", "algorithm_optimize"})


class TaskDecomposer:
    """Decompose a request into dependency-ordered executable steps."""

    VERSION = "21.0.0"

    def __init__(self, router: CapabilityRouter | None = None) -> None:
        self.router = router or CapabilityRouter()

    def classify_complexity(self, message: str, *, capabilities: list[str], context: dict[str, Any] | None = None) -> dict[str, Any]:
        caps = list(capabilities or [])
        t = (message or "").lower()
        ctx = dict(context or {})
        multi_markers = sum(
            1
            for m in ("and then", "then ", "finally", "fix it", "run the tests", "implement", "optimize")
            if m in t
        )
        needs_tools = any(c in caps for c in ("tool_execution", "mcp", "testing"))
        needs_coding = any(c in caps for c in ("coding", "debugging", "application_engineering"))
        needs_research = any(c in caps for c in ("research", "web_operations"))
        needs_algorithms = "algorithms" in caps
        needs_escalation = any(c in caps for c in ("algorithms", "architecture", "debugging")) or multi_markers >= 2

        if ctx.get("force_agent_engine") or len(caps) >= 4 or multi_markers >= 2:
            level = "complex"
            decompose = True
        elif len(caps) <= 1 and len(t.split()) <= 10 and not needs_coding and not needs_algorithms:
            level = "simple"
            decompose = False
        elif len(caps) >= 2 or needs_coding or needs_algorithms or needs_research:
            level = "moderate"
            decompose = True
        else:
            level = "simple"
            decompose = False

        return {
            "level": level,
            "decompose": decompose,
            "needs_tools": needs_tools,
            "needs_coding": needs_coding,
            "needs_research": needs_research,
            "needs_algorithms": needs_algorithms,
            "needs_model_escalation": needs_escalation,
            "capability_count": len(caps),
            "multi_markers": multi_markers,
        }

    def decompose(self, message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = dict(context or {})
        route = self.router.route(message, context=ctx)
        caps = list(route.get("capabilities") or [])
        complexity = self.classify_complexity(message, capabilities=caps, context=ctx)

        # Fast path: no unnecessary decomposition
        if not complexity["decompose"] and not ctx.get("force_decompose"):
            step_id = new_id("step")
            return {
                "ok": True,
                "capabilities": caps or ["reasoning"],
                "capability_routing": route,
                "complexity": complexity,
                "decomposed": False,
                "steps": [
                    {
                        "step_id": step_id,
                        "action": "reason",
                        "label": "Direct fast response",
                        "capability": (caps or ["reasoning"])[0],
                        "depends_on": [],
                        "parallel_safe": True,
                        "mutates_files": False,
                    }
                ],
                "plan_id": new_id("plan"),
                "version": self.VERSION,
                "note": "Simple request — decomposition skipped for latency",
            }

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
        # Group independent retrieve/tool caps for parallel starts
        parallel_wave: list[str] = []
        for cap in ordered_caps:
            if cap in _PARALLEL_SAFE_CAPS and not steps:
                parallel_wave.append(cap)

        for cap in ordered_caps:
            for tmpl in _CAP_STEPS.get(cap, [{"action": f"cap_{cap}", "label": cap}]):
                step_id = new_id("step")
                mutates = tmpl["action"] in _MUTATING
                parallel_safe = cap in _PARALLEL_SAFE_CAPS and not mutates
                if parallel_safe and cap in parallel_wave:
                    deps: list[str] = []
                elif steps:
                    # Depend on last non-parallel or last step
                    deps = [steps[-1]["step_id"]]
                else:
                    deps = []
                # Independent tool/mcp can depend only on planning if present
                if parallel_safe and steps and steps[0].get("action") == "plan":
                    deps = [steps[0]["step_id"]]
                steps.append(
                    {
                        "step_id": step_id,
                        "action": tmpl["action"],
                        "label": tmpl["label"],
                        "capability": cap,
                        "depends_on": deps,
                        "parallel_safe": parallel_safe,
                        "mutates_files": mutates,
                        "requires_tools": cap in ("tool_execution", "mcp", "testing"),
                        "requires_coding": cap in ("coding", "debugging", "application_engineering"),
                        "requires_research": cap in ("research", "web_operations"),
                        "requires_algorithms": cap == "algorithms",
                        "requires_model_escalation": complexity["needs_model_escalation"]
                        and cap in ("algorithms", "architecture", "debugging", "reasoning"),
                    }
                )

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
            "complexity": complexity,
            "decomposed": True,
            "steps": steps,
            "plan_id": new_id("plan"),
            "version": self.VERSION,
            "note": "Plan composed from registries/capabilities; parallel_safe marked for independent work",
        }
