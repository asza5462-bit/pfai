"""PHASE 21 adaptive execution budgets — FAST/NORMAL/DEEP/AGENT/TRAINING; never bypass security."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from pfai.elite.execution_budgets import BudgetTracker, ExecutionBudgets


@dataclass
class AdaptiveBudgetProfile:
    name: str
    budgets: ExecutionBudgets
    reasoning_depth: int = 1
    parallelism: int = 1
    sandbox_seconds: float = 30.0
    prefer_lightweight_model: bool = False
    allow_model_escalation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "budgets": self.budgets.to_dict(),
            "reasoning_depth": self.reasoning_depth,
            "parallelism": self.parallelism,
            "sandbox_seconds": self.sandbox_seconds,
            "prefer_lightweight_model": self.prefer_lightweight_model,
            "allow_model_escalation": self.allow_model_escalation,
            "cannot_bypass_authorization": True,
            "cannot_bypass_security": True,
        }


PROFILES: dict[str, AdaptiveBudgetProfile] = {
    "FAST": AdaptiveBudgetProfile(
        name="FAST",
        budgets=ExecutionBudgets(
            max_task_steps=6,
            max_retries=1,
            max_tool_calls=4,
            max_model_calls=2,
            max_execution_time_seconds=15.0,
            max_nested_task_depth=1,
        ),
        reasoning_depth=1,
        parallelism=1,
        sandbox_seconds=10.0,
        prefer_lightweight_model=True,
        allow_model_escalation=False,
    ),
    "NORMAL": AdaptiveBudgetProfile(
        name="NORMAL",
        budgets=ExecutionBudgets(
            max_task_steps=16,
            max_retries=2,
            max_tool_calls=20,
            max_model_calls=8,
            max_execution_time_seconds=60.0,
            max_nested_task_depth=3,
        ),
        reasoning_depth=2,
        parallelism=2,
        sandbox_seconds=30.0,
        prefer_lightweight_model=False,
        allow_model_escalation=True,
    ),
    "DEEP": AdaptiveBudgetProfile(
        name="DEEP",
        budgets=ExecutionBudgets(
            max_task_steps=24,
            max_retries=3,
            max_tool_calls=40,
            max_model_calls=16,
            max_execution_time_seconds=120.0,
            max_nested_task_depth=4,
        ),
        reasoning_depth=4,
        parallelism=3,
        sandbox_seconds=60.0,
        prefer_lightweight_model=False,
        allow_model_escalation=True,
    ),
    "AGENT": AdaptiveBudgetProfile(
        name="AGENT",
        budgets=ExecutionBudgets(
            max_task_steps=32,
            max_retries=3,
            max_tool_calls=48,
            max_model_calls=20,
            max_execution_time_seconds=180.0,
            max_nested_task_depth=5,
        ),
        reasoning_depth=4,
        parallelism=4,
        sandbox_seconds=90.0,
        prefer_lightweight_model=False,
        allow_model_escalation=True,
    ),
    "TRAINING": AdaptiveBudgetProfile(
        name="TRAINING",
        budgets=ExecutionBudgets(
            max_task_steps=64,
            max_retries=2,
            max_tool_calls=20,
            max_model_calls=40,
            max_execution_time_seconds=600.0,
            max_nested_task_depth=2,
        ),
        reasoning_depth=2,
        parallelism=1,
        sandbox_seconds=120.0,
        prefer_lightweight_model=False,
        allow_model_escalation=False,
    ),
}


class AdaptiveBudgetSelector:
    VERSION = "21.0.0"

    def select(
        self,
        message: str,
        *,
        capabilities: list[str] | None = None,
        context: dict[str, Any] | None = None,
        forced_tier: str | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        caps = list(capabilities or [])
        if forced_tier and forced_tier.upper() in PROFILES:
            profile = PROFILES[forced_tier.upper()]
            return {"ok": True, "tier": profile.name, "profile": profile.to_dict(), "version": self.VERSION}

        t = (message or "").lower()
        if ctx.get("training") or "train model" in t or "autonomous training" in t:
            profile = PROFILES["TRAINING"]
        elif (
            len(caps) >= 4
            or any(w in t for w in ("multi-step", "and then", "finally", "fix it", "run the tests"))
            or ctx.get("force_agent_engine")
        ):
            profile = PROFILES["AGENT"]
        elif any(
            c in caps
            for c in ("algorithms", "architecture", "debugging", "research", "security_analysis")
        ) or any(w in t for w in ("complex", "architecture", "algorithm", "debug", "research")):
            profile = PROFILES["DEEP"]
        elif len(caps) <= 1 and len(t.split()) <= 12 and not caps.intersection(
            {"coding", "debugging", "algorithms", "tool_execution"}
        ) if isinstance(caps, set) else (
            len(caps) <= 1
            and len(t.split()) <= 12
            and not any(c in caps for c in ("coding", "debugging", "algorithms", "tool_execution"))
        ):
            profile = PROFILES["FAST"]
        else:
            # Simple questions / small transforms
            if len(t.split()) <= 8 and not any(
                c in caps for c in ("coding", "debugging", "algorithms", "tool_execution", "mcp")
            ):
                profile = PROFILES["FAST"]
            else:
                profile = PROFILES["NORMAL"]

        # Optional overrides from config (never security bypass)
        overrides = dict(ctx.get("budget_overrides") or {})
        budgets = profile.budgets
        if overrides:
            budgets = replace(
                budgets,
                **{k: overrides[k] for k in overrides if hasattr(budgets, k)},
            )
            profile = AdaptiveBudgetProfile(
                name=profile.name,
                budgets=budgets,
                reasoning_depth=profile.reasoning_depth,
                parallelism=profile.parallelism,
                sandbox_seconds=profile.sandbox_seconds,
                prefer_lightweight_model=profile.prefer_lightweight_model,
                allow_model_escalation=profile.allow_model_escalation,
            )

        return {
            "ok": True,
            "tier": profile.name,
            "profile": profile.to_dict(),
            "budgets": budgets,
            "tracker": None,
            "version": self.VERSION,
            "cannot_bypass_authorization": True,
        }

    def tracker_for(self, selection: dict[str, Any]) -> BudgetTracker:
        budgets = selection.get("budgets")
        if not isinstance(budgets, ExecutionBudgets):
            tier = selection.get("tier") or "NORMAL"
            budgets = PROFILES.get(tier, PROFILES["NORMAL"]).budgets
        return BudgetTracker(budgets)
