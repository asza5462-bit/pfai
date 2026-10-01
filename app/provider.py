"""AI provider adapters for OpenAI-compatible and Anthropic APIs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings
from app.database import db


@dataclass(slots=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def config_for(user_id: int) -> ProviderConfig:
    provider = db.get_setting(user_id, "ai.provider", settings.default_provider).strip().lower()
    model = db.get_setting(user_id, "ai.model", settings.default_model).strip()
    base_url = db.get_setting(user_id, "ai.base_url", settings.openai_base_url).strip().rstrip("/")
    stored_key = db.get_setting(user_id, f"ai.key.{provider}", "")
    env_key = settings.anthropic_api_key if provider == "anthropic" else settings.openai_api_key
    return ProviderConfig(
        provider=provider,
        model=model,
        api_key=stored_key or env_key,
        base_url=base_url or settings.openai_base_url,
    )


def public_config(user_id: int) -> dict[str, Any]:
    config = config_for(user_id)
    return {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "configured": config.configured,
        "key_source": "saved" if db.get_setting(user_id, f"ai.key.{config.provider}", "") else ("environment" if config.configured else None),
        "providers": {
            "openai": ["gpt-5.2", "gpt-5", "gpt-4.1"],
            "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1"],
            "compatible": ["custom-model"],
        },
    }


def save_config(user_id: int, provider: str, model: str, api_key: str | None, base_url: str | None) -> dict:
    provider = provider.strip().lower()
    if provider not in {"openai", "anthropic", "compatible"}:
        raise HTTPException(400, "مزود الذكاء غير مدعوم")
    if not model.strip():
        raise HTTPException(400, "اسم النموذج مطلوب")
    db.set_setting(user_id, "ai.provider", provider)
    db.set_setting(user_id, "ai.model", model.strip())
    if base_url is not None:
        db.set_setting(user_id, "ai.base_url", base_url.strip().rstrip("/"))
    if api_key:
        if len(api_key.strip()) < 12:
            raise HTTPException(400, "مفتاح API قصير جداً")
        db.set_setting(user_id, f"ai.key.{provider}", api_key.strip(), encrypted=True)
    db.audit(user_id, "ai.configure", {"provider": provider, "model": model.strip()})
    return public_config(user_id)


async def complete(user_id: int, messages: list[dict[str, str]], *, max_tokens: int = 8192) -> str:
    config = config_for(user_id)
    if not config.configured:
        raise HTTPException(
            424,
            "اربط مزود ذكاء من الإعدادات أولاً. يدعم OpenAI وAnthropic وأي API متوافق مع OpenAI.",
        )
    if config.provider == "anthropic":
        return await _anthropic(config, messages, max_tokens=max_tokens)
    return await _openai_compatible(config, messages, max_tokens=max_tokens)


async def test_connection(user_id: int) -> dict[str, Any]:
    text = await complete(
        user_id,
        [
            {"role": "system", "content": "Reply with exactly: NOVA_OK"},
            {"role": "user", "content": "Connection test"},
        ],
        max_tokens=32,
    )
    return {"ok": "NOVA_OK" in text.upper(), "response": text[:200], **public_config(user_id)}


async def _openai_compatible(config: ProviderConfig, messages: list[dict[str, str]], *, max_tokens: int) -> str:
    url = f"{config.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.15,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"تعذّر الاتصال بمزود الذكاء: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code if response.status_code < 500 else 502, _provider_error(response))
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "استجابة غير صالحة من مزود الذكاء") from exc
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return str(content or "")


async def _anthropic(config: ProviderConfig, messages: list[dict[str, str]], *, max_tokens: int) -> str:
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    chat = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in {"user", "assistant"}]
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.model,
        "system": "\n\n".join(system_parts),
        "messages": chat,
        "max_tokens": max_tokens,
        "temperature": 0.15,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"تعذّر الاتصال بـ Anthropic: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code if response.status_code < 500 else 502, _provider_error(response))
    try:
        data = response.json()
        return "".join(item.get("text", "") for item in data["content"] if item.get("type") == "text")
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "استجابة غير صالحة من Anthropic") from exc


def _provider_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error", data)
            if isinstance(error, dict):
                message = error.get("message") or error.get("detail") or json.dumps(error, ensure_ascii=False)
            else:
                message = str(error)
            return f"خطأ مزود الذكاء ({response.status_code}): {message[:500]}"
    except ValueError:
        pass
    return f"خطأ مزود الذكاء ({response.status_code}): {response.text[:500]}"
