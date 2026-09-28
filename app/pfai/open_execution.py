"""Open execution policy — unlock productive autonomy without unsafe side effects.

Unlocked (when open):
  - Chat tool approval waits / lock icons
  - Auto-accept curated learning candidates (dataset/knowledge proposals)
  - Auto-apply *registered safe* self-heal steps (cache/eval/compat/worker)

Never unlocked here:
  - Silent model weight promotion / activation
  - SSRF / arbitrary network bypass
  - Security policy mutation, secret reads, arbitrary code rewrite
  - Forbidden heal action names (see self_check.FORBIDDEN_SAFE_ACTION_PATTERNS)
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


def auto_accept_learning() -> bool:
    """Accept eligible curated learning candidates without a human click.

    Does NOT promote/activate model weights. Weight activation stays on
    explicit training APIs (`activate_if_pass` / promote endpoints).
    """
    explicit = _flag("PFAI_AUTO_ACCEPT_LEARNING")
    if explicit == "on":
        return True
    if explicit == "off":
        return False
    return open_chat_tools()


def auto_safe_heal() -> bool:
    """Apply registered low-risk heal steps without approval wait."""
    explicit = _flag("PFAI_AUTO_SAFE_HEAL")
    if explicit == "on":
        return True
    if explicit == "off":
        return False
    return open_chat_tools()


def open_execution_status() -> dict:
    return {
        "open_chat_tools": open_chat_tools(),
        "auto_accept_learning": auto_accept_learning(),
        "auto_safe_heal": auto_safe_heal(),
        "public_access_mode_env": os.environ.get("PFAI_PUBLIC_ACCESS_MODE", ""),
        "open_chat_tools_env": os.environ.get("PFAI_OPEN_CHAT_TOOLS", ""),
        "auto_accept_learning_env": os.environ.get("PFAI_AUTO_ACCEPT_LEARNING", ""),
        "auto_safe_heal_env": os.environ.get("PFAI_AUTO_SAFE_HEAL", ""),
        "pfai_env": os.environ.get("PFAI_ENV", ""),
        "locks_visible": not open_chat_tools(),
        "still_gated": [
            "model_weight_promotion",
            "ssrf_and_arbitrary_network",
            "security_policy_mutation",
            "secret_read",
            "arbitrary_code_rewrite",
        ],
        "note": (
            "Open mode unlocks chat tools, learning-candidate accept, and safe heal. "
            "Weight promotion never auto-runs from chat."
        ),
    }
