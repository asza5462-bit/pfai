"""Enable/disable gate for continuous training.

Priority:
1. Environment variable ``PFAI_CONTINUOUS_TRAINING_ENABLED`` when set to a
   recognized truthy/falsey value (force override).
2. Otherwise ``continuous_training.enabled`` from the JSON config.

Promotion to an active production model is intentionally *not* controlled here —
that remains owner-gated in LearningLoop / API routes.
"""
from __future__ import annotations

import os
from typing import Any

from .config import Config

ENV_NAME = "PFAI_CONTINUOUS_TRAINING_ENABLED"
_FALSEY = {"0", "false", "off", "no", "disabled"}
_TRUTHY = {"1", "true", "on", "yes", "enabled"}


def env_override() -> bool | None:
    """Return True/False when the env var forces a value, else None."""
    raw = os.environ.get(ENV_NAME, "").strip().lower()
    if not raw:
        return None
    if raw in _FALSEY:
        return False
    if raw in _TRUTHY:
        return True
    return None


def is_continuous_enabled(config_path: str = "configs/default.json", cfg: dict[str, Any] | None = None) -> bool:
    forced = env_override()
    if forced is not None:
        return forced
    data = cfg if cfg is not None else Config.load(config_path)
    return bool(data.get("continuous_training", {}).get("enabled", False))


def continuous_gate_status(config_path: str = "configs/default.json") -> dict[str, Any]:
    cfg = Config.load(config_path)
    config_enabled = bool(cfg.get("continuous_training", {}).get("enabled", False))
    forced = env_override()
    enabled = is_continuous_enabled(config_path, cfg=cfg)
    return {
        "enabled": enabled,
        "config_enabled": config_enabled,
        "env_var": ENV_NAME,
        "env_override": forced,
        "auto_promote": False,
        "require_human_approval": True,
        "notes": "Learning/curation may run when enabled; promotion to active always requires owner approval.",
    }
