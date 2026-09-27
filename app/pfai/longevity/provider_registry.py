"""In-memory ProviderRegistry scaffold — register Echo/Mock/local first."""
from __future__ import annotations

from typing import Any, Callable

from pfai.interfaces.model import ProviderSpec
from pfai.model import ModelProvider


Factory = Callable[..., ModelProvider]


class ProviderRegistry:
    """Provider catalog. Not wired into app.py yet — Core stays vendor-agnostic."""

    def __init__(self) -> None:
        self._specs: dict[str, ProviderSpec] = {}
        self._factories: dict[str, Factory] = {}

    def register(self, spec: ProviderSpec, factory: Factory) -> None:
        if not spec.provider_id:
            raise ValueError("provider_id required")
        self._specs[spec.provider_id] = spec
        self._factories[spec.provider_id] = factory

    def get(self, provider_id: str) -> ProviderSpec | None:
        return self._specs.get(provider_id)

    def list_providers(self) -> list[ProviderSpec]:
        return list(self._specs.values())

    def create(self, provider_id: str, **kwargs: Any) -> ModelProvider:
        factory = self._factories.get(provider_id)
        if not factory:
            raise KeyError(f"unknown provider: {provider_id}")
        return factory(**kwargs)

    def bootstrap_defaults(self) -> None:
        """Register offline-capable defaults (no commercial vendor required)."""
        from pfai.model import EchoProvider
        from pfai.model_mock import MockCommandProvider

        if "echo" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="echo",
                    kind="echo",
                    description="Deterministic offline Echo provider",
                    offline_capable=True,
                    requires_api_key=False,
                ),
                lambda **_: EchoProvider(),
            )
        if "mock" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="mock",
                    kind="mock",
                    description="Mock command/planning provider for offline tests",
                    offline_capable=True,
                    requires_api_key=False,
                ),
                lambda **_: MockCommandProvider(),
            )
