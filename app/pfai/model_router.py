"""ModelRouter — role → ModelProvider using ProviderRegistry (PHASE 2).

Anthropic is never required. Missing/unusable roles fall back to DEFAULT,
then Echo/Mock.
"""
from __future__ import annotations

from typing import Any

from pfai.interfaces.model import ModelRole, ModelRouterProtocol
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.model import EchoProvider, ModelProvider
from pfai.model_mock import MockCommandProvider

__all__ = ["ModelRole", "ModelRouterProtocol", "ModelRouter"]

PHASE = 2


class ModelRouter:
    def __init__(
        self,
        providers: dict[str, ModelProvider] | None = None,
        *,
        registry: ProviderRegistry | None = None,
        role_map: dict[str, str] | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.registry.bootstrap_defaults()
        self._providers = {str(k): v for k, v in (providers or {}).items()}
        # role -> provider_id in registry (used when instance not pre-bound)
        self._role_map = {str(k): str(v) for k, v in (role_map or {}).items()}
        if ModelRole.DEFAULT.value not in self._providers:
            # Prefer mock for chat-like roles when nothing bound — offline-safe.
            self._providers[ModelRole.DEFAULT.value] = EchoProvider()

    @classmethod
    def from_config(
        cls,
        model_cfg: dict[str, Any] | None = None,
        *,
        roles: dict[str, Any] | None = None,
        registry: ProviderRegistry | None = None,
    ) -> "ModelRouter":
        reg = registry or ProviderRegistry()
        reg.bootstrap_defaults()
        default = reg.create_from_config(model_cfg)
        providers: dict[str, ModelProvider] = {ModelRole.DEFAULT.value: default}
        role_map: dict[str, str] = {ModelRole.DEFAULT.value: str((model_cfg or {}).get("provider") or "echo")}

        # Optional per-role overrides: {"coding": {"provider": "mock"}, ...}
        for role_name, cfg in (roles or {}).items():
            if isinstance(cfg, str):
                pid = cfg
                providers[role_name] = reg.create(pid) if pid in {p.provider_id for p in reg.list_providers()} else default
                role_map[role_name] = pid
            elif isinstance(cfg, dict):
                providers[role_name] = reg.create_from_config(cfg)
                role_map[role_name] = str(cfg.get("provider") or role_map[ModelRole.DEFAULT.value])
            elif isinstance(cfg, ModelProvider):
                providers[role_name] = cfg
                role_map[role_name] = type(cfg).__name__

        # Sensible offline defaults for specialized roles when unset
        if ModelRole.CODING.value not in providers:
            providers[ModelRole.CODING.value] = MockCommandProvider()
            role_map[ModelRole.CODING.value] = "mock"
        if ModelRole.FAST.value not in providers:
            providers[ModelRole.FAST.value] = EchoProvider()
            role_map[ModelRole.FAST.value] = "echo"
        if ModelRole.REASONING.value not in providers:
            providers[ModelRole.REASONING.value] = default
            role_map[ModelRole.REASONING.value] = role_map[ModelRole.DEFAULT.value]

        return cls(providers, registry=reg, role_map=role_map)

    def bind(self, role: ModelRole | str, provider: ModelProvider) -> None:
        key = role.value if isinstance(role, ModelRole) else str(role)
        self._providers[key] = provider

    def resolve(self, role: ModelRole | str = ModelRole.DEFAULT) -> ModelProvider:
        key = role.value if isinstance(role, ModelRole) else str(role)
        if key in self._providers:
            return self._providers[key]
        if ModelRole.DEFAULT.value in self._providers:
            return self._providers[ModelRole.DEFAULT.value]
        return EchoProvider()

    def available_roles(self) -> list[str]:
        return sorted(self._providers.keys())

    def describe(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "roles": {name: type(provider).__name__ for name, provider in self._providers.items()},
            "role_map": dict(self._role_map),
            "registry_providers": [p.provider_id for p in self.registry.list_providers()],
            "anthropic_required": False,
            "offline_capable_defaults": True,
        }
