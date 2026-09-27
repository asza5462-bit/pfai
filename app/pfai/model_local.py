"""Local / open-weight model adapters (PHASE 5).

Talks to OpenAI-compatible HTTP runtimes (Ollama, vLLM, llama.cpp server, etc.).
Does not claim a runtime is connected unless a readiness probe succeeds.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .model import ModelProvider
from .model_http import OpenAICompatibleProvider


def model_settings_from_env(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve replaceable model settings from environment + optional overrides."""
    cfg = dict(overrides or {})
    provider = (
        cfg.get("provider")
        or os.environ.get("MODEL_PROVIDER")
        or os.environ.get("PFAI_MODEL_PROVIDER")
        or "echo"
    )
    return {
        "provider": str(provider).strip() or "echo",
        "model": cfg.get("model")
        or os.environ.get("MODEL_NAME")
        or os.environ.get("PFAI_MODEL_NAME")
        or cfg.get("name")
        or "local",
        "base_url": cfg.get("base_url")
        or os.environ.get("MODEL_ENDPOINT")
        or os.environ.get("PFAI_MODEL_ENDPOINT")
        or "http://127.0.0.1:11434/v1",
        "context_length": int(
            cfg.get("context_length")
            or os.environ.get("MODEL_CONTEXT_LENGTH")
            or os.environ.get("PFAI_MODEL_CONTEXT_LENGTH")
            or 8192
        ),
        "timeout": float(
            cfg.get("timeout")
            or os.environ.get("MODEL_TIMEOUT")
            or os.environ.get("PFAI_MODEL_TIMEOUT")
            or 60
        ),
        "max_tokens": int(
            cfg.get("max_tokens")
            or os.environ.get("MODEL_MAX_TOKENS")
            or os.environ.get("PFAI_MODEL_MAX_TOKENS")
            or 2048
        ),
        "temperature": float(
            cfg.get("temperature")
            or os.environ.get("MODEL_TEMPERATURE")
            or os.environ.get("PFAI_MODEL_TEMPERATURE")
            or 0.2
        ),
        "api_key": cfg.get("api_key")
        or os.environ.get("MODEL_API_KEY")
        or os.environ.get("PFAI_MODEL_API_KEY")
        or "",
        "api_key_env": cfg.get("api_key_env") or "",
    }


class LocalModelProvider(ModelProvider):
    """Real adapter for a local OpenAI-compatible inference server."""

    kind = "local"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "local",
        api_key: str = "",
        timeout: float = 60.0,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        context_length: int = 8192,
        probe_on_init: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.context_length = int(context_length)
        self._delegate = OpenAICompatibleProvider(self.base_url, self.model, self.api_key)
        self._last_probe: dict[str, Any] = {"connected": False, "checked": False}
        if probe_on_init:
            self.probe()

    def probe(self) -> dict[str, Any]:
        """Honest readiness check — never fakes a live runtime."""
        result: dict[str, Any] = {
            "ok": False,
            "connected": False,
            "adapter": self.__class__.__name__,
            "kind": self.kind,
            "model": self.model,
            "endpoint_configured": bool(self.base_url),
            "status": "Adapter implemented, runtime not connected.",
            "checked": True,
        }
        if not self.base_url:
            self._last_probe = result
            return result
        try:
            url = f"{self.base_url}/models"
            req = urllib.request.Request(url, method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urllib.request.urlopen(req, timeout=min(5.0, self.timeout)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw) if raw else {}
            models = data.get("data") if isinstance(data, dict) else None
            result["ok"] = True
            result["connected"] = True
            result["status"] = "connected"
            result["models_listed"] = len(models) if isinstance(models, list) else None
        except Exception as exc:
            result["ok"] = False
            result["connected"] = False
            result["error"] = type(exc).__name__
            result["status"] = "Adapter implemented, runtime not connected."
        self._last_probe = result
        return result

    def readiness(self) -> dict[str, Any]:
        if not self._last_probe.get("checked"):
            return self.probe()
        return dict(self._last_probe)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self.readiness().get("connected"):
            raise RuntimeError("Adapter implemented, runtime not connected.")
        kwargs.setdefault("temperature", self.temperature)
        kwargs.setdefault("timeout", self.timeout)
        # OpenAICompatibleProvider currently forwards temperature/timeout only.
        return self._delegate.generate(prompt, **kwargs)


class OpenWeightModelProvider(LocalModelProvider):
    """Same transport as LocalModelProvider; distinct registry kind for open-weight roles."""

    kind = "open_weight"


def build_local_or_open_weight(provider_id: str, **kwargs: Any) -> ModelProvider:
    settings = model_settings_from_env(kwargs)
    cls = OpenWeightModelProvider if provider_id == "open_weight" else LocalModelProvider
    return cls(
        base_url=str(kwargs.get("base_url") or settings["base_url"]),
        model=str(kwargs.get("model") or settings["model"]),
        api_key=str(kwargs.get("api_key") or settings["api_key"]),
        timeout=float(kwargs.get("timeout") or settings["timeout"]),
        max_tokens=int(kwargs.get("max_tokens") or settings["max_tokens"]),
        temperature=float(kwargs.get("temperature") or settings["temperature"]),
        context_length=int(kwargs.get("context_length") or settings["context_length"]),
        probe_on_init=bool(kwargs.get("probe_on_init", True)),
    )
