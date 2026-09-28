"""PHASE 19 Capability Router — multi-capability discovery without hard-coding every task."""
from __future__ import annotations

import re
from typing import Any


# Capability ids used by UnifiedAICore (honest: mapped to real subsystems)
CAPABILITIES: tuple[str, ...] = (
    "reasoning",
    "planning",
    "coding",
    "debugging",
    "architecture",
    "application_engineering",
    "security_analysis",
    "research",
    "web_operations",
    "document_processing",
    "data_analysis",
    "mathematics",
    "algorithms",
    "testing",
    "remediation",
    "tool_execution",
    "mcp",
    "memory_retrieval",
    "knowledge_retrieval",
    "learning",
    "evaluation",
    "model_training",
)

_HINTS: dict[str, tuple[str, ...]] = {
    "reasoning": ("why", "reason", "explain", "analyze", "think", "understand"),
    "planning": ("plan", "steps", "workflow", "decompose", "roadmap"),
    "coding": (
        "code",
        "implement",
        "function",
        "class",
        "refactor",
        "write a",
        "programming",
        "repository",
        "this project",
        "the project",
        "bottleneck",
        "performance",
    ),
    "debugging": (
        "bug",
        "debug",
        "fix the bug",
        "fix it",
        "fix the",
        "traceback",
        "stack trace",
        "failing test",
        "diagnose",
    ),
    "architecture": ("architecture", "design the system", "system design", "component diagram", "review this component"),
    "application_engineering": (
        "build a website",
        "build an api",
        "full-stack",
        "create an application",
        "application engineering",
        "ابن",
        "موقعا",
    ),
    "security_analysis": (
        "security",
        "vulnerabilit",
        "cwe",
        "owasp",
        "secure code",
        "threat model",
        "check security",
        "افحص",
        "أصلح",
    ),
    "research": ("research", "cite", "sources", "paper", "literature"),
    "web_operations": ("web search", "fetch url", "http://", "https://", "browse", "crawl"),
    "document_processing": ("document", "summarize pdf", "extract from doc", "outline the document"),
    "data_analysis": ("dataset", "statistics", "mean", "plot", "dataframe", "csv analysis"),
    "mathematics": ("math", "equation", "prove", "integral", "derivative", "matrix"),
    "algorithms": (
        "algorithm",
        "complexity",
        "big-o",
        "big o",
        "o(n",
        "edge case",
        "optimize the algorithm",
        "sorting",
        "graph search",
        "dynamic programming",
        "asymptotic",
    ),
    "testing": ("run tests", "unit test", "pytest", "regression test", "test suite", "run the tests"),
    "remediation": ("remediat", "apply fix", "patch the", "اصلح", "أصلح"),
    "tool_execution": ("run command", "invoke tool", "execute tool", "use tools", "use tool"),
    "mcp": ("mcp ", "mcp tool", "model context protocol"),
    "memory_retrieval": ("remember", "recall", "from memory", "what did we", "previous context"),
    "knowledge_retrieval": ("knowledge base", "verified knowledge", "known fact"),
    "learning": ("learn from", "record experience", "training candidate"),
    "evaluation": ("evaluate", "quality gate", "score the result", "benchmark", "explain the result"),
    "model_training": ("train model", "fine-tune", "lora", "autonomous training", "retrain"),
}


class CapabilityRouter:
    """Determine which capabilities a request requires — composable, multi-label."""

    VERSION = "19.0.0"

    def route(self, message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        text = message or ""
        lowered = text.lower()
        ctx = dict(context or {})
        selected: list[str] = []
        evidence: dict[str, list[str]] = {}

        for cap, hints in _HINTS.items():
            hits = [h for h in hints if h in lowered or h in text]
            if hits:
                selected.append(cap)
                evidence[cap] = hits[:5]

        # Contextual boosts
        if ctx.get("project_path") and "coding" not in selected:
            selected.append("coding")
            evidence.setdefault("coding", []).append("context:project_path")
        if ctx.get("target_id") and "security_analysis" not in selected:
            selected.append("security_analysis")
            evidence.setdefault("security_analysis", []).append("context:target_id")
        if ctx.get("code") and "coding" not in selected:
            selected.append("coding")

        # Multi-step phrases imply planning + evaluation
        if any(w in lowered for w in ("then", "and then", "after that", "finally", "also")):
            if "planning" not in selected:
                selected.append("planning")
            if "evaluation" not in selected:
                selected.append("evaluation")

        # Algorithm tasks always need reasoning artifacts
        if "algorithms" in selected and "reasoning" not in selected:
            selected.append("reasoning")

        # Coding+debug+test combo
        if "debugging" in selected and "testing" not in selected:
            selected.append("testing")

        # Default: reasoning for empty/simple questions
        if not selected:
            selected = ["reasoning"]
            evidence["reasoning"] = ["default"]

        # Always allow planning for multi-capability
        if len(selected) >= 2 and "planning" not in selected:
            selected.insert(0, "planning")

        # Stable order by CAPABILITIES declaration
        order = {c: i for i, c in enumerate(CAPABILITIES)}
        selected = sorted(set(selected), key=lambda c: order.get(c, 999))

        return {
            "ok": True,
            "capabilities": selected,
            "evidence": evidence,
            "multi_capability": len(selected) > 1,
            "version": self.VERSION,
        }

    def model_capability_hints(self, capabilities: list[str]) -> list[str]:
        """Map task capabilities to ModelRouter capability tags."""
        hints: list[str] = []
        if any(c in capabilities for c in ("coding", "debugging", "application_engineering", "algorithms")):
            hints.append("coding")
        if any(c in capabilities for c in ("debugging",)):
            hints.append("debugging")
        if any(c in capabilities for c in ("research", "web_operations")):
            hints.append("research")
        if any(c in capabilities for c in ("reasoning", "planning", "algorithms", "mathematics")):
            hints.append("reasoning")
        if "fast" not in hints and len(capabilities) <= 1 and capabilities == ["reasoning"]:
            hints.append("fast")
        return hints or ["reasoning"]
