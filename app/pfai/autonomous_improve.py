"""Autonomous self-improve cycle — detect → heal(safe) → learn → tick.

Bounded: never promotes weights, never mutates security, never runs arbitrary code.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from pfai.open_execution import auto_accept_learning, auto_safe_heal, open_execution_status

log = logging.getLogger("pfai.autonomy")


class AutonomousImproveOrchestrator:
    """One cohesive brain tick for self-check / safe heal / continuous learn."""

    def __init__(
        self,
        *,
        self_check: Any,
        self_heal: Any,
        continuous: Any,
        experience_record: Optional[Callable[..., dict]] = None,
    ) -> None:
        self.self_check = self_check
        self.self_heal = self_heal
        self.continuous = continuous
        self.experience_record = experience_record

    def status(self) -> dict[str, Any]:
        open_st = open_execution_status()
        cont = {}
        try:
            cont = self.continuous.status() if self.continuous else {}
        except Exception as exc:
            cont = {"error": str(exc)}
        return {
            "ok": True,
            "autonomy": open_st,
            "continuous": {
                "service": (cont.get("service") or {}).get("status"),
                "worker_alive": cont.get("worker_alive"),
                "pending_examples": cont.get("pending_examples"),
                "auto_promote": False,
                "auto_accept_learning": auto_accept_learning(),
            },
            "heal_safe_actions": sorted(getattr(self.self_heal, "_safe_actions", {}).keys()),
            "note": "Self-improve runs safe heal + learning accept; never silent weight promote",
        }

    def run_cycle(self, *, include_continuous_tick: bool = True) -> dict[str, Any]:
        t0 = time.time()
        timeline: list[dict[str, Any]] = []
        report = self.self_check.run_checks()
        timeline.append({"step": "self_check", "ok": bool(report.ok), "summary": report.summary})

        prop = self.self_heal.propose_fix(report)
        heal_out: dict[str, Any] = {
            "proposal_id": prop.proposal_id,
            "diagnosis": prop.diagnosis,
            "steps": list(prop.steps or []),
            "requires_owner": bool(prop.requires_owner),
            "applied": False,
            "rolled_back": False,
        }
        if report.ok:
            heal_out["note"] = "healthy — no heal needed"
        elif auto_safe_heal() and prop.safe and prop.reversible and prop.steps:
            applied = self.self_heal.apply_fix(prop.proposal_id, approved=True)
            heal_out["applied"] = bool(applied.applied and applied.ok)
            heal_out["apply_message"] = applied.message
            tested = self.self_heal.test_fix(prop.proposal_id)
            heal_out["recheck_ok"] = bool(tested.ok)
            if not tested.ok:
                rolled = self.self_heal.rollback_fix(prop.proposal_id)
                heal_out["rolled_back"] = bool(rolled.rolled_back)
                heal_out["rollback_message"] = rolled.message
            timeline.append({"step": "safe_heal", "ok": heal_out["applied"] and heal_out.get("recheck_ok", False)})
        else:
            heal_out["note"] = "heal proposed; waiting approval or no safe steps"
            timeline.append({"step": "safe_heal", "ok": False, "skipped": True})

        learn_note = {
            "auto_accept_learning": auto_accept_learning(),
            "auto_promote": False,
        }
        cont_out: dict[str, Any] | None = None
        if include_continuous_tick and self.continuous is not None:
            try:
                cont_out = self.continuous.tick_once()
                timeline.append({"step": "continuous_tick", "ok": bool((cont_out or {}).get("ok"))})
            except Exception as exc:
                cont_out = {"ok": False, "error": str(exc)}
                timeline.append({"step": "continuous_tick", "ok": False, "error": str(exc)})
                log.warning("autonomy continuous tick failed: %s", exc)

        if self.experience_record is not None:
            try:
                self.experience_record(
                    instruction="Summarize one autonomous self-improve cycle outcome.",
                    response=(
                        f"check_ok={report.ok}; heal_applied={heal_out.get('applied')}; "
                        f"learning_auto_accept={auto_accept_learning()}; weight_promote=false"
                    ),
                    source_id=f"autonomy:{prop.proposal_id}",
                    passed=bool(report.ok or heal_out.get("recheck_ok")),
                )
            except Exception as exc:
                log.debug("experience record skipped: %s", exc)

        return {
            "ok": True,
            "check_ok": bool(report.ok),
            "checks": list(report.checks or [])[:20],
            "heal": heal_out,
            "learning": learn_note,
            "continuous": cont_out,
            "timeline": timeline,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "autonomy": open_execution_status(),
            "weight_promotion": "never_auto",
        }
