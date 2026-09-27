"""Model Router contracts — roles over existing ModelProvider adapters."""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pfai.model import ModelProvider


class ModelRole(str, Enum):
    """Logical roles; config maps each role to a concrete provider.

    Local / openai_compatible / Echo / Mock are first-class.
    Anthropic is optional when ANTHROPIC_API_KEY is present — never required.
    """

    DEFAULT = "default"
    CODING = "coding"
    REASONING = "reasoning"
    FAST = "fast"
    VISION = "vision"
    EMBEDDING = "embedding"


@runtime_checkable
class ModelRouterProtocol(Protocol):
    """Resolve a ModelProvider for a role without forcing a vendor."""

    def resolve(self, role: ModelRole | str = ModelRole.DEFAULT) -> ModelProvider:
        """Return a provider for the role (may fall back to DEFAULT / Mock / Echo)."""
        ...

    def available_roles(self) -> list[str]:
        """Roles currently mapped to a usable provider."""
        ...

    def describe(self) -> dict[str, Any]:
        """Non-secret inventory of role → provider kind (no API keys)."""
        ...
