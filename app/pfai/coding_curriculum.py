"""Extensible Coding Curriculum Engine — tracks/lessons loaded from JSON, not hardcoded."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CurriculumEngine:
    def __init__(self, root: str = "configs/coding"):
        self.root = Path(root)
        self._curriculum = self._load(self.root / "curriculum.json")
        self._assessments = self._load(self.root / "assessments.json")
        self._projects = self._load(self.root / "projects" / "catalog.json")
        self._knowledge = self._load(self.root / "knowledge" / "base.json")

    @staticmethod
    def _load(path: Path) -> dict:
        if not path.exists():
            return {"version": 0, "tracks": [], "assessments": [], "projects": [], "entries": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def reload(self) -> None:
        self.__init__(str(self.root))

    def list_tracks(self) -> list[dict]:
        out = []
        for t in self._curriculum.get("tracks", []):
            out.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "levels": t.get("levels", []),
                "skills": t.get("skills", []),
                "lesson_count": len(t.get("lessons", [])),
            })
        return out

    def get_track(self, track_id: str) -> dict | None:
        for t in self._curriculum.get("tracks", []):
            if t.get("id") == track_id:
                return t
        return None

    def get_lesson(self, track_id: str, lesson_id: str) -> dict | None:
        track = self.get_track(track_id)
        if not track:
            return None
        for lesson in track.get("lessons", []):
            if lesson.get("id") == lesson_id:
                return {**lesson, "track_id": track_id, "track_title": track.get("title")}
        return None

    def lessons_for_level(self, track_id: str, level: str) -> list[dict]:
        track = self.get_track(track_id) or {}
        return [x for x in track.get("lessons", []) if x.get("level") == level]

    def next_lesson(self, track_id: str, completed_ids: list[str], level: str | None = None) -> dict | None:
        track = self.get_track(track_id)
        if not track:
            return None
        done = set(completed_ids or [])
        for lesson in track.get("lessons", []):
            if level and lesson.get("level") != level:
                continue
            if lesson.get("id") not in done:
                return {**lesson, "track_id": track_id}
        return None

    def assessments(self) -> list[dict]:
        return list(self._assessments.get("assessments", []))

    def projects(self, level: str | None = None) -> list[dict]:
        items = list(self._projects.get("projects", []))
        if level:
            items = [p for p in items if p.get("level") == level]
        return items

    def get_project(self, project_id: str) -> dict | None:
        for p in self.projects():
            if p.get("id") == project_id:
                return p
        return None

    def knowledge_search(self, query: str, limit: int = 8) -> list[dict]:
        q = (query or "").lower()
        hits = []
        for e in self._knowledge.get("entries", []):
            blob = " ".join([
                str(e.get("title", "")),
                str(e.get("content", "")),
                " ".join(e.get("tags") or []),
                str(e.get("category", "")),
            ]).lower()
            if not q or q in blob:
                hits.append(e)
        return hits[: max(1, int(limit))]

    def personalize_path(self, track_id: str, skill_scores: dict[str, float], goal: str = "") -> dict[str, Any]:
        track = self.get_track(track_id)
        if not track:
            return {"ok": False, "error": f"unknown track: {track_id}"}
        weak = sorted(((k, v) for k, v in (skill_scores or {}).items()), key=lambda x: x[1])
        weak_skills = {k for k, v in weak if v < 0.6}
        ordered = []
        for lesson in track.get("lessons", []):
            skills = set(lesson.get("skills") or [])
            priority = 0 if skills & weak_skills else 1
            ordered.append((priority, lesson))
        ordered.sort(key=lambda x: (x[0], x[1].get("level", ""), x[1].get("id", "")))
        path = [x[1] for x in ordered]
        level = "beginner"
        avg = sum(skill_scores.values()) / max(1, len(skill_scores)) if skill_scores else 0.4
        if avg >= 0.75:
            level = "advanced"
        elif avg >= 0.55:
            level = "intermediate"
        return {
            "ok": True,
            "track_id": track_id,
            "goal": goal,
            "recommended_level": level,
            "focus_skills": list(weak_skills)[:8],
            "path": [{"id": l.get("id"), "title": l.get("title"), "level": l.get("level"), "skills": l.get("skills", [])} for l in path],
        }
