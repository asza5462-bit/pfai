"""High-accuracy model adapter: calls the Anthropic Messages API (Claude).

Consistent with how every other secret in PFAI is handled (see owner_control.py),
the API key is never read from a config file and never logged — only from the
environment at call time. If it is missing, generation fails closed with a clear
error instead of silently falling back to a weaker provider.
"""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from .model import ModelProvider

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-opus-5"
API_VERSION = "2023-06-01"


class AnthropicProvider(ModelProvider):
    """Calls Claude for generation. Fails closed if no API key is configured."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 max_tokens: int = 2048, api_key_env: str = "ANTHROPIC_API_KEY"):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.api_key_env = api_key_env

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} must be set in the environment; "
                "PFAI never reads API keys from config files."
            )
        return key

    def generate(self, prompt: str, **kwargs) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")

        payload = {
            "model": kwargs.get("model", self.model),
            "max_tokens": int(kwargs.get("max_tokens", self.max_tokens)),
            "messages": [{"role": "user", "content": prompt}],
        }
        if kwargs.get("system"):
            payload["system"] = kwargs["system"]
        # Current Claude models deprecate non-default temperature/top_p/top_k.
        # Keep generation behavior controlled by prompting rather than sending
        # a parameter that can cause a 400 on newer models.

        req = urllib.request.Request(
            self.base_url + "/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key(),
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=kwargs.get("timeout", 30)) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Anthropic API: {exc.reason}") from exc

        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise RuntimeError("Anthropic API returned no text content")
        return text
