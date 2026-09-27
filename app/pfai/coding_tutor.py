"""Interactive Coding Tutor — progressive hints, no spoilers by default."""
from __future__ import annotations

from typing import Any

from .coding_curriculum import CurriculumEngine
from .coding_skill_profile import SkillProfileStore
from .code_execution_evaluator import SandboxedCodeEvaluator


class CodingTutor:
    def __init__(self, curriculum: CurriculumEngine | None = None, profiles: SkillProfileStore | None = None,
                 sandbox: SandboxedCodeEvaluator | None = None):
        self.curriculum = curriculum or CurriculumEngine()
        self.profiles = profiles or SkillProfileStore(curriculum=self.curriculum)
        self.sandbox = sandbox or SandboxedCodeEvaluator()
        self._hint_state: dict[str, int] = {}

    def start_path(self, owner: str, track_id: str, goal: str = "") -> dict:
        profile = self.profiles.get_profile(owner)
        path = self.curriculum.personalize_path(track_id, profile.get("skills") or {}, goal=goal)
        if path.get("ok"):
            goals = list(dict.fromkeys([*(profile.get("goals") or []), goal or track_id]))
            self.profiles.save_profile(owner, goals=goals, display_level=path.get("recommended_level", profile.get("display_level")))
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
            "lesson": {"id": lesson.get("id"), "title": lesson.get("title"), "level": lesson.get("level"), "skills": lesson.get("skills", []), "track_id": track_id},
        }

    def hint(self, owner: str, track_id: str, lesson_id: str) -> dict:
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        hints = (lesson.get("exercise") or {}).get("hints") or []
        key = f"{owner}:{track_id}:{lesson_id}"
        idx = self._hint_state.get(key, 0)
        if idx >= len(hints):
            return {"ok": True, "hint": None, "level": idx, "exhausted": True, "message": "No more hints. Try the exercise, then request solution explicitly."}
        hint = hints[idx]
        self._hint_state[key] = idx + 1
        return {"ok": True, "hint": hint, "level": idx + 1, "exhausted": False}

    def submit_exercise(self, owner: str, track_id: str, lesson_id: str, code: str) -> dict:
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        ex = lesson.get("exercise") or {}
        tests = ex.get("tests") or ""
        if not tests.strip():
            # Conceptual lesson — accept non-empty answer
            ok = bool((code or "").strip())
            if ok:
                self.profiles.complete_lesson(owner, f"{track_id}/{lesson_id}", {s: 0.05 for s in lesson.get("skills") or []})
            return {"ok": ok, "mode": "conceptual", "passed": ok, "message": "Conceptual submission recorded" if ok else "Empty answer"}
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
        }
        if result.passed:
            self.profiles.complete_lesson(owner, f"{track_id}/{lesson_id}", {s: 0.08 for s in lesson.get("skills") or []})
        else:
            self.profiles.record_error(owner, f"{track_id}/{lesson_id}:{result.reason[:80]}")
            payload["teaching"] = "Read the failing assertion/stderr. Ask for Hint before requesting the solution."
        return payload

    def solution(self, owner: str, track_id: str, lesson_id: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            return {"ok": False, "needs_confirmation": True, "message": "In Learning Mode, confirm you want the full solution."}
        lesson = self.curriculum.get_lesson(track_id, lesson_id)
        if not lesson:
            return {"ok": False, "error": "lesson not found"}
        return {"ok": True, "solution": (lesson.get("exercise") or {}).get("solution", ""), "lesson_id": lesson_id}

    def adaptive_next(self, owner: str, track_id: str) -> dict:
        profile = self.profiles.get_profile(owner)
        nxt = self.curriculum.next_lesson(track_id, profile.get("completed_lessons") or [], level=None)
        # If weak skills dominate, prefer matching lessons
        path = self.curriculum.personalize_path(track_id, profile.get("skills") or {})
        preferred = None
        done = set(profile.get("completed_lessons") or [])
        for item in path.get("path") or []:
            key = f"{track_id}/{item['id']}"
            # completed_lessons stores track/lesson keys from complete_lesson
            if key not in done and item["id"] not in done:
                preferred = item
                break
        return {"ok": True, "next": preferred or ( {"id": nxt.get("id"), "title": nxt.get("title"), "level": nxt.get("level")} if nxt else None), "profile_level": profile.get("display_level")}
