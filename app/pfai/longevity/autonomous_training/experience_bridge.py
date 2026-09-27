"""ContinuousExperienceBridge — record REAL operational outcomes only.

Never manufactures examples. Never trains from raw chat. Never stores secrets.
Callers must only invoke after a verified success / owner approval / correction.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .types import (
    AUTO_ACCEPT_TRUST,
    EXPERIENCE_TRUST,
    ExperienceSource,
    LearningEligibility,
)


# Optional process-wide hook set by API bootstrap (avoids circular imports).
_GLOBAL_BRIDGE: Any | None = None


def set_global_experience_bridge(bridge: Any | None) -> None:
    global _GLOBAL_BRIDGE
    _GLOBAL_BRIDGE = bridge


def get_global_experience_bridge() -> Any | None:
    return _GLOBAL_BRIDGE


def notify_skill_success(*, skill: str, summary: str, source_id: str = "") -> None:
    bridge = _GLOBAL_BRIDGE
    if bridge is None:
        return
    try:
        bridge.record_skill_success(
            instruction=f"Execute skill {skill}",
            result_summary=summary,
            source_id=source_id or f"skill:{skill}",
        )
    except Exception:
        return


class ContinuousExperienceBridge:
    """Fan-in from coding / knowledge / tools / skills / feedback into LearningCandidatePipeline."""

    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
        self._event_count = 0
        self._last_event_at = 0.0
        self._last_event_kind = ""

    def _pipeline(self):
        return self.orch.learning_pipeline_gate

    def _outcomes(self):
        return getattr(self.orch, "verified_outcomes", None)

    def _trust(self, attribution: str) -> float:
        return float(EXPERIENCE_TRUST.get(attribution, 0.5))

    def _mirror_outcome(self, *, kind: str, instruction: str, response: str, source_id: str, extra: dict[str, Any] | None = None) -> None:
        store = self._outcomes()
        if store is None:
            return
        try:
            store.append(
                {
                    "kind": kind,
                    "instruction": instruction,
                    "response": response,
                    "prompt": instruction,
                    "solution": response,
                    "code": response,
                    "id": source_id,
                    "source_id": source_id,
                    **(extra or {}),
                }
            )
        except Exception:
            return

    def record_event(
        self,
        *,
        instruction: str,
        response: str,
        attribution: str,
        source_id: str = "",
        verified: bool = False,
        success: bool = False,
        eligible_for_learning: bool = True,
        category: str = "",
        provenance: dict[str, Any] | None = None,
        require_owner_approved: bool = False,
        owner_approved: bool = False,
    ) -> dict[str, Any]:
        """Process one real operational observation through the LearningCandidate pipeline.

        Unsuccessful / unverified events become INELIGIBLE — never ACCEPTED.
        """
        self._event_count += 1
        self._last_event_at = time.time()
        self._last_event_kind = attribution

        if not eligible_for_learning:
            return {
                "ok": True,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "not_eligible_for_learning",
                "trained": False,
            }
        if not success and not verified and not owner_approved:
            return {
                "ok": True,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "unsuccessful_or_unverified",
                "trained": False,
            }
        if require_owner_approved and not owner_approved:
            return {
                "ok": True,
                "eligibility": LearningEligibility.PENDING_REVIEW.value,
                "reason": "awaiting_owner_approval",
                "trained": False,
            }
        if not (instruction or "").strip() or not (response or "").strip():
            return {
                "ok": False,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "empty_instruction_or_response",
                "trained": False,
            }

        trust = self._trust(attribution)
        pending = trust < AUTO_ACCEPT_TRUST and not owner_approved
        raw = {
            "instruction": instruction,
            "response": response,
            "source": attribution,
            "source_id": source_id or f"evt-{self._event_count}",
            "outcome": "approved" if (owner_approved or verified or success) else "unknown",
            "category": category or attribution.lower(),
            "verified": bool(verified or owner_approved or success),
            "attribution": attribution,
            "trust": trust,
            "force_pending_review": pending,
            "timestamp": self._last_event_at,
            "provenance": {
                **(provenance or {}),
                "attribution": attribution,
                "trust": trust,
                "eligible_for_learning": True,
                "continuous_experience": True,
                "synthetic": False,
            },
        }
        rec = self._pipeline().process_observation(raw)
        # Map pipeline lowercase eligibility onto explicit states when needed
        elig = rec.eligibility
        elig_l = str(elig or "").lower()
        if elig_l in ("accepted", LearningEligibility.ACCEPTED.value.lower()):
            if pending:
                # Downgrade high-quality but lower-trust accepts to PENDING_REVIEW
                rec.eligibility = LearningEligibility.PENDING_REVIEW.value
                rec.rejection_reason = ""
                self._pipeline().store.upsert(rec)
                elig = LearningEligibility.PENDING_REVIEW.value
            else:
                elig = LearningEligibility.ACCEPTED.value
                # Normalize stored eligibility to enum value
                if rec.eligibility != LearningEligibility.ACCEPTED.value:
                    rec.eligibility = LearningEligibility.ACCEPTED.value
                    self._pipeline().store.upsert(rec)
                # Mirror high-trust accepts into rediscoverable outcome store
                if attribution in (
                    ExperienceSource.CODE_TEST_PASS.value,
                    ExperienceSource.CORRECTED_FAILURE.value,
                ):
                    self._mirror_outcome(
                        kind="coding_passed",
                        instruction=instruction,
                        response=response,
                        source_id=source_id or rec.candidate_id,
                    )
                elif attribution == ExperienceSource.EVALUATION.value:
                    self._mirror_outcome(
                        kind="evaluation",
                        instruction=instruction,
                        response=response,
                        source_id=source_id or rec.candidate_id,
                    )
                # Future production-eval accumulation (never used to inflate training)
                try:
                    from .evaluation_dataset import EvaluationDatasetBuilder

                    acc = Path(str(self.orch.root)) / "evaluation_datasets" / "accumulator.jsonl"
                    acc.parent.mkdir(parents=True, exist_ok=True)
                    dig = rec.content_hash or ""
                    line = json.dumps(
                        {
                            "instruction": instruction,
                            "response": response,
                            "source": f"accumulator:{attribution}",
                            "source_id": source_id or rec.candidate_id,
                            "content_hash": dig,
                            "provenance": {
                                "continuous_experience": True,
                                "eligibility": elig,
                                "synthetic": False,
                            },
                        },
                        ensure_ascii=False,
                    )
                    # Append only if hash not already present (best-effort scan of last 2k lines)
                    exists = False
                    if dig and acc.exists():
                        tail = acc.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]
                        exists = any(dig in ln for ln in tail)
                    if not exists:
                        with acc.open("a", encoding="utf-8") as fh:
                            fh.write(line + "\n")
                except Exception:
                    pass
        elif elig_l in ("rejected", LearningEligibility.REJECTED.value.lower()):
            elig = LearningEligibility.REJECTED.value
            if rec.eligibility != LearningEligibility.REJECTED.value:
                rec.eligibility = LearningEligibility.REJECTED.value
                try:
                    self._pipeline().store.upsert(rec)
                except Exception:
                    pass
        elif elig_l in ("pending", "pending_review", LearningEligibility.PENDING_REVIEW.value.lower()):
            elig = LearningEligibility.PENDING_REVIEW.value

        self.orch.audit.record(
            "experience_recorded",
            attribution=attribution,
            eligibility=elig,
            source_id=source_id,
            candidate_id=rec.candidate_id,
            rejection_reason=rec.rejection_reason or "",
        )
        return {
            "ok": True,
            "eligibility": elig,
            "candidate_id": rec.candidate_id,
            "rejection_reason": rec.rejection_reason or "",
            "quality_score": rec.quality_score,
            "attribution": attribution,
            "trust": trust,
            "trained": False,
            "note": "Recorded as learning candidate only — does not trigger training.",
        }

    # --- typed helpers (real outcomes only) ---

    def record_code_test_pass(
        self,
        *,
        instruction: str,
        code: str,
        source_id: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.record_event(
            instruction=instruction,
            response=code,
            attribution=ExperienceSource.CODE_TEST_PASS.value,
            source_id=source_id,
            verified=True,
            success=True,
            category="coding",
            provenance=provenance,
        )

    def record_corrected_failure(
        self,
        *,
        instruction: str,
        corrected_response: str,
        source_id: str = "",
        tests_passed: bool = False,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not tests_passed:
            return {
                "ok": True,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "correction_not_verified",
                "trained": False,
            }
        return self.record_event(
            instruction=instruction,
            response=corrected_response,
            attribution=ExperienceSource.CORRECTED_FAILURE.value,
            source_id=source_id,
            verified=True,
            success=True,
            category="correction",
            provenance=provenance,
        )

    def record_knowledge_verified(
        self,
        *,
        content: str,
        source_id: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.record_event(
            instruction="Apply this verified PFAI knowledge entry",
            response=content,
            attribution=ExperienceSource.KNOWLEDGE_VERIFIED.value,
            source_id=source_id,
            verified=True,
            success=True,
            category="knowledge",
            provenance=provenance,
        )

    def record_owner_feedback(
        self,
        *,
        instruction: str,
        response: str,
        source_id: str = "",
        approved: bool = True,
    ) -> dict[str, Any]:
        return self.record_event(
            instruction=instruction,
            response=response,
            attribution=ExperienceSource.FEEDBACK.value,
            source_id=source_id,
            verified=True,
            success=True,
            owner_approved=bool(approved),
            require_owner_approved=True,
            category="owner_feedback",
        )

    def record_user_approved_task(
        self,
        *,
        instruction: str,
        response: str,
        source_id: str = "",
    ) -> dict[str, Any]:
        return self.record_event(
            instruction=instruction,
            response=response,
            attribution=ExperienceSource.USER_APPROVED.value,
            source_id=source_id,
            verified=True,
            success=True,
            owner_approved=True,
            category="task",
        )

    def record_tool_success(
        self,
        *,
        instruction: str,
        result_summary: str,
        source_id: str = "",
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Never accept raw tool payloads that may contain secrets
        if raw_payload and any(
            k in raw_payload for k in ("secret", "token", "password", "otp", "cookie", "api_key")
        ):
            return {
                "ok": True,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "tool_payload_contains_secrets",
                "trained": False,
            }
        return self.record_event(
            instruction=instruction,
            response=result_summary,
            attribution=ExperienceSource.TOOL_SUCCESS.value,
            source_id=source_id,
            success=True,
            verified=True,
            category="tool",
        )

    def record_skill_success(
        self,
        *,
        instruction: str,
        result_summary: str,
        source_id: str = "",
    ) -> dict[str, Any]:
        return self.record_event(
            instruction=instruction,
            response=result_summary,
            attribution=ExperienceSource.SKILL_SUCCESS.value,
            source_id=source_id,
            success=True,
            verified=True,
            category="skill",
        )

    def record_self_check(
        self,
        *,
        instruction: str,
        response: str,
        source_id: str = "",
        passed: bool = False,
    ) -> dict[str, Any]:
        if not passed:
            return {
                "ok": True,
                "eligibility": LearningEligibility.INELIGIBLE.value,
                "reason": "self_check_failed",
                "trained": False,
            }
        return self.record_event(
            instruction=instruction,
            response=response,
            attribution=ExperienceSource.SELF_CHECK.value,
            source_id=source_id,
            success=True,
            verified=True,
            category="self_check",
        )

    def record_evaluation_lesson(
        self,
        *,
        instruction: str,
        response: str,
        source_id: str = "",
    ) -> dict[str, Any]:
        return self.record_event(
            instruction=instruction,
            response=response,
            attribution=ExperienceSource.EVALUATION.value,
            source_id=source_id,
            verified=True,
            success=True,
            category="evaluation",
        )

    def record_raw_chat_attempt(self, *, instruction: str, response: str) -> dict[str, Any]:
        """Raw chats are never training data."""
        return {
            "ok": True,
            "eligibility": LearningEligibility.INELIGIBLE.value,
            "reason": "raw_chat_never_trained",
            "trained": False,
            "instruction_len": len(instruction or ""),
            "response_len": len(response or ""),
        }

    def status(self) -> dict[str, Any]:
        return {
            "events_recorded": self._event_count,
            "last_event_at": self._last_event_at,
            "last_event_kind": self._last_event_kind,
            "synthetic_generation": False,
            "raw_chat_training": False,
        }
