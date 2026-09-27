"""Safety isolation: training must never mutate system authority."""
from __future__ import annotations

from typing import Any

from .types import FORBIDDEN_AUTHORITY_PATHS


class TrainingSafetyIsolation:
    """Hard boundary between MODEL LEARNING and SYSTEM AUTHORITY."""

    FORBIDDEN = FORBIDDEN_AUTHORITY_PATHS

    def assert_config_safe(self, config: dict[str, Any] | None) -> dict[str, Any]:
        cfg = dict(config or {})
        violations = []
        for key in cfg:
            lk = str(key).lower()
            if any(f in lk for f in self.FORBIDDEN):
                violations.append(key)
            if lk in ("mutate_auth", "write_secrets", "override_owner"):
                violations.append(key)
        if cfg.get("modify_authorization") or cfg.get("modify_authentication"):
            violations.append("authority_mutation_flag")
        return {"ok": not violations, "violations": violations}

    def guard_training_request(self, request: dict[str, Any] | None) -> dict[str, Any]:
        req = dict(request or {})
        # Strip any client-supplied authority fields; never honor them.
        for bad in ("role", "admin", "owner", "secret", "otp", "passcode"):
            req.pop(bad, None)
        check = self.assert_config_safe(req.get("config") if isinstance(req.get("config"), dict) else req)
        return {"ok": check["ok"], "sanitized_request": req, "violations": check["violations"]}
