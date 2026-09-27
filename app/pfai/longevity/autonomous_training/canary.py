"""Canary / shadow promotion controls (PHASE 7)."""
from __future__ import annotations

import os
from typing import Any


class CanaryController:
    def __init__(self) -> None:
        self.enabled = (os.environ.get("MODEL_CANARY_ENABLED") or "true").lower() in (
            "1",
            "true",
            "yes",
        )
        self.request_limit = int(os.environ.get("MODEL_CANARY_REQUEST_LIMIT", "50"))
        self.failure_threshold = float(os.environ.get("MODEL_CANARY_FAILURE_THRESHOLD", "0.2"))

    def evaluate_shadow(self, shadow_report: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": bool(shadow_report.get("ok", True)),
                "mode": "shadow_disabled_pass_through",
                "decision": "CONTINUE" if shadow_report.get("ok", True) else "STOP_ACTIVATION",
            }
        ok = shadow_report.get("decision") != "STOP_ACTIVATION" and bool(shadow_report.get("ok", False))
        regression = float(shadow_report.get("regression") or 0)
        if regression > self.failure_threshold:
            ok = False
        return {
            "ok": ok,
            "mode": "shadow",
            "request_limit": self.request_limit,
            "failure_threshold": self.failure_threshold,
            "regression": regression,
            "decision": "CONTINUE" if ok else "STOP_ACTIVATION",
        }
