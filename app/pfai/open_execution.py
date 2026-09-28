"""Open Chat Tool Execution — align tool locks with Public Access Mode.

When unlocked, Command Chat tools execute immediately (no 🔒 / approval wait).
Model *promotion* / weight activation stays on privileged training APIs and is
never auto-started from chat.
"""
from __future__ import annotations

import os


def _flag(name: str) -> str | None:
    v = os.environ.get(name, "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return "off"
    if v in ("1", "true", "yes", "on"):
        return "on"
    return None


def _is_production_env() -> bool:
    return os.environ.get("PFAI_ENV", "").strip().lower() in {"production", "prod"}


def open_chat_tools() -> bool:
    """True ⇒ chat tools run without owner-approval wait / lock icons.

    Precedence:
      1. PFAI_OPEN_CHAT_TOOLS explicit on/off
      2. PFAI_PUBLIC_ACCESS_MODE explicit on/off
      3. Default ON in production/prod (same as Public Access Mode)
    """
    explicit = _flag("PFAI_OPEN_CHAT_TOOLS")
    if explicit == "on":
        return True
    if explicit == "off":
        return False
    pub = _flag("PFAI_PUBLIC_ACCESS_MODE")
    if pub == "on":
        return True
    if pub == "off":
        return False
    return _is_production_env()


def open_execution_status() -> dict:
    return {
        "open_chat_tools": open_chat_tools(),
        "public_access_mode_env": os.environ.get("PFAI_PUBLIC_ACCESS_MODE", ""),
        "open_chat_tools_env": os.environ.get("PFAI_OPEN_CHAT_TOOLS", ""),
        "pfai_env": os.environ.get("PFAI_ENV", ""),
        "locks_visible": not open_chat_tools(),
        "note": "Model promotion never auto-runs from chat; training cycle stays on /platform/training/*",
    }
