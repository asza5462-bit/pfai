"""Pytest defaults: keep legacy owner gates unless a test opts into public mode."""
from __future__ import annotations

import os


# Existing suite exercises owner-gated privileged APIs via X-Owner-Secret.
# Public Access Mode is covered by dedicated tests that set PFAI_PUBLIC_ACCESS_MODE=1.
os.environ.setdefault("PFAI_PUBLIC_ACCESS_MODE", "0")
os.environ.setdefault("PFAI_ENV", "test")
os.environ.setdefault("PFAI_COOKIE_SECURE", "false")
