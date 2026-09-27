"""PHASE 12 SkillDiscoveryEngine — transparent ranked skill selection."""
from __future__ import annotations

import re
from typing import Any

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.types import SkillCandidate


_INTENT_HINTS: dict[str, list[str]] = {
    "code": ["code", "function", "bug", "test", "refactor", "api", "debug", "implement"],
    "engineering": [
        "build me a website",
        "build a website",
        "full-stack",
        "web application",
        "create an application",
        "project structure",
        "architecture design",
        "inspect project",
        "repository inspection",
        "refactor",
    ],
    "security": [
        "security review",
        "vulnerability",
        "security weaknesses",
        "authorized test",
        "remediation",
        "security headers",
        "secure code",
        "check my application for security",
        "threat model",
        "secrets audit",
    ],
    "research": ["research", "source", "evidence", "cite", "fact", "paper", "compare sources"],
    "web": ["web search", "search the web", "fetch url", "http://", "https://", "browse", "online"],
    "data": ["dataset", "statistics", "mean", "plot", "experiment", "numeric"],
    "document": ["document", "summarize", "extract", "pdf", "rewrite", "outline"],
    "reason": ["why", "reason", "plan", "decide", "hypothesis", "analyze"],
    "tool": ["tool", "execute", "run command", "invoke"],
    "write": ["write", "brainstorm", "translate", "summarize"],
    "ai": ["model", "prompt", "rag", "embedding", "fine-tune", "routing"],
}


class SkillDiscoveryEngine:
    def __init__(self, registry: SkillRegistry2) -> None:
        self.registry = registry

    def infer_intents(self, task: str) -> list[str]:
        t = (task or "").lower()
        hits = []
        for intent, words in _INTENT_HINTS.items():
            if any(w in t for w in words):
                hits.append(intent)
        return hits or ["reason"]

    def discover(
        self,
        task: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 8,
        require_enabled: bool = True,
        allowed_permissions: set[str] | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        intents = self.infer_intents(task)
        category_map = {
            "code": "software_engineering",
            "engineering": "application_engineering",
            "security": "cyber_defense",
            "research": "research",
            "web": "web_information",
            "data": "data_science",
            "document": "document_intelligence",
            "reason": "reasoning",
            "tool": "agent_tool_use",
            "write": "creative_general",
            "ai": "ai_engineering",
        }
        wanted_categories = {category_map[i] for i in intents if i in category_map}
        tokens = set(re.findall(r"[a-zA-Z_]{3,}", (task or "").lower()))
        candidates: list[SkillCandidate] = []
        for skill in self.registry.list_skills(enabled_only=require_enabled):
            rationale: list[str] = []
            score = 0.0
            if require_enabled and not skill.enabled:
                continue
            if skill.status in ("disabled", "rolled_back"):
                continue
            if allowed_permissions and skill.permissions_required not in allowed_permissions:
                rationale.append("permission_filtered")
                continue
            if skill.category in wanted_categories:
                score += 3.0
                rationale.append(f"category_match:{skill.category}")
            caps = {c.lower() for c in skill.capabilities + skill.tags}
            overlap = tokens & caps
            if overlap:
                score += 1.5 * len(overlap)
                rationale.append(f"capability_overlap:{sorted(overlap)[:5]}")
            # name token overlap
            name_tokens = set(skill.skill_id.lower().split("_"))
            if tokens & name_tokens:
                score += 2.0
                rationale.append("name_token_match")
            if skill.evaluation_state in ("smoke_ok", "validated", "pass"):
                score += 0.5
                rationale.append("evaluation_healthy")
            if skill.health in ("healthy", "ok", "unknown"):
                score += 0.25
            # historical performance hook
            hist = float((ctx.get("skill_scores") or {}).get(skill.skill_id) or 0.0)
            if hist:
                score += hist
                rationale.append(f"historical_bonus:{hist}")
            # model/tool compatibility soft signals
            if ctx.get("model_provider") and ctx.get("model_provider") in skill.compatible_models:
                score += 0.5
                rationale.append("model_compatible")
            if score <= 0:
                continue
            candidates.append(
                SkillCandidate(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    version=skill.version,
                    score=round(score, 4),
                    rationale=rationale,
                    definition=skill.to_dict(),
                )
            )
        candidates.sort(key=lambda c: (-c.score, c.skill_id))
        top = candidates[: max(1, int(limit))]
        return {
            "ok": True,
            "task": task,
            "intents": intents,
            "wanted_categories": sorted(wanted_categories),
            "candidates": [c.to_dict() for c in top],
            "selection_policy": "transparent_scored_capability_match",
            "note": "No hard-coded single best skill; ranking is explanatory.",
        }
