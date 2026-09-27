"""Model / Provider Registry contracts — fully swappable, vendor-agnostic Core.

Anthropic, OpenAI-compatible, Echo, Mock, and future providers register here.
Core PFAI must run with local/Echo/Mock alone — no commercial vendor required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pfai.model import ModelProvider


class ModelRole(str, Enum):
    """Logical roles; config maps each role to a concrete provider."""

    DEFAULT = "default"
    CODING = "coding"
    REASONING = "reasoning"
    FAST = "fast"
    VISION = "vision"
    EMBEDDING = "embedding"


# Capability classes used by ModelRouter (Phase 13). Only claim what is implemented.
MODEL_CAPABILITIES = (
    "reasoning",
    "coding",
    "debugging",
    "research",
    "long_context",
    "structured_output",
    "tool_use",
    "vision",
    "embeddings",
    "local",
    "remote",
    "fast",
    "echo",
    "mock",
)


@dataclass
class ProviderSpec:
    """Registration metadata for a model provider implementation."""

    provider_id: str
    kind: str  # echo | mock | openai_compatible | anthropic | local | custom
    description: str = ""
    offline_capable: bool = False
    requires_api_key: bool = False
    api_key_env: str = ""
    default_model: str = ""
    capabilities: tuple[str, ...] = ()
    context_length: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnavailableResult:
    """Structured result when a provider/role cannot be used (never pretend success)."""

    ok: bool = False
    available: bool = False
    error: str = "provider_unavailable"
    provider_id: str = ""
    role: str = ""
    capabilities_requested: tuple[str, ...] = ()
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "available": self.available,
            "error": self.error,
            "provider_id": self.provider_id,
            "role": self.role,
            "capabilities_requested": list(self.capabilities_requested),
            "audit": dict(self.audit),
        }


@dataclass
class ModelRegistration:
    model_id: str
    provider_id: str
    display_name: str = ""
    roles: tuple[str, ...] = ()
    status: str = "candidate"  # candidate | active | archived
    score: float | None = None
    artifact: str = ""
    created_at: str = ""
    parent: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ModelRouterProtocol(Protocol):
    """Resolve a ModelProvider for a role without forcing a vendor."""

    def resolve(self, role: ModelRole | str = ModelRole.DEFAULT) -> ModelProvider:
        ...

    def available_roles(self) -> list[str]:
        ...

    def describe(self) -> dict[str, Any]:
        ...


@runtime_checkable
class ProviderRegistryProtocol(Protocol):
    def register(self, spec: ProviderSpec, factory: Any) -> None:
        ...

    def get(self, provider_id: str) -> ProviderSpec | None:
        ...

    def list_providers(self) -> list[ProviderSpec]:
        ...

    def create(self, provider_id: str, **kwargs: Any) -> ModelProvider:
        ...


@runtime_checkable
class ModelRegistryProtocol(Protocol):
    """Extends today's ModelRegistry JSON file with a stable port."""

    def register(self, entry: ModelRegistration) -> ModelRegistration:
        ...

    def promote(self, model_id: str, *, approved: bool = False) -> bool:
        ...

    def rollback(self, model_id: str, *, approved: bool = False) -> bool:
        ...

    def active(self) -> ModelRegistration | None:
        ...

    def history(self) -> list[ModelRegistration]:
        ...
