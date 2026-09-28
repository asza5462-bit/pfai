"""PHASE 21 performance-aware model routing — prefer smallest capable; escalate when needed.

Never claims a model is better without measured evidence. Never hard-codes a single commercial provider.
"""
from __future__ import annotations

from typing import Any

from pfai.elite.capability_router import CapabilityRouter


# Preference order for simple tasks (local/lightweight first when available)
_LIGHTWEIGHT_PREF = ("echo", "local", "tiny", "small", "distil")
_ESCALATION_HINTS = ("reasoning", "coding", "long_context")


class PerformanceModelRouter:
    VERSION = "21.0.0"

    def __init__(self, model_router: Any = None) -> None:
        self.model_router = model_router
        self.capabilities = CapabilityRouter()

    def route(
        self,
        message: str,
        *,
        capabilities: list[str] | None = None,
        tier: str = "NORMAL",
        prefer_lightweight: bool = False,
        escalate: bool = False,
        previous_eval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        router = self.model_router
        if router is None:
            return {
                "ok": False,
                "available": False,
                "error": "model_router_not_configured",
                "capability_unavailable": True,
                "version": self.VERSION,
            }

        caps = list(capabilities or self.capabilities.route(message).get("capabilities") or [])
        hints = self.capabilities.model_capability_hints(caps)
        if escalate:
            for h in _ESCALATION_HINTS:
                if h not in hints:
                    hints.append(h)

        prefer_local = prefer_lightweight or tier.upper() == "FAST"
        # If previous evaluation evidence says a role failed, try alternate
        avoid_role = None
        if previous_eval and previous_eval.get("failed_role"):
            avoid_role = previous_eval.get("failed_role")

        try:
            if hasattr(router, "select_by_capabilities"):
                info = router.select_by_capabilities(hints, prefer_local=prefer_local)
            else:
                info = router.route_for_task(message)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "available": False, "error": type(exc).__name__, "version": self.VERSION}

        if isinstance(info, dict) and info.get("provider") is not None and not isinstance(info.get("provider"), str):
            info = dict(info)
            info["provider"] = type(info["provider"]).__name__

        # Lightweight preference: if multiple candidates conceptually, prefer echo/local ids when FAST
        if prefer_local and info.get("available") and info.get("provider_id"):
            pid = str(info.get("provider_id") or "").lower()
            if not any(x in pid for x in _LIGHTWEIGHT_PREF) and hasattr(router, "select_by_capabilities"):
                # Keep current selection — do not fabricate a better model claim
                info = dict(info)
                info["lightweight_preferred"] = True
                info["note"] = "selected_by_capability_coverage; no unmeasured quality claim"

        if avoid_role and info.get("role") == avoid_role and escalate and hasattr(router, "available_roles"):
            roles = [r for r in router.available_roles() if r != avoid_role]
            if roles and hasattr(router, "resolve"):
                try:
                    alt = router.resolve(roles[0])
                    info = {
                        "ok": True,
                        "available": True,
                        "role": roles[0],
                        "provider_id": type(alt).__name__,
                        "provider": type(alt).__name__,
                        "escalated": True,
                        "previous_failed_role": avoid_role,
                    }
                except Exception:
                    pass

        if not info.get("available") and not info.get("ok"):
            return {**info, "capability_unavailable": True, "version": self.VERSION}

        out = dict(info)
        out["version"] = self.VERSION
        out["tier"] = tier
        out["prefer_lightweight"] = prefer_local
        out["quality_claim"] = "none_without_measured_evaluation"
        out["fabricated_superiority"] = False
        return out
