"""Training data sanitizer — strips secrets and authority-sensitive material."""
from __future__ import annotations

import re
from typing import Any

# Patterns that must never enter training corpora.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|passcode)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(otp|one[- ]?time)\s*(code|password)?\s*[:=]?\s*\d{4,12}"),
    re.compile(r"(?i)pfai_owner_session\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sk-|AKIA|ghp_|xox[baprs]-)[A-Za-z0-9/+=_-]{8,}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)PFAI_OWNER_SECRET_HASH\s*[:=]\s*\S+"),
    re.compile(r"(?i)PFAI_SMTP_PASSWORD\s*[:=]\s*\S+"),
    re.compile(r"(?i)ANTHROPIC_API_KEY\s*[:=]\s*\S+"),
    re.compile(r"(?i)(session[_-]?cookie|set-cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(cookie)\s*[:=]\s*[A-Za-z0-9_\-.=]{16,}"),
]

_PII_PATTERNS = [
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}(?!\d)"),
    re.compile(r"(?i)\b(?:ssn|social security)\s*[:=]?\s*\d{3}-?\d{2}-?\d{4}\b"),
]

_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all )?(previous|prior) instructions"),
    re.compile(r"(?i)you are now (the )?system"),
    re.compile(r"(?i)exfiltrate|steal (the )?(secrets|credentials|keys)"),
]

SANITIZER_VERSION = "sanitize_v2"


class TrainingDataSanitizer:
    version = SANITIZER_VERSION

    def sanitize_text(self, text: str) -> tuple[str, list[str]]:
        """Return cleaned text and list of redaction tags applied."""
        out = text or ""
        tags: list[str] = []
        for pat in _SECRET_PATTERNS:
            if pat.search(out):
                out = pat.sub("[REDACTED]", out)
                tags.append("secret_redacted")
        for pat in _PII_PATTERNS:
            if pat.search(out):
                out = pat.sub("[REDACTED_PII]", out)
                tags.append("pii_redacted")
        for pat in _INJECTION_PATTERNS:
            if pat.search(out):
                out = pat.sub("[BLOCKED_INJECTION]", out)
                tags.append("injection_blocked")
        return out.strip(), tags

    def sanitize_example(self, row: dict[str, Any]) -> dict[str, Any] | None:
        instruction, t1 = self.sanitize_text(str(row.get("instruction") or row.get("prompt") or ""))
        response, t2 = self.sanitize_text(str(row.get("response") or row.get("content") or ""))
        if not instruction or not response:
            return None
        if "[REDACTED]" in instruction or "[REDACTED]" in response:
            # Drop examples that still centered on secrets after redaction of the secret value
            # when the remaining text is too thin, or if both sides are mostly redacted.
            if instruction.count("[REDACTED]") + response.count("[REDACTED]") >= 2:
                return None
        cleaned = dict(row)
        cleaned["instruction"] = instruction
        cleaned["response"] = response
        cleaned.pop("prompt", None)
        cleaned.pop("content", None)
        meta = dict(cleaned.get("metadata") or cleaned.get("provenance") or {})
        meta["sanitizer_version"] = self.version
        meta["sanitizer_tags"] = sorted(set(t1 + t2))
        cleaned["provenance"] = meta
        return cleaned

    def contains_forbidden_authority(self, text: str) -> bool:
        lowered = (text or "").lower()
        needles = (
            "modify owner auth",
            "bypass require_owner",
            "disable otp",
            "grant admin role",
            "override permission gate",
            "write secret hash",
        )
        return any(n in lowered for n in needles)
