"""Interactive Coding Tutor — progressive, diagnostics-aware, no spoilers by default."""
from __future__ import annotations

import re
from typing import Any

from .coding_curriculum import CurriculumEngine
from .coding_skill_profile import SkillProfileStore
from .code_execution_evaluator import SandboxedCodeEvaluator


class CodingTutor:
    def __init__(
        self,
        curriculum: CurriculumEngine | None = None,
        profiles: SkillProfileStore | None = None,
        sandbox: SandboxedCodeEvaluator | None = None,
    ):
        self.curriculum = curriculum or CurriculumEngine()
        self.profiles = profiles or SkillProfileStore(curriculum=self.curriculum)
        self.sandbox = sandbox or SandboxedCodeEvaluator()
        self._hint_state: dict[str, int] = {}

    def start_path(self, owner: str, track_id: str, goal: str = "") -> dict:
        profile = self.profiles.get_profile(owner)
        path = self.curriculum.personalize_path(track_id, profile.get("skills") or {}, goal=goal)
        if path.get("ok"):
            goals = list(dict.fromkeys([*(profile.get("goals") or []), goal or track_id]))
            self.profiles.save_profile(
                owner,
                goals=goals,
                display_level=path.get("recommended_level", profile.get("display_level")),
            )
        return path

    def lesson(self, track_id: str, lesson_id: str, *, reveal_solution: bool = False) -> dict:
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        exercise = dict(lesson.get("exercise") or {})
        if not reveal_solution:
            exercise = {k: v for k, v in exercise.items() if k != "solution"}
            exercise["hints_available"] = len((lesson.get("exercise") or {}).get("hints") or [])
            exercise.pop("hints", None)
        return {
            "ok": True,
            "concept": lesson.get("concept"),
            "example": lesson.get("example"),
            "explanation": lesson.get("concept"),
            "exercise": exercise,
            "lesson": {
                "id": lesson.get("id"),
                "title": lesson.get("title"),
                "level": lesson.get("level"),
                "skills": lesson.get("skills", []),
                "track_id": track_id,
            },
        }

    def hint(
        self,
        owner: str,
        track_id: str,
        lesson_id: str,
        *,
        code: str = "",
        stderr: str = "",
    ) -> dict:
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        hints = list((lesson.get("exercise") or {}).get("hints") or [])
        # Soften last hint if it looks like a full solution dump
        if hints:
            last = hints[-1]
            if re.search(r"^\s*def\s+\w+\s*\(|return\s+\d+\s*\+\s*\d+", last or ""):
                hints[-1] = (
                    "Focus on the function contract and return the exact expected value; "
                    "re-read the failing assertion before asking for the full solution."
                )
        key = f"{owner}:{track_id}:{lesson_id}"
        idx = self._hint_state.get(key, 0)
        diagnostic = self._diagnostic_hint(code or "", stderr or "", lesson)
        if idx >= len(hints):
            msg = "No more curriculum hints. Use the diagnostic tip, retry, then request solution explicitly."
            return {
                "ok": True,
                "hint": diagnostic,
                "level": idx,
                "exhausted": True,
                "diagnostic": diagnostic,
                "message": msg,
            }
        hint = hints[idx]
        self._hint_state[key] = idx + 1
        combined = hint
        if diagnostic and idx == 0:
            combined = f"{hint}\nDiagnostic: {diagnostic}"
        elif diagnostic and idx > 0:
            combined = f"{hint} ({diagnostic})"
        return {
            "ok": True,
            "hint": combined,
            "level": idx + 1,
            "exhausted": False,
            "diagnostic": diagnostic,
            "curriculum_hint": hint,
        }

    def _diagnostic_hint(self, code: str, stderr: str, lesson: dict) -> str:
        text = f"{stderr}\n{code}".lower()
        tips = []
        if "assertionerror" in text or "assert" in text:
            tips.append("Compare your return value with the assertion's expected value exactly.")
        if "nameerror" in text:
            tips.append("A name is undefined — check spelling and that you defined the function.")
        if "typeerror" in text:
            tips.append("Argument types/arity mismatch — match the function signature in the prompt.")
        if "indentationerror" in text or "syntaxerror" in text:
            tips.append("Fix syntax/indentation first; Python blocks must be consistently indented.")
        if "timed out" in text or "timeout" in text:
            tips.append("Likely infinite loop — ensure the loop terminates.")
        if "pass" in (code or "") and "return" not in (code or ""):
            tips.append("Your stub still uses pass — return a real value.")
        if not tips and (lesson.get("exercise") or {}).get("prompt"):
            tips.append("Re-state the prompt in one sentence, then implement only that contract.")
        return tips[0] if tips else ""

    def submit_exercise(self, owner: str, track_id: str, lesson_id: str, code: str) -> dict:
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        ex = lesson.get("exercise") or {}
        tests = ex.get("tests") or ""
        if not tests.strip():
            answer = (code or "").strip()
            ok = len(answer) >= 3
            teaching = None
            if ok:
                # Light conceptual quality: must not be empty/placeholder
                if answer.lower() in {"pass", "todo", "ok", "..."}:
                    ok = False
                    teaching = "Give a precise conceptual answer, not a placeholder."
                else:
                    self.profiles.complete_lesson(
                        owner,
                        f"{track_id}/{lesson_id}",
                        {s: 0.05 for s in lesson.get("skills") or []},
                    )
            return {
                "ok": ok,
                "mode": "conceptual",
                "passed": ok,
                "message": "Conceptual submission recorded" if ok else (teaching or "Empty/weak answer"),
                "teaching": teaching,
                "track_id": track_id,
                "lesson_id": lesson_id,
            }
        result = self.sandbox.evaluate(code or "", tests)
        payload = {
            "ok": True,
            "mode": "sandbox",
            "passed": result.passed,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "reason": result.reason,
            "timed_out": result.timed_out,
            "static_passed": result.static_passed,
            "score": result.score,
            "track_id": track_id,
            "lesson_id": lesson_id,
        }
        if result.passed:
            self.profiles.complete_lesson(
                owner,
                f"{track_id}/{lesson_id}",
                {s: 0.08 for s in lesson.get("skills") or []},
            )
            payload["teaching"] = "Passed. Next: ask for the next lesson or a harder project."
            # reset hints for this lesson on success
            self._hint_state.pop(f"{owner}:{track_id}:{lesson_id}", None)
        else:
            self.profiles.record_error(owner, f"{track_id}/{lesson_id}:{result.reason[:80]}")
            diag = self._diagnostic_hint(code or "", result.stderr or result.reason or "", lesson)
            payload["teaching"] = (
                f"Failed. {diag} Ask for a hint (progressive) before requesting the full solution."
            )
            payload["diagnostic"] = diag
        return payload

    def solution(self, owner: str, track_id: str, lesson_id: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            return {
                "ok": False,
                "needs_confirmation": True,
                "message": "In Learning Mode, confirm you want the full solution.",
            }
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        return {
            "ok": True,
            "solution": (lesson.get("exercise") or {}).get("solution", ""),
            "lesson_id": lesson_id,
            "track_id": track_id,
        }

    def adaptive_next(self, owner: str, track_id: str) -> dict:
        profile = self.profiles.get_profile(owner)
        nxt = self.curriculum.next_lesson(track_id, profile.get("completed_lessons") or [], level=None)
        path = self.curriculum.personalize_path(track_id, profile.get("skills") or {})
        preferred = None
        done = set(profile.get("completed_lessons") or [])
        for item in path.get("path") or []:
            key = f"{track_id}/{item['id']}"
            if key not in done and item["id"] not in done:
                preferred = item
                break
        return {
            "ok": True,
            "next": preferred
            or (
                {"id": nxt.get("id"), "title": nxt.get("title"), "level": nxt.get("level")}
                if nxt
                else None
            ),
            "profile_level": profile.get("display_level"),
        }
