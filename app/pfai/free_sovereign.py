"""Free Sovereign Integrity — full audit, self-correct, productive freedom.

User intent: no faults, self-learning repair of bad/conflicting code, full
productive authority, unrestricted continuous evolution.

Honest bounds (never unlocked here):
- Silent model weight promotion / activation
- SSRF / arbitrary network bypass
- Secret reads / security policy mutation
- Arbitrary host code rewrite outside sandbox curriculum repairs

Everything else productive is driven hard: heal, migrate, workers, sandbox
code repair, continuous curation, evolution cadence.
"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.free_sovereign")


class FreeSovereignIntegrity:
    """One-brain integrity: audit → repair → retest → learn."""

    VERSION = "8.9.0"

    def __init__(
        self,
        *,
        self_check_fn: Callable[[], Any],
        heal_propose_fn: Callable[[Any], Any],
        heal_apply_fn: Callable[[str], Any],
        heal_test_fn: Callable[[str], Any] | None = None,
        migrate_status_fn: Callable[[], dict] | None = None,
        migrate_apply_fn: Callable[[], dict] | None = None,
        continuous_ensure_fn: Callable[[], dict] | None = None,
        continuous_tick_fn: Callable[[], dict] | None = None,
        evolution_ensure_fn: Callable[[], dict] | None = None,
        evolution_tick_fn: Callable[[], dict] | None = None,
        advanced_develop_fn: Callable[[], dict] | None = None,
        autonomy_fn: Callable[[], dict] | None = None,
        quantum_pulse_fn: Callable[[], dict] | None = None,
        open_status_fn: Callable[[], dict] | None = None,
        regression_repair_fn: Callable[[], dict] | None = None,
        conflict_scan_fn: Callable[[], dict] | None = None,
    ) -> None:
        self.self_check_fn = self_check_fn
        self.heal_propose_fn = heal_propose_fn
        self.heal_apply_fn = heal_apply_fn
        self.heal_test_fn = heal_test_fn
        self.migrate_status_fn = migrate_status_fn
        self.migrate_apply_fn = migrate_apply_fn
        self.continuous_ensure_fn = continuous_ensure_fn
        self.continuous_tick_fn = continuous_tick_fn
        self.evolution_ensure_fn = evolution_ensure_fn
        self.evolution_tick_fn = evolution_tick_fn
        self.advanced_develop_fn = advanced_develop_fn
        self.autonomy_fn = autonomy_fn
        self.quantum_pulse_fn = quantum_pulse_fn
        self.open_status_fn = open_status_fn
        self.regression_repair_fn = regression_repair_fn
        self.conflict_scan_fn = conflict_scan_fn
        self._cycles = 0
        self._last: dict[str, Any] = {}

    def _safe(self, label: str, fn: Optional[Callable[[], Any]], *args: Any) -> dict[str, Any]:
        if fn is None:
            return {"ok": False, "skipped": True, "label": label, "reason": "no_fn"}
        t0 = time.time()
        try:
            out = fn(*args) if args else fn()
            if hasattr(out, "__dict__") and not isinstance(out, dict):
                # SelfCheckReport / HealProposal dataclasses
                d = {
                    "ok": bool(getattr(out, "ok", True)),
                    "summary": getattr(out, "summary", None),
                    "proposal_id": getattr(out, "proposal_id", None),
                    "diagnosis": getattr(out, "diagnosis", None),
                    "steps": list(getattr(out, "steps", None) or []),
                    "requires_owner": getattr(out, "requires_owner", None),
                    "safe": getattr(out, "safe", None),
                    "checks": getattr(out, "checks", None),
                    "message": getattr(out, "message", None),
                    "applied": getattr(out, "applied", None),
                }
                # prune Nones
                out = {k: v for k, v in d.items() if v is not None}
            if not isinstance(out, dict):
                out = {"ok": True, "value": out}
            out.setdefault("ok", True)
            out["_label"] = label
            out["_ms"] = int((time.time() - t0) * 1000)
            return out
        except Exception as exc:
            log.warning("sovereign %s failed: %s", label, exc)
            return {
                "ok": False,
                "error": str(exc)[:240],
                "traceback": traceback.format_exc()[-400:],
                "_label": label,
                "_ms": int((time.time() - t0) * 1000),
            }

    def freedom_map(self) -> dict[str, Any]:
        open_st = {}
        if self.open_status_fn:
            try:
                open_st = self.open_status_fn() or {}
            except Exception as exc:
                open_st = {"error": str(exc)[:120]}
        return {
            "unlocked_productive": [
                "chat_tools_no_approval_wait" if open_st.get("open_chat_tools") else None,
                "auto_accept_learning_candidates" if open_st.get("auto_accept_learning") else None,
                "auto_safe_heal" if open_st.get("auto_safe_heal") else None,
                "continuous_curation_worker",
                "evolution_minute_hour_day",
                "sandbox_code_self_repair",
                "schema_self_migrate",
                "quantum_inspired_local_pulse",
                "iot_grounded_mind",
            ],
            "still_hard_gated": list(open_st.get("still_gated") or [
                "model_weight_promotion",
                "ssrf_and_arbitrary_network",
                "security_policy_mutation",
                "secret_read",
                "arbitrary_host_code_rewrite",
            ]),
            "open_execution": open_st,
            "philosophy": (
                "Free sovereign AI = maximum productive autonomy + honest hard bounds. "
                "No fake unrestricted claims that break security."
            ),
        }

    def audit(self) -> dict[str, Any]:
        """High-precision full-system audit."""
        t0 = time.time()
        report = self._safe("self_check", self.self_check_fn)
        migrate = self._safe("migrate_status", self.migrate_status_fn) if self.migrate_status_fn else {}
        conflicts = self._safe("conflict_scan", self.conflict_scan_fn) if self.conflict_scan_fn else {}
        quantum = self._safe("quantum", self.quantum_pulse_fn) if self.quantum_pulse_fn else {}
        failures = []
        for c in report.get("checks") or []:
            if isinstance(c, dict) and not c.get("ok"):
                failures.append(c.get("name") or "check")
        pending = int(migrate.get("pending_count") or 0)
        if pending > 0:
            failures.append(f"schema_pending:{pending}")
        if conflicts.get("ok") is False or (conflicts.get("conflicts") or []):
            failures.append("module_conflicts")
        freedom = self.freedom_map()
        out = {
            "ok": report.get("ok") is True and pending == 0 and not (conflicts.get("conflicts") or []),
            "self_check": {
                "ok": report.get("ok"),
                "summary": report.get("summary"),
                "failures": failures[:20],
                "n_checks": len(report.get("checks") or []),
            },
            "schema": {
                "current": migrate.get("current"),
                "target": migrate.get("target"),
                "pending_count": pending,
                "pending": migrate.get("pending") or [],
            },
            "conflicts": conflicts,
            "quantum_timing": (quantum.get("timing") if isinstance(quantum, dict) else None),
            "freedom": freedom,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "weight_promotion": "never_auto",
            "version": self.VERSION,
        }
        return out

    def repair(self, *, deep_code: bool = True) -> dict[str, Any]:
        """Apply all safe repairs. Never promotes weights."""
        timeline: list[dict[str, Any]] = []
        t0 = time.time()

        # 1) Schema migrate if pending
        mig_st = self._safe("migrate_status", self.migrate_status_fn) if self.migrate_status_fn else {}
        if int(mig_st.get("pending_count") or 0) > 0 and self.migrate_apply_fn:
            mig = self._safe("migrate_apply", self.migrate_apply_fn)
            timeline.append({"step": "schema_migrate", "ok": bool(mig.get("ok")), "detail": {
                "current": mig.get("current") or mig.get("to_version"),
                "error": mig.get("error"),
                "applied": mig.get("applied"),
            }})
        else:
            timeline.append({"step": "schema_migrate", "ok": True, "skipped": True})

        # 2) Ensure continuous + evolution workers
        if self.continuous_ensure_fn:
            timeline.append({"step": "ensure_continuous", **{k: v for k, v in self._safe("ensure_continuous", self.continuous_ensure_fn).items() if k in ("ok", "worker_alive", "real_loop", "error")}})
        if self.evolution_ensure_fn:
            timeline.append({"step": "ensure_evolution", **{k: v for k, v in self._safe("ensure_evolution", self.evolution_ensure_fn).items() if k in ("ok", "alive", "running", "error")}})

        # 3) Self-heal from fresh check
        report = self.self_check_fn()
        prop = self.heal_propose_fn(report)
        pid = getattr(prop, "proposal_id", None) or (prop.get("proposal_id") if isinstance(prop, dict) else None)
        steps = list(getattr(prop, "steps", None) or (prop.get("steps") if isinstance(prop, dict) else []) or [])
        heal_out: dict[str, Any] = {"ok": True, "applied": False, "steps": steps}
        if steps and pid:
            applied = self._safe("heal_apply", lambda: self.heal_apply_fn(pid))
            heal_out = {"ok": bool(applied.get("ok")), "applied": bool(applied.get("ok")), "steps": steps, "message": applied.get("message")}
            if self.heal_test_fn and applied.get("ok"):
                tested = self._safe("heal_test", lambda: self.heal_test_fn(pid))
                heal_out["recheck_ok"] = bool(tested.get("ok"))
        timeline.append({"step": "safe_heal", **heal_out})

        # 4) Conflict scan + optional regression/code repair
        if self.conflict_scan_fn:
            timeline.append({"step": "conflict_scan", **{k: self._safe("conflict_scan", self.conflict_scan_fn).get(k) for k in ("ok", "conflicts", "error")}})
        if deep_code and self.regression_repair_fn:
            timeline.append({"step": "regression_repair", **{k: self._safe("regression_repair", self.regression_repair_fn).get(k) for k in ("ok", "repaired", "error", "skipped")}})
        if deep_code and self.advanced_develop_fn:
            adv = self._safe("advanced_develop", self.advanced_develop_fn)
            timeline.append({
                "step": "sandbox_code_self_build",
                "ok": bool(adv.get("ok")),
                "solved": (adv.get("build") or {}).get("solved") if isinstance(adv.get("build"), dict) else adv.get("solved"),
                "ran": adv.get("ran"),
            })

        # 5) Autonomy + continuous tick + evolution minute
        if self.autonomy_fn:
            timeline.append({"step": "autonomy", "ok": bool(self._safe("autonomy", self.autonomy_fn).get("ok"))})
        if self.continuous_tick_fn:
            timeline.append({"step": "continuous_tick", "ok": bool(self._safe("continuous_tick", self.continuous_tick_fn).get("ok"))})
        if self.evolution_tick_fn:
            timeline.append({"step": "evolution_minute", "ok": bool(self._safe("evolution_minute", self.evolution_tick_fn).get("ok"))})

        ok = all(bool(s.get("ok", True)) or s.get("skipped") for s in timeline)
        return {
            "ok": ok,
            "timeline": timeline,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "weight_promotion": "never_auto",
            "version": self.VERSION,
        }

    def sovereign_cycle(self, *, deep_code: bool = True) -> dict[str, Any]:
        """Full free-sovereign cycle: audit → repair → re-audit."""
        self._cycles += 1
        before = self.audit()
        repair = self.repair(deep_code=deep_code)
        after = self.audit()
        out = {
            "ok": bool(after.get("ok")) and bool(repair.get("ok")),
            "cycle": self._cycles,
            "before": {
                "ok": before.get("ok"),
                "failures": (before.get("self_check") or {}).get("failures"),
                "schema_pending": (before.get("schema") or {}).get("pending_count"),
            },
            "repair": repair,
            "after": {
                "ok": after.get("ok"),
                "failures": (after.get("self_check") or {}).get("failures"),
                "schema_pending": (after.get("schema") or {}).get("pending_count"),
                "schema_current": (after.get("schema") or {}).get("current"),
            },
            "freedom": after.get("freedom"),
            "improved": (not before.get("ok")) and bool(after.get("ok")),
            "weight_promotion": "never_auto",
            "note": (
                "Free sovereign cycle completed. Productive autonomy maximized; "
                "weight promotion / SSRF / secrets remain hard-gated."
            ),
            "version": self.VERSION,
        }
        self._last = out
        return out

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "version": self.VERSION,
            "cycles": self._cycles,
            "last_ok": (self._last or {}).get("ok"),
            "freedom": self.freedom_map(),
            "weight_promotion": "never_auto",
        }
