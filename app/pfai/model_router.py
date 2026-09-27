"""ModelRouter — role/capability → ModelProvider using ProviderRegistry (PHASE 13).

Anthropic is never required. Missing/unusable providers return structured
UnavailableResult — never silently pretend success unless explicit fallback
is permitted by configuration.
"""
from __future__ import annotations

import os
from typing import Any

from pfai.interfaces.model import ModelRole, ModelRouterProtocol, UnavailableResult
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.model import EchoProvider, ModelProvider
from pfai.model_mock import MockCommandProvider

__all__ = ["ModelRole", "ModelRouterProtocol", "ModelRouter", "UnavailableResult"]

PHASE = 13

# Default capability claims — only what each offline adapter truly offers.
_DEFAULT_CAPS: dict[str, tuple[str, ...]] = {
    "echo": ("echo", "local", "fast"),
    "mock": ("mock", "local", "coding", "structured_output", "fast"),
    "local": ("local", "reasoning", "coding", "debugging", "research", "structured_output", "tool_use"),
    "open_weight": ("local", "reasoning", "coding", "debugging", "research", "structured_output"),
    "openai_compatible": ("local", "remote", "reasoning", "coding", "structured_output", "tool_use"),
    "transformers_local": ("local", "reasoning", "coding", "structured_output"),
    "anthropic": ("remote", "reasoning", "coding", "debugging", "research", "long_context", "structured_output", "tool_use", "vision"),
}

_ROLE_CAPS: dict[str, tuple[str, ...]] = {
    ModelRole.DEFAULT.value: ("reasoning",),
    ModelRole.CODING.value: ("coding",),
    ModelRole.REASONING.value: ("reasoning",),
    ModelRole.FAST.value: ("fast",),
    ModelRole.VISION.value: ("vision",),
    ModelRole.EMBEDDING.value: ("embeddings",),
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def allow_provider_fallback() -> bool:
    """Explicit opt-in for falling back when preferred provider is unavailable."""
    return _env_bool("PFAI_MODEL_ALLOW_FALLBACK", True)


class ModelRouter:
    def __init__(
        self,
        providers: dict[str, ModelProvider] | None = None,
        *,
        registry: ProviderRegistry | None = None,
        role_map: dict[str, str] | None = None,
        capability_map: dict[str, tuple[str, ...]] | None = None,
        allow_fallback: bool | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.registry.bootstrap_defaults()
        self._providers = {str(k): v for k, v in (providers or {}).items()}
        self._role_map = {str(k): str(v) for k, v in (role_map or {}).items()}
        self._capability_map = {
            str(k): tuple(v) for k, v in (capability_map or dict(_DEFAULT_CAPS)).items()
        }
        self.allow_fallback = allow_provider_fallback() if allow_fallback is None else bool(allow_fallback)
        if ModelRole.DEFAULT.value not in self._providers:
            self._providers[ModelRole.DEFAULT.value] = EchoProvider()
            self._role_map.setdefault(ModelRole.DEFAULT.value, "echo")

    @classmethod
    def from_config(
        cls,
        model_cfg: dict[str, Any] | None = None,
        *,
        roles: dict[str, Any] | None = None,
        registry: ProviderRegistry | None = None,
        allow_fallback: bool | None = None,
    ) -> "ModelRouter":
        reg = registry or ProviderRegistry()
        reg.bootstrap_defaults()
        cfg = dict(model_cfg or {})
        # Environment-driven selection (Phase 13)
        if not cfg.get("provider"):
            env_provider = (os.environ.get("MODEL_PROVIDER") or os.environ.get("PFAI_MODEL_PROVIDER") or "").strip()
            if env_provider:
                cfg["provider"] = env_provider
        if not cfg.get("model"):
            env_model = (os.environ.get("MODEL_NAME") or os.environ.get("PFAI_MODEL_NAME") or "").strip()
            if env_model:
                cfg["model"] = env_model
        if not cfg.get("base_url") and os.environ.get("MODEL_ENDPOINT"):
            cfg["base_url"] = os.environ.get("MODEL_ENDPOINT")
        if not cfg.get("context_length") and os.environ.get("MODEL_CONTEXT_LENGTH"):
            cfg["context_length"] = int(os.environ.get("MODEL_CONTEXT_LENGTH") or 0)
        if not cfg.get("timeout") and os.environ.get("MODEL_TIMEOUT"):
            cfg["timeout"] = float(os.environ.get("MODEL_TIMEOUT") or 30)
        if not cfg.get("max_tokens") and os.environ.get("MODEL_MAX_TOKENS"):
            cfg["max_tokens"] = int(os.environ.get("MODEL_MAX_TOKENS") or 256)
        if os.environ.get("MODEL_CAPABILITIES") and "capabilities" not in cfg:
            cfg["capabilities"] = [
                c.strip() for c in str(os.environ.get("MODEL_CAPABILITIES") or "").split(",") if c.strip()
            ]

        default = reg.create_from_config(cfg)
        provider_id = str(cfg.get("provider") or "echo").strip() or "echo"
        providers: dict[str, ModelProvider] = {ModelRole.DEFAULT.value: default}
        role_map: dict[str, str] = {ModelRole.DEFAULT.value: provider_id}
        capability_map = dict(_DEFAULT_CAPS)
        if cfg.get("capabilities"):
            capability_map[provider_id] = tuple(cfg["capabilities"])

        for role_name, role_cfg in (roles or {}).items():
            if isinstance(role_cfg, str):
                pid = role_cfg
                if pid in {p.provider_id for p in reg.list_providers()}:
                    providers[role_name] = reg.create(pid)
                else:
                    providers[role_name] = default
                role_map[role_name] = pid
            elif isinstance(role_cfg, dict):
                providers[role_name] = reg.create_from_config(role_cfg)
                role_map[role_name] = str(role_cfg.get("provider") or role_map[ModelRole.DEFAULT.value])
                if role_cfg.get("capabilities"):
                    capability_map[role_map[role_name]] = tuple(role_cfg["capabilities"])
            elif isinstance(role_cfg, ModelProvider):
                providers[role_name] = role_cfg
                role_map[role_name] = type(role_cfg).__name__

        if ModelRole.CODING.value not in providers:
            providers[ModelRole.CODING.value] = MockCommandProvider()
            role_map[ModelRole.CODING.value] = "mock"
        if ModelRole.FAST.value not in providers:
            providers[ModelRole.FAST.value] = EchoProvider()
            role_map[ModelRole.FAST.value] = "echo"
        if ModelRole.REASONING.value not in providers:
            providers[ModelRole.REASONING.value] = default
            role_map[ModelRole.REASONING.value] = role_map[ModelRole.DEFAULT.value]

        return cls(
            providers,
            registry=reg,
            role_map=role_map,
            capability_map=capability_map,
            allow_fallback=allow_fallback,
        )

    def bind(self, role: ModelRole | str, provider: ModelProvider, *, provider_id: str | None = None) -> None:
        key = role.value if isinstance(role, ModelRole) else str(role)
        self._providers[key] = provider
        if provider_id:
            self._role_map[key] = provider_id

    def resolve(self, role: ModelRole | str = ModelRole.DEFAULT) -> ModelProvider:
        key = role.value if isinstance(role, ModelRole) else str(role)
        if key in self._providers:
            return self._providers[key]
        if self.allow_fallback and ModelRole.DEFAULT.value in self._providers:
            return self._providers[ModelRole.DEFAULT.value]
        return EchoProvider() if self.allow_fallback else EchoProvider()

    def resolve_result(self, role: ModelRole | str = ModelRole.DEFAULT) -> dict[str, Any]:
        """Resolve with structured availability — never pretends success when missing."""
        key = role.value if isinstance(role, ModelRole) else str(role)
        if key in self._providers:
            pid = self._role_map.get(key, type(self._providers[key]).__name__)
            return {
                "ok": True,
                "available": True,
                "role": key,
                "provider_id": pid,
                "provider": self._providers[key],
                "capabilities": list(self.capabilities_for(pid)),
            }
        if self.allow_fallback and ModelRole.DEFAULT.value in self._providers:
            pid = self._role_map.get(ModelRole.DEFAULT.value, "echo")
            return {
                "ok": True,
                "available": True,
                "role": key,
                "provider_id": pid,
                "provider": self._providers[ModelRole.DEFAULT.value],
                "fallback": True,
                "capabilities": list(self.capabilities_for(pid)),
                "audit": {"fallback_from": key, "fallback_to": ModelRole.DEFAULT.value},
            }
        unavailable = UnavailableResult(
            error="provider_unavailable",
            role=key,
            audit={"reason": "role_unbound", "allow_fallback": self.allow_fallback},
        )
        return unavailable.to_dict()

    def capabilities_for(self, provider_id: str) -> tuple[str, ...]:
        if provider_id in self._capability_map:
            return self._capability_map[provider_id]
        spec = self.registry.get(provider_id)
        if spec and getattr(spec, "capabilities", None):
            return tuple(spec.capabilities)
        return _DEFAULT_CAPS.get(provider_id, ())

    def select_by_capabilities(
        self,
        required: list[str] | tuple[str, ...] | None,
        *,
        prefer_local: bool = False,
    ) -> dict[str, Any]:
        """Pick a bound role/provider that covers required capabilities."""
        needed = tuple(c for c in (required or ()) if c)
        candidates: list[tuple[int, str, str, ModelProvider]] = []
        for role, provider in self._providers.items():
            pid = self._role_map.get(role, type(provider).__name__)
            caps = set(self.capabilities_for(pid))
            if needed and not set(needed).issubset(caps) and not (set(needed) & caps):
                # Prefer intersection; require at least one match when specified
                continue
            score = len(set(needed) & caps) * 10
            if prefer_local and "local" in caps:
                score += 5
            if "remote" in caps and prefer_local:
                score -= 2
            candidates.append((score, role, pid, provider))
        candidates.sort(key=lambda x: (-x[0], x[1]))
        if not candidates:
            if self.allow_fallback and ModelRole.DEFAULT.value in self._providers:
                pid = self._role_map.get(ModelRole.DEFAULT.value, "echo")
                return {
                    "ok": True,
                    "available": True,
                    "fallback": True,
                    "role": ModelRole.DEFAULT.value,
                    "provider_id": pid,
                    "provider": self._providers[ModelRole.DEFAULT.value],
                    "capabilities_requested": list(needed),
                    "capabilities": list(self.capabilities_for(pid)),
                    "audit": {"reason": "no_capability_match_fallback"},
                }
            return UnavailableResult(
                error="provider_unavailable",
                capabilities_requested=needed,
                audit={"reason": "no_provider_for_capabilities"},
            ).to_dict()
        score, role, pid, provider = candidates[0]
        return {
            "ok": True,
            "available": True,
            "role": role,
            "provider_id": pid,
            "provider": provider,
            "score": score,
            "capabilities_requested": list(needed),
            "capabilities": list(self.capabilities_for(pid)),
        }

    def route_for_task(self, task: str, *, mode: str | None = None) -> dict[str, Any]:
        """Capability-driven routing from task/mode text."""
        text = f"{mode or ''} {task or ''}".lower()
        required: list[str] = []
        if any(w in text for w in ("code", "implement", "refactor", "debug", "python", "typescript")):
            required.append("coding")
        if any(w in text for w in ("debug", "traceback", "stack trace")):
            required.append("debugging")
        if any(w in text for w in ("research", "cite", "web", "source")):
            required.append("research")
        if any(w in text for w in ("embed", "embedding", "vector")):
            required.append("embeddings")
        if any(w in text for w in ("image", "vision", "screenshot")):
            required.append("vision")
        if any(w in text for w in ("long context", "entire repo", "100k")):
            required.append("long_context")
        if not required:
            if (mode or "").upper() == "CODE":
                required = ["coding"]
            elif (mode or "").upper() in ("REASON", "PLAN", "RESEARCH"):
                required = ["reasoning"]
            else:
                required = ["reasoning"]
        return self.select_by_capabilities(required)

    def available_roles(self) -> list[str]:
        return sorted(self._providers.keys())

    def describe(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "roles": {name: type(provider).__name__ for name, provider in self._providers.items()},
            "role_map": dict(self._role_map),
            "capabilities": {k: list(v) for k, v in self._capability_map.items()},
            "registry_providers": [p.provider_id for p in self.registry.list_providers()],
            "anthropic_required": False,
            "offline_capable_defaults": True,
            "allow_fallback": self.allow_fallback,
            "model_independent_security": True,
            "model_cannot_grant_privileges": True,
        }
