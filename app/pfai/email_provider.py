"""Replaceable email delivery ports (PHASE 5).

Never log message bodies that may contain OTPs. Configuration via environment only.
"""
from __future__ import annotations

import os
import smtplib
import ssl
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
    @abstractmethod
    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        """Send email. Must not return body/OTP content."""
        ...

    def readiness(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.__class__.__name__}


class MockEmailProvider(EmailProvider):
    """Test/dev sink — captures metadata only, never exposes OTP via API."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._last_body_for_tests: str = ""  # tests may inspect via helper; never returned by API

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        # Store body only in-process for unit tests; strip OTP-looking digits from audit meta.
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
        return {"ok": True, "provider": "mock", "connected": True}


class SMTPEmailProvider(EmailProvider):
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
        return {
            "ok": bool(self.host and self.from_addr),
            "provider": "smtp",
            "host_configured": bool(self.host),
            "from_configured": bool(self.from_addr),
            # Do not claim connected without a live probe.
            "connected": False,
            "note": "SMTP configured; connectivity verified on send",
        }

    def send(self, message: EmailMessageSpec) -> dict[str, Any]:
        if not self.host or not (message.from_addr or self.from_addr):
            return {"ok": False, "error": "smtp_not_configured"}
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
            # Never include message body in error return
            return {"ok": False, "error": type(exc).__name__, "provider": "smtp"}


def email_provider_from_env() -> EmailProvider:
    kind = (os.environ.get("PFAI_EMAIL_PROVIDER") or "mock").strip().lower()
    if kind == "smtp":
        return SMTPEmailProvider(
            host=os.environ.get("PFAI_SMTP_HOST", ""),
            port=int(os.environ.get("PFAI_SMTP_PORT", "587") or 587),
            username=os.environ.get("PFAI_SMTP_USER", ""),
            password=os.environ.get("PFAI_SMTP_PASSWORD", ""),
            from_addr=os.environ.get("PFAI_SMTP_FROM", "") or os.environ.get("PFAI_SMTP_USER", ""),
            use_tls=(os.environ.get("PFAI_SMTP_TLS", "true").lower() in ("1", "true", "yes")),
            timeout=float(os.environ.get("PFAI_SMTP_TIMEOUT", "20") or 20),
        )
    return MockEmailProvider()
