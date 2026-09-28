"""Email OTP delivery was permanently removed from PFAI.

This module remains only as an honest status reporter for observability /
phase gates. No providers, no SMTP/API clients, no mock send sinks.
"""
from __future__ import annotations

from typing import Any


def email_config_report(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Always report email OTP/login delivery as REMOVED (no secrets)."""
    return {
        "EMAIL_PROVIDER": "removed",
        "EMAIL_OTP": "REMOVED",
        "EMAIL_PRODUCTION_READY": False,
        "EMAIL_DELIVERY_STATUS": "REMOVED",
        "EMAIL_LIFECYCLE_STATUS": "REMOVED",
        "EMAIL_REQUIRE_PRODUCTION": False,
        "EMAIL_VERIFIED": False,
        "ok": True,
        "note": "Email OTP and login email delivery permanently removed; owner auth is passcode/session only",
        "host_configured": False,
        "endpoint_configured": False,
        "from_configured": False,
        "api_key_configured": False,
        "verify_evidence": None,
    }


def production_email_required() -> bool:
    return False
