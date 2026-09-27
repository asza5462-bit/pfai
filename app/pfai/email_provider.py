"""PHASE 13 email providers — provider-agnostic, fail-closed in production.

Never log OTP bodies. Credentials only from environment.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


@dataclass
class EmailMessageSpec:
    to: str
    subject: str
    body_text: str
    from_addr: str = ""


class EmailProvider(ABC):
    provider_id: str = "abstract"

    @abstractmethod
    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        """Send email. Must not return body/OTP content."""
        ...

    def readiness(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.provider_id}


class MockEmailProvider(EmailProvider):
    """Test/dev sink ONLY — never selected when production email is required."""

    provider_id = "mock"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._last_body_for_tests: str = ""

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        self._last_body_for_tests = message.body_text
        self.sent.append(
            {
                "to": message.to,
                "subject": message.subject,
                "from": message.from_addr,
                "body_len": len(message.body_text or ""),
            }
        )
        return {"ok": True, "provider": "mock", "to": message.to}

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": "mock",
            "connected": True,
            "production_ready": False,
            "note": "test_only",
        }


class SMTPEmailProvider(EmailProvider):
    provider_id = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        use_tls: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.from_addr = from_addr or username
        self.use_tls = use_tls
        self.timeout = float(timeout)

    def readiness(self) -> dict[str, Any]:
        configured = bool(self.host and self.from_addr)
        return {
            "ok": configured,
            "provider": "smtp",
            "host_configured": bool(self.host),
            "from_configured": bool(self.from_addr),
            "connected": False,
            "production_ready": configured,
            "note": "SMTP configured; connectivity verified on send",
        }

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        if not self.host or not (message.from_addr or self.from_addr):
            return {"ok": False, "error": "smtp_not_configured", "provider": "smtp"}
        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = message.from_addr or self.from_addr
        msg["To"] = message.to
        msg.set_content(message.body_text)
        try:
            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                    server.starttls(context=context)
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            return {"ok": True, "provider": "smtp", "to": message.to}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "provider": "smtp"}


class APIEmailProvider(EmailProvider):
    """Generic HTTP email API adapter (SendGrid-like JSON POST). Provider-agnostic."""

    provider_id = "api"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str = "",
        from_addr: str = "",
        timeout: float = 20.0,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
    ) -> None:
        self.endpoint = (endpoint or "").strip()
        self.api_key = api_key
        self.from_addr = from_addr
        self.timeout = float(timeout)
        self.auth_header = auth_header or "Authorization"
        self.auth_scheme = auth_scheme

    def readiness(self) -> dict[str, Any]:
        configured = bool(self.endpoint and self.from_addr and self.api_key)
        return {
            "ok": configured,
            "provider": "api",
            "endpoint_configured": bool(self.endpoint),
            "from_configured": bool(self.from_addr),
            "api_key_configured": bool(self.api_key),
            "connected": False,
            "production_ready": configured,
            "note": "API email configured; delivery verified on send",
        }

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        if not self.endpoint or not self.api_key:
            return {"ok": False, "error": "api_email_not_configured", "provider": "api"}
        payload = {
            "to": message.to,
            "from": message.from_addr or self.from_addr,
            "subject": message.subject,
            "text": message.body_text,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            self.auth_header: f"{self.auth_scheme} {self.api_key}".strip(),
        }
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                _ = resp.read(256)
                return {"ok": True, "provider": "api", "to": message.to, "status": getattr(resp, "status", 200)}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"http_{exc.code}", "provider": "api"}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "provider": "api"}


class FailClosedEmailProvider(EmailProvider):
    """Used when production requires email but configuration is incomplete."""

    provider_id = "unconfigured"

    def __init__(self, reason: str = "email_not_configured") -> None:
        self.reason = reason

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        return {"ok": False, "error": self.reason, "provider": "unconfigured"}

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": "unconfigured",
            "production_ready": False,
            "error": self.reason,
        }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def production_email_required() -> bool:
    """True when silent Mock fallback is forbidden."""
    if _env_bool("PFAI_EMAIL_REQUIRE_PRODUCTION", False):
        return True
    env = (os.environ.get("PFAI_ENV") or os.environ.get("ENV") or "").strip().lower()
    return env in ("production", "prod", "staging")


def email_provider_from_env(*, allow_mock: bool | None = None) -> EmailProvider:
    kind = (os.environ.get("PFAI_EMAIL_PROVIDER") or "").strip().lower()
    require_prod = production_email_required()
    if allow_mock is None:
        allow_mock = not require_prod

    if kind in ("", "mock"):
        if require_prod and not allow_mock:
            return FailClosedEmailProvider("production_forbids_mock_email")
        if not kind:
            # Explicit default for non-production
            return MockEmailProvider()
        return MockEmailProvider()

    if kind == "smtp":
        provider = SMTPEmailProvider(
            host=os.environ.get("PFAI_SMTP_HOST", ""),
            port=int(os.environ.get("PFAI_SMTP_PORT", "587") or 587),
            username=os.environ.get("PFAI_SMTP_USER", ""),
            password=os.environ.get("PFAI_SMTP_PASSWORD", ""),
            from_addr=os.environ.get("PFAI_SMTP_FROM", "") or os.environ.get("PFAI_SMTP_USER", ""),
            use_tls=(os.environ.get("PFAI_SMTP_TLS", "true").lower() in ("1", "true", "yes")),
            timeout=float(os.environ.get("PFAI_SMTP_TIMEOUT", "20") or 20),
        )
        ready = provider.readiness()
        if require_prod and not ready.get("production_ready"):
            return FailClosedEmailProvider("smtp_incomplete_configuration")
        return provider

    if kind == "api":
        provider = APIEmailProvider(
            endpoint=os.environ.get("PFAI_EMAIL_API_ENDPOINT", ""),
            api_key=os.environ.get("PFAI_EMAIL_API_KEY", ""),
            from_addr=os.environ.get("PFAI_EMAIL_FROM", "") or os.environ.get("PFAI_SMTP_FROM", ""),
            timeout=float(os.environ.get("PFAI_EMAIL_API_TIMEOUT", "20") or 20),
            auth_header=os.environ.get("PFAI_EMAIL_API_AUTH_HEADER", "Authorization"),
            auth_scheme=os.environ.get("PFAI_EMAIL_API_AUTH_SCHEME", "Bearer"),
        )
        ready = provider.readiness()
        if require_prod and not ready.get("production_ready"):
            return FailClosedEmailProvider("api_email_incomplete_configuration")
        return provider

    if require_prod:
        return FailClosedEmailProvider(f"unknown_email_provider:{kind}")
    return MockEmailProvider()


def email_config_report(provider: EmailProvider | None = None) -> dict[str, Any]:
    """Startup/config report without revealing secrets."""
    prov = provider or email_provider_from_env()
    ready = prov.readiness() if hasattr(prov, "readiness") else {"ok": False}
    kind = getattr(prov, "provider_id", None) or ready.get("provider") or type(prov).__name__
    if kind in ("MockEmailProvider", "mock"):
        kind = "mock"
    elif kind in ("SMTPEmailProvider", "smtp"):
        kind = "smtp"
    elif kind in ("APIEmailProvider", "api"):
        kind = "api"
    elif kind in ("FailClosedEmailProvider", "unconfigured"):
        kind = "unconfigured"
    production_ready = bool(ready.get("production_ready")) and kind in ("smtp", "api")
    return {
        "EMAIL_PROVIDER": kind,
        "EMAIL_PRODUCTION_READY": production_ready,
        "EMAIL_REQUIRE_PRODUCTION": production_email_required(),
        "ok": bool(ready.get("ok")),
        "note": ready.get("note") or ready.get("error") or "",
        # never include keys/passwords/hosts secrets beyond booleans already in readiness
        "host_configured": ready.get("host_configured"),
        "endpoint_configured": ready.get("endpoint_configured"),
        "from_configured": ready.get("from_configured"),
        "api_key_configured": ready.get("api_key_configured"),
    }
