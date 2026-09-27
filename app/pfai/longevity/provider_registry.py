"""ProviderRegistry — replaceable model provider catalog (PHASE 2).

Core registers Echo/Mock first. openai_compatible (local) and Anthropic are
optional adapters — never required to construct or run the registry.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from pfai.interfaces.model import ProviderSpec
from pfai.model import EchoProvider, ModelProvider
from pfai.model_mock import MockCommandProvider

Factory = Callable[..., ModelProvider]


class ProviderRegistry:
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
        """Register offline-capable + optional network providers."""
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
        if "openai_compatible" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="openai_compatible",
                    kind="openai_compatible",
                    description="Local/OpenAI-compatible HTTP endpoint (Ollama/vLLM/etc.)",
                    offline_capable=True,
                    requires_api_key=False,
                ),
                _make_openai_compatible,
            )
        if "local" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="local",
                    kind="local",
                    description="Local OpenAI-compatible runtime adapter (Ollama/vLLM/llama.cpp)",
                    offline_capable=True,
                    requires_api_key=False,
                ),
                lambda **kw: _make_local("local", **kw),
            )
        if "open_weight" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="open_weight",
                    kind="open_weight",
                    description="Open-weight model adapter via OpenAI-compatible HTTP endpoint",
                    offline_capable=True,
                    requires_api_key=False,
                ),
                lambda **kw: _make_local("open_weight", **kw),
            )
        if "anthropic" not in self._specs:
            self.register(
                ProviderSpec(
                    provider_id="anthropic",
                    kind="anthropic",
                    description="Optional Anthropic Messages API adapter",
                    offline_capable=False,
                    requires_api_key=True,
                    api_key_env="ANTHROPIC_API_KEY",
                ),
                _make_anthropic,
            )

    def create_from_config(self, model_cfg: dict[str, Any] | None = None) -> ModelProvider:
        """Build a provider from config without requiring a commercial vendor.

        If the configured provider needs a missing API key, fall back to Echo.
        """
        cfg = dict(model_cfg or {})
        provider_id = str(cfg.get("provider") or "echo").strip() or "echo"
        if provider_id not in self._factories:
            self.bootstrap_defaults()
        if provider_id not in self._factories:
            return EchoProvider()

        spec = self._specs.get(provider_id)
        if spec and spec.requires_api_key:
            env_name = spec.api_key_env or cfg.get("api_key_env") or ""
            if env_name and not os.environ.get(env_name):
                # Core must run offline — do not fail construction.
                return self.create("echo")

        try:
            return self.create(provider_id, **_factory_kwargs(provider_id, cfg))
        except Exception:
            return self.create("echo")


def _factory_kwargs(provider_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    if provider_id in ("openai_compatible", "local", "open_weight"):
        import os as _os

        from pfai.model_local import model_settings_from_env

        settings = model_settings_from_env(cfg)
        key_env = cfg.get("api_key_env") or settings.get("api_key_env")
        api_key = settings.get("api_key") or ""
        if key_env and not api_key:
            api_key = _os.environ.get(str(key_env), "")
        return {
            "base_url": cfg.get("base_url") or settings["base_url"],
            "model": cfg.get("model") or settings["model"],
            "api_key": api_key,
            "timeout": cfg.get("timeout", settings["timeout"]),
            "max_tokens": cfg.get("max_tokens", settings["max_tokens"]),
            "temperature": cfg.get("temperature", settings["temperature"]),
            "context_length": cfg.get("context_length", settings["context_length"]),
            "probe_on_init": cfg.get("probe_on_init", True),
        }
    if provider_id == "anthropic":
        return {
            "model": cfg.get("model", "claude-opus-5"),
            "base_url": cfg.get("base_url", "https://api.anthropic.com/v1"),
            "max_tokens": int(cfg.get("max_tokens", 2048)),
            "api_key_env": cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
        }
    return {}


def _make_openai_compatible(**kwargs: Any) -> ModelProvider:
    from pfai.model_http import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        kwargs.get("base_url", "http://127.0.0.1:11434/v1"),
        kwargs.get("model", "local"),
        kwargs.get("api_key", ""),
    )


def _make_local(provider_id: str, **kwargs: Any) -> ModelProvider:
    from pfai.model_local import build_local_or_open_weight

    return build_local_or_open_weight(provider_id, **kwargs)


def _make_anthropic(**kwargs: Any) -> ModelProvider:
    from pfai.model_anthropic import AnthropicProvider

    return AnthropicProvider(
        model=kwargs.get("model", "claude-opus-5"),
        base_url=kwargs.get("base_url", "https://api.anthropic.com/v1"),
        max_tokens=int(kwargs.get("max_tokens", 2048)),
        api_key_env=kwargs.get("api_key_env", "ANTHROPIC_API_KEY"),
    )
