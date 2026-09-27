"""Model Router scaffold (PHASE 1). Implementation in PHASE 2.

Existing providers (Echo, Anthropic optional, openai_compatible, Mock) stay as-is.
This layer only assigns logical ModelRole → provider; Anthropic is never required.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.model import ModelRole, ModelRouterProtocol
from pfai.model import ModelProvider

__all__ = ["ModelRole", "ModelRouterProtocol", "ModelRouter"]

PHASE = 2


class ModelRouter:
    """Placeholder registry map; not wired into runtime in PHASE 1."""

    def __init__(self, providers: dict[str, ModelProvider] | None = None) -> None:
        self._providers = {str(k): v for k, v in (providers or {}).items()}

    def resolve(self, role: ModelRole | str = ModelRole.DEFAULT) -> ModelProvider:
        key = role.value if isinstance(role, ModelRole) else str(role)
        if key in self._providers:
            return self._providers[key]
        if ModelRole.DEFAULT.value in self._providers:
            return self._providers[ModelRole.DEFAULT.value]
        raise NotImplementedError(
            "ModelRouter has no providers yet — wire in PHASE 2 (Local/Mock first; Anthropic optional)"
        )

    def available_roles(self) -> list[str]:
        return sorted(self._providers.keys())

    def describe(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "roles": {
                name: type(provider).__name__ for name, provider in self._providers.items()
            },
            "anthropic_required": False,
        }
