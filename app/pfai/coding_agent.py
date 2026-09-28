"""Coding Intelligence Agent — Learning Mode vs Engineering Mode.

Uses existing model providers (Anthropic optional, openai_compatible/local, or Mock).
Never auto fine-tunes production weights.
"""
from __future__ import annotations

import os
import re
from typing import Any

from .coding_curriculum import CurriculumEngine
from .coding_skill_profile import SkillProfileStore
from .coding_academy_memory import CodingAcademyMemory
from .coding_tutor import CodingTutor
from .coding_reviewer import CodingReviewer
from .coding_debugger import DebuggingTrainer
from .coding_quality import CodingQualityGate
from .code_execution_evaluator import SandboxedCodeEvaluator
from .model_anthropic import AnthropicProvider
from .model_mock import MockCommandProvider
from .logging_setup import setup_logging

log = setup_logging("pfai.coding_agent")


class CodingAgent:
    def __init__(
        self,
        model=None,
        curriculum: CurriculumEngine | None = None,
        profiles: SkillProfileStore | None = None,
        academy_memory: CodingAcademyMemory | None = None,
    ):
        self.model = model
        self.mock = MockCommandProvider()
        self.curriculum = curriculum or CurriculumEngine()
        self.profiles = profiles or SkillProfileStore(curriculum=self.curriculum)
        self.memory = academy_memory
        self.sandbox = SandboxedCodeEvaluator()
        self.tutor = CodingTutor(self.curriculum, self.profiles, self.sandbox)
        self.reviewer = CodingReviewer()
        self.debugger = DebuggingTrainer(self.profiles, self.sandbox)
        self.quality = CodingQualityGate()

    def provider_name(self) -> str:
        if self._model_ready():
            if isinstance(self.model, AnthropicProvider):
                return f"anthropic:{getattr(self.model, 'model', 'claude')}"
            return type(self.model).__name__
        return "mock-command"

    def _model_ready(self) -> bool:
        if self.model is None:
            return False
        if isinstance(self.model, AnthropicProvider):
            return bool(os.environ.get(getattr(self.model, "api_key_env", "ANTHROPIC_API_KEY")))
        # Echo/OpenAI-compatible/other: treat as ready if generate exists
        return hasattr(self.model, "generate") and type(self.model).__name__ != "EchoProvider"

    def handle(self, message: str, *, owner: str, mode: str | None = None, code: str = "", language: str = "python") -> dict:
        timeline = [{"status": "thinking", "detail": "Coding agent loading learner profile"}]
        profile = self.profiles.get_profile(owner)
        mode = mode or profile.get("mode") or "learning"
        if mode not in {"learning", "engineering"}:
            mode = "learning"
        timeline.append({"status": "planning", "detail": f"mode={mode} provider={self.provider_name()}"})
        intent = self._detect_intent(message, code=code)
        timeline.append({"status": "planning", "detail": f"intent={intent['name']}"})
        try:
            result = self._dispatch(intent, message=message, owner=owner, mode=mode, code=code, language=language, timeline=timeline)
        except Exception as exc:
            log.exception("coding agent failure")
            timeline.append({"status": "failed", "detail": str(exc)})
            return {"ok": False, "error": str(exc), "timeline": timeline, "mode": mode, "provider": self.provider_name()}
        if "timeline" not in result:
            result["timeline"] = timeline
        else:
            result["timeline"] = timeline + list(result.get("timeline") or [])
        result.setdefault("mode", mode)
        result.setdefault("provider", self.provider_name())
        result.setdefault("intent", intent["name"])
        if result.get("ok", True):
            result["timeline"].append({"status": "completed", "detail": "Coding turn finished"})
        result["learning_context"] = build_learning_context(result)
        return result

    def _detect_intent(self, message: str, code: str = "") -> dict:
        text = (message or "").strip()
        low = text.lower()
        if re.search(r"اختبر مستواي|skill assessment|test my level|assess my skills", text, re.I):
            return {"name": "assess"}
        if re.search(r"علمني|teach me|learn|أريد تعلم|become|full stack|مبتدئ", text, re.I):
            track = self._guess_track(low, text)
            return {"name": "teach", "track_id": track, "goal": text}
        if re.search(r"أعطني تمرين|give me (an )?exercise|تمرين", text, re.I):
            return {"name": "exercise", "track_id": self._guess_track(low, text)}
        if re.search(r"تلميح|hint|لا تعطيني الحل", text, re.I):
            return {"name": "hint"}
        if re.search(r"راجع هذا الكود|code review|review (this )?code|راجع architecture", text, re.I) or code.strip():
            if re.search(r"architecture|معمار", text, re.I):
                return {"name": "review_architecture"}
            return {"name": "review"}
        if re.search(r"اشرح.*خطأ|debug|لماذا.*بطيء|why.*slow|debugging", text, re.I):
            return {"name": "debug"}
        if re.search(r"مشروع|project|ابنِ لي مشروع", text, re.I):
            return {"name": "project"}
        if re.search(r"engineering mode|وضع هندسي", text, re.I):
            return {"name": "set_mode", "mode": "engineering"}
        if re.search(r"learning mode|وضع تعليم", text, re.I):
            return {"name": "set_mode", "mode": "learning"}
        if re.search(r"run|نفذ|execute|sandbox", text, re.I) and code.strip():
            return {"name": "run"}
        return {"name": "coach"}

    def _guess_track(self, low: str, text: str) -> str:
        mapping = [
            (("python", "بايثون"), "python"),
            (("javascript", "js", "جافاسكريبت"), "javascript"),
            (("algorithm", "خوارزم", "data structure"), "algorithms"),
            (("git",), "git"),
            (("api", "rest"), "apis"),
            (("rag", "llm", "ذكاء", "ai"), "ai-engineering"),
            (("docker", "devops"), "docker-devops"),
            (("security", "أمن"), "security"),
        ]
        for keys, track in mapping:
            if any(k in low or k in text for k in keys):
                return track
        return "python"

    def _dispatch(self, intent, *, message, owner, mode, code, language, timeline) -> dict:
        name = intent["name"]
        if name == "set_mode":
            profile = self.profiles.set_mode(owner, intent.get("mode", "learning"))
            return {"ok": True, "reply": f"Mode set to {profile['mode']}", "profile": profile}
        if name == "assess":
            timeline.append({"status": "teaching", "detail": "Preparing skill assessment"})
            return {"ok": True, "reply": "Skill assessment ready. Submit answers to /coding/assessment/submit.", "assessment": self.profiles.start_assessment()}
        if name == "teach":
            timeline.append({"status": "teaching", "detail": f"Building path for {intent.get('track_id')}"})
            path = self.tutor.start_path(owner, intent.get("track_id", "python"), goal=intent.get("goal", message))
            if self.memory:
                self.memory.remember("coding_goal", f"{owner}: {intent.get('goal', message)}", source=owner)
            return {"ok": True, "reply": self._path_reply(path, mode), "path": path}
        if name == "exercise":
            track_id = intent.get("track_id", "python")
            nxt = self.tutor.adaptive_next(owner, track_id)
            lesson_id = (nxt.get("next") or {}).get("id")
            if not lesson_id:
                return {"ok": True, "reply": "No remaining lessons in this track. Try another track or a project."}
            timeline.append({"status": "teaching", "detail": f"Lesson {lesson_id}"})
            lesson = self.tutor.lesson(track_id, lesson_id, reveal_solution=False)
            title = (lesson.get("lesson") or {}).get("title") or lesson_id
            prompt = ((lesson.get("exercise") or {}).get("prompt") or "")[:280]
            reply = (
                f"Exercise ready: {title} ({track_id}/{lesson_id}).\n"
                f"{prompt}\n"
                "Use the chat exercise card to submit code, or ask for a hint. "
                "Passing sandbox work may become a learning candidate — training never auto-starts from chat."
            )
            return {"ok": True, "reply": reply, "lesson": lesson, "next": nxt, "track_id": track_id}
        if name == "hint":
            # Expect track/lesson encoded in message like track:lesson or use python first incomplete
            track_id, lesson_id = self._parse_lesson_ref(message, owner)
            timeline.append({"status": "teaching", "detail": "Providing progressive hint"})
            return {"ok": True, "reply": "Hint generated.", "hint": self.tutor.hint(owner, track_id, lesson_id)}
        if name == "review":
            timeline.append({"status": "reviewing", "detail": "Static/security/maintainability review"})
            review = self.reviewer.review(code or _extract_code(message), language=language)
            return {"ok": True, "reply": self._review_reply(review, mode), "review": review}
        if name == "review_architecture":
            timeline.append({"status": "reviewing", "detail": "Architecture coaching"})
            kb = self.curriculum.knowledge_search("architecture layers", limit=3)
            return {"ok": True, "reply": "Architecture review (knowledge-backed).", "knowledge": kb, "guidance": "Separate API, domain, and persistence; keep secrets out of code; add tests at boundaries."}
        if name == "debug":
            timeline.append({"status": "teaching", "detail": "Debugging trainer session"})
            sess = self.debugger.start(owner, code or _extract_code(message), test_code="", buggy_description=message)
            return {"ok": True, "reply": sess.get("question"), "debug": sess}
        if name == "project":
            level = self.profiles.get_profile(owner).get("display_level", "beginner")
            projects = self.curriculum.projects(level=level) or self.curriculum.projects()
            return {"ok": True, "reply": f"Found {len(projects)} projects for level={level}.", "projects": projects}
        if name == "run":
            timeline.append({"status": "running_test", "detail": "Sandbox execution"})
            q = self.quality.evaluate_answer(code or _extract_code(message), test_code="", language=language)
            return {"ok": True, "reply": q.get("message"), "quality": q}
        # coach default
        mem = self.memory.relevant(message, limit=5) if self.memory else []
        reply = self._coach_reply(message, mode, mem)
        return {"ok": True, "reply": reply, "memory_hits": mem}

    def _path_reply(self, path: dict, mode: str) -> str:
        if not path.get("ok"):
            return path.get("error", "Could not build path")
        focus = ", ".join(path.get("focus_skills") or []) or "general foundations"
        return (
            f"Personalized {path.get('track_id')} path ready (level={path.get('recommended_level')}). "
            f"Focus: {focus}. Mode={mode}. I will teach with hints before solutions."
        )

    def _review_reply(self, review: dict, mode: str) -> str:
        findings = review.get("findings") or []
        high = sum(1 for f in findings if f.get("severity") == "high")
        return f"Code review complete: {len(findings)} notes ({high} high). Mode={mode}. " + (
            "I explain issues first; ask for a patch explicitly in Engineering Mode." if mode == "learning"
            else "Say 'generate patch' if you want an approved fix proposal."
        )

    def _coach_reply(self, message: str, mode: str, mem: list) -> str:
        if self._model_ready():
            try:
                prompt = (
                    f"You are PFAI Coding {'Teacher' if mode=='learning' else 'Engineer'}. "
                    f"Be practical. Mode={mode}. Do not invent passing tests. User: {message}\n"
                    f"Memory: {mem[:3]}"
                )
                return self.model.generate(prompt)
            except Exception as exc:
                log.warning("model coach failed: %s", exc)
        return self.mock.compose_reply(message, [], str(mem), language="ar" if re.search(r"[\u0600-\u06FF]", message) else "en")

    def _parse_lesson_ref(self, message: str, owner: str) -> tuple[str, str]:
        m = re.search(r"([a-z0-9\-]+)/([a-z0-9\-]+)", message or "")
        if m:
            return m.group(1), m.group(2)
        # fallback first incomplete python lesson
        nxt = self.tutor.adaptive_next(owner, "python")
        lesson = nxt.get("next") or {}
        return "python", lesson.get("id") or "py-intro"


def _extract_code(message: str) -> str:
    if "```" not in (message or ""):
        return ""
    parts = message.split("```")
    if len(parts) >= 3:
        block = parts[1]
        lines = block.splitlines()
        if lines and re.match(r"^[a-zA-Z]+$", lines[0].strip()):
            lines = lines[1:]
        return "\n".join(lines).strip()
    return ""


def build_learning_context(coding: dict[str, Any] | None) -> dict[str, Any]:
    """Compact education bridge for Command Chat UI (never starts training)."""
    coding = coding or {}
    path = coding.get("path") or {}
    lesson_wrap = coding.get("lesson") or {}
    lesson = lesson_wrap.get("lesson") if isinstance(lesson_wrap.get("lesson"), dict) else {}
    exercise = lesson_wrap.get("exercise") if isinstance(lesson_wrap.get("exercise"), dict) else {}
    nxt = coding.get("next") or {}
    track_id = (
        coding.get("track_id")
        or path.get("track_id")
        or lesson.get("track_id")
        or None
    )
    return {
        "mode": coding.get("mode"),
        "intent": coding.get("intent"),
        "track_id": track_id,
        "lesson_id": lesson.get("id"),
        "lesson_title": lesson.get("title"),
        "has_exercise": bool(exercise),
        "hints_available": exercise.get("hints_available"),
        "path_len": len(path.get("path") or []) or None,
        "assessment_count": (coding.get("assessment") or {}).get("count"),
        "project_count": len(coding.get("projects") or []) or None,
        "next_lesson_id": (nxt.get("next") or {}).get("id") if isinstance(nxt, dict) else None,
        "training_auto": False,
        "can_start_training_from_chat": False,
        "note": "Education linked; model training never auto-starts from chat",
    }
