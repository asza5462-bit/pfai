"""Safe observation adapters for LearningCandidatePipeline (no raw secrets/logs)."""
from __future__ import annotations

from typing import Any, Iterable

from .collector import collect_from_learning_pipeline
from .experience_seeds import approved_pfai_seed_examples


def observe_approved_seeds() -> list[dict[str, Any]]:
    rows = approved_pfai_seed_examples()
    for r in rows:
        r.setdefault("outcome", "approved")
        r.setdefault("category", "owner_approved_seed")
        r.setdefault("verified", True)
    return rows


def observe_durable_learning(pipeline: Any) -> list[dict[str, Any]]:
    rows = collect_from_learning_pipeline(pipeline, statuses=("stored", "validated"))
    for r in rows:
        r.setdefault("outcome", "approved")
        r.setdefault("category", "durable_learning")
    return rows


def observe_coding_passes(coding_store: Any = None, *, limit: int = 200) -> list[dict[str, Any]]:
    """Pull coding tasks that passed tests when a store/API is available."""
    out: list[dict[str, Any]] = []
    if coding_store is None:
        return out
    lister = getattr(coding_store, "list_passed_exercises", None) or getattr(
        coding_store, "list_verified_solutions", None
    )
    if not callable(lister):
        return out
    try:
        items = list(lister(limit=limit) or [])
    except Exception:
        return out
    for i, item in enumerate(items):
        if isinstance(item, dict):
            prompt = str(item.get("prompt") or item.get("instruction") or item.get("exercise") or "")
            solution = str(item.get("solution") or item.get("response") or item.get("code") or "")
            sid = str(item.get("id") or item.get("exercise_id") or i)
        else:
            prompt = str(getattr(item, "prompt", "") or getattr(item, "instruction", ""))
            solution = str(getattr(item, "solution", "") or getattr(item, "code", ""))
            sid = str(getattr(item, "id", i))
        if not prompt or not solution:
            continue
        out.append(
            {
                "instruction": prompt,
                "response": solution,
                "source": "coding_passed",
                "source_id": sid,
                "outcome": "success",
                "category": "coding",
                "verified": True,
            }
        )
    return out


def observe_evaluation_lessons(eval_runner: Any = None) -> list[dict[str, Any]]:
    """Convert structured evaluation notes into learning candidates when available."""
    out: list[dict[str, Any]] = []
    if eval_runner is None:
        return out
    lessons = getattr(eval_runner, "learning_lessons", None)
    if not callable(lessons):
        return out
    try:
        for i, lesson in enumerate(lessons() or []):
            if isinstance(lesson, dict):
                instruction = str(lesson.get("instruction") or lesson.get("prompt") or "")
                response = str(lesson.get("response") or lesson.get("lesson") or "")
                sid = str(lesson.get("id") or i)
            else:
                continue
            if instruction and response:
                out.append(
                    {
                        "instruction": instruction,
                        "response": response,
                        "source": "evaluation",
                        "source_id": sid,
                        "outcome": "evaluated",
                        "category": "evaluation",
                        "verified": True,
                    }
                )
    except Exception:
        return out
    return out


def observe_owner_feedback(feedback_items: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(feedback_items or []):
        if not item.get("approved"):
            continue
        instruction = str(item.get("instruction") or item.get("question") or "")
        response = str(item.get("response") or item.get("correction") or "")
        if not instruction or not response:
            continue
        out.append(
            {
                "instruction": instruction,
                "response": response,
                "source": "owner_feedback",
                "source_id": str(item.get("id") or i),
                "outcome": "approved",
                "category": "owner_feedback",
                "verified": True,
            }
        )
    return out


def observe_tool_skill_outcomes(items: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(items or []):
        if not item.get("success"):
            continue
        instruction = str(item.get("instruction") or item.get("goal") or "")
        response = str(item.get("response") or item.get("result_summary") or "")
        # Never take raw tool payloads that may contain secrets
        if any(k in (item or {}) for k in ("secret", "token", "password", "otp")):
            continue
        if not instruction or not response:
            continue
        out.append(
            {
                "instruction": instruction,
                "response": response,
                "source": "tool_skill",
                "source_id": str(item.get("id") or i),
                "outcome": "success",
                "category": "tool_skill",
                "verified": True,
            }
        )
    return out


def observe_corrected_failures(items: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(items or []):
        if not item.get("corrected"):
            continue
        instruction = str(item.get("instruction") or "")
        response = str(item.get("corrected_response") or item.get("response") or "")
        if not instruction or not response:
            continue
        out.append(
            {
                "instruction": instruction,
                "response": response,
                "source": "corrected_failure",
                "source_id": str(item.get("id") or i),
                "outcome": "failed_then_fixed",
                "category": "correction",
                "verified": True,
            }
        )
    return out
