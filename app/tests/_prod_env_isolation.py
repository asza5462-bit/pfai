"""Isolate unit tests from a live production.env / shell exports."""
from __future__ import annotations

import os
from contextlib import contextmanager
from unittest import mock

_CLEAR_KEYS = (
    "PFAI_WEB_ALLOW_NETWORK",
    "PFAI_WEB_SEARCH_PROVIDER",
    "PFAI_WEB_FETCH_PROVIDER",
    "PFAI_WEB_SEARCH_ENDPOINT",
    "PFAI_WEB_SEARCH_API_KEY",
    "PFAI_EMAIL_PROVIDER",
    "PFAI_EMAIL_REQUIRE_PRODUCTION",
    "PFAI_EMAIL_API_KEY",
    "PFAI_EMAIL_API_ENDPOINT",
    "PFAI_EMAIL_FROM",
    "PFAI_ENV",
    "ENV",
    "PFAI_SMTP_HOST",
    "PFAI_SMTP_PASSWORD",
    "PFAI_SMTP_USER",
    "PFAI_SMTP_FROM",
    "SMTP_HOST",
    "SMTP_PASSWORD",
    "EMAIL_API_KEY",
)


@contextmanager
def isolated_unconfigured_env():
    """Force honest NOT_CONFIGURED / REMOVED paths regardless of host production secrets."""
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in _CLEAR_KEYS:
            os.environ.pop(k, None)
        os.environ["PFAI_ENV"] = "test"
        yield
