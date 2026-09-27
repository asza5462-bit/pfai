"""Learner skill profile, assessments, and progress tracking."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .coding_curriculum import CurriculumEngine


class SkillProfileStore:
    def __init__(self, path: str = "data/coding_academy/profiles.sqlite3", curriculum: CurriculumEngine | None = None):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(p, check_same_thread=False)
        self._lock = threading.RLock()
        self.curriculum = curriculum or CurriculumEngine()
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                  owner TEXT PRIMARY KEY,
                  display_level TEXT,
                  goals_json TEXT,
                  skills_json TEXT,
                  completed_lessons_json TEXT,
                  repeated_errors_json TEXT,
                  projects_json TEXT,
                  mode TEXT,
                  updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS assessment_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  owner TEXT,
                  answers_json TEXT,
                  scores_json TEXT,
                  created_at REAL
                );
                CREATE TABLE IF NOT EXISTS progress_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  owner TEXT,
                  kind TEXT,
                  payload_json TEXT,
                  created_at REAL
                );
                """
            )
            self.db.commit()

    def get_profile(self, owner: str) -> dict:
        with self._lock:
            row = self.db.execute("SELECT owner,display_level,goals_json,skills_json,completed_lessons_json,repeated_errors_json,projects_json,mode,updated_at FROM profiles WHERE owner=?", (owner,)).fetchone()
        if not row:
            return {
                "owner": owner,
                "display_level": "beginner",
                "goals": [],
                "skills": {},
                "completed_lessons": [],
                "repeated_errors": {},
                "projects": [],
                "mode": "learning",
                "updated_at": None,
            }
        return {
            "owner": row[0],
            "display_level": row[1] or "beginner",
            "goals": json.loads(row[2] or "[]"),
            "skills": json.loads(row[3] or "{}"),
            "completed_lessons": json.loads(row[4] or "[]"),
            "repeated_errors": json.loads(row[5] or "{}"),
            "projects": json.loads(row[6] or "[]"),
            "mode": row[7] or "learning",
            "updated_at": row[8],
        }

    def save_profile(self, owner: str, **fields) -> dict:
        cur = self.get_profile(owner)
        for k, v in fields.items():
            if k in {"display_level", "goals", "skills", "completed_lessons", "repeated_errors", "projects", "mode"}:
                cur[k] = v
        with self._lock:
            self.db.execute(
                """
                INSERT INTO profiles(owner,display_level,goals_json,skills_json,completed_lessons_json,repeated_errors_json,projects_json,mode,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(owner) DO UPDATE SET
                  display_level=excluded.display_level,
                  goals_json=excluded.goals_json,
                  skills_json=excluded.skills_json,
                  completed_lessons_json=excluded.completed_lessons_json,
                  repeated_errors_json=excluded.repeated_errors_json,
                  projects_json=excluded.projects_json,
                  mode=excluded.mode,
                  updated_at=excluded.updated_at
                """,
                (
                    owner,
                    cur["display_level"],
                    json.dumps(cur["goals"], ensure_ascii=False),
                    json.dumps(cur["skills"], ensure_ascii=False),
                    json.dumps(cur["completed_lessons"], ensure_ascii=False),
                    json.dumps(cur["repeated_errors"], ensure_ascii=False),
                    json.dumps(cur["projects"], ensure_ascii=False),
                    cur["mode"],
                    time.time(),
                ),
            )
            self.db.commit()
        return self.get_profile(owner)

    def set_mode(self, owner: str, mode: str) -> dict:
        mode = "engineering" if mode == "engineering" else "learning"
        return self.save_profile(owner, mode=mode)

    def record_error(self, owner: str, error_key: str) -> dict:
        p = self.get_profile(owner)
        errs = dict(p.get("repeated_errors") or {})
        errs[error_key] = int(errs.get(error_key, 0)) + 1
        return self.save_profile(owner, repeated_errors=errs)

    def complete_lesson(self, owner: str, lesson_key: str, skill_deltas: dict[str, float] | None = None) -> dict:
        p = self.get_profile(owner)
        done = list(dict.fromkeys([*(p.get("completed_lessons") or []), lesson_key]))
        skills = dict(p.get("skills") or {})
        for sk, delta in (skill_deltas or {}).items():
            skills[sk] = round(min(1.0, max(0.0, float(skills.get(sk, 0.4)) + float(delta))), 3)
        level = _level_from_skills(skills)
        with self._lock:
            self.db.execute(
                "INSERT INTO progress_events(owner,kind,payload_json,created_at) VALUES(?,?,?,?)",
                (owner, "lesson_complete", json.dumps({"lesson": lesson_key}, ensure_ascii=False), time.time()),
            )
            self.db.commit()
        return self.save_profile(owner, completed_lessons=done, skills=skills, display_level=level)

    def start_assessment(self) -> dict:
        items = self.curriculum.assessments()
        public = [{"id": x["id"], "skill": x["skill"], "prompt": x["prompt"], "choices": x["choices"], "level": x.get("level")} for x in items]
        return {"items": public, "count": len(public)}

    def grade_assessment(self, owner: str, answers: dict[str, int]) -> dict:
        items = {x["id"]: x for x in self.curriculum.assessments()}
        scores: dict[str, list[float]] = {}
        detail = []
        for qid, choice in (answers or {}).items():
            q = items.get(qid)
            if not q:
                continue
            ok = int(choice) == int(q.get("answer", -1))
            skill = q.get("skill", "general")
            scores.setdefault(skill, []).append(1.0 if ok else 0.0)
            detail.append({"id": qid, "skill": skill, "correct": ok})
        skill_scores = {k: round(sum(v) / len(v), 3) for k, v in scores.items() if v}
        strong = sorted([k for k, v in skill_scores.items() if v >= 0.7])
        weak = sorted([k for k, v in skill_scores.items() if v < 0.6])
        level = _level_from_skills(skill_scores)
        with self._lock:
            self.db.execute(
                "INSERT INTO assessment_runs(owner,answers_json,scores_json,created_at) VALUES(?,?,?,?)",
                (owner, json.dumps(answers, ensure_ascii=False), json.dumps(skill_scores, ensure_ascii=False), time.time()),
            )
            self.db.commit()
        profile = self.save_profile(owner, skills=skill_scores, display_level=level)
        return {
            "ok": True,
            "skill_scores": skill_scores,
            "strong_skills": strong,
            "weak_skills": weak,
            "level": level,
            "detail": detail,
            "profile": profile,
        }

    def progress(self, owner: str, limit: int = 30) -> dict:
        p = self.get_profile(owner)
        with self._lock:
            rows = self.db.execute(
                "SELECT kind,payload_json,created_at FROM progress_events WHERE owner=? ORDER BY id DESC LIMIT ?",
                (owner, int(limit)),
            ).fetchall()
        events = []
        for kind, payload, ts in rows:
            try:
                payload_obj = json.loads(payload or "{}")
            except json.JSONDecodeError:
                payload_obj = {}
            events.append({"kind": kind, "payload": payload_obj, "created_at": ts})
        return {"profile": p, "events": events}


def _level_from_skills(skills: dict[str, float]) -> str:
    if not skills:
        return "beginner"
    avg = sum(skills.values()) / len(skills)
    if avg >= 0.75:
        return "advanced"
    if avg >= 0.55:
        return "intermediate"
    return "beginner"
