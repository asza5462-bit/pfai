"""Self-learning via reflection, not silent weight updates.

After each answer, ask the connected model to critique itself and extract durable,
self-contained lessons worth remembering. Lessons are written to MemoryStore, so the
next retrieval (via Agent/RAG) is grounded in what was already learned. This is how
PFAI gets measurably better across a conversation and across sessions without any
unreviewed change to model weights — consistent with the project's standing rule
that self-improvement stays evaluation/human gated.

Fails closed by design: any model or parsing error just means "nothing learned this
turn". Reflection can never raise, never block, and never corrupt the primary answer.
"""
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

_PROMPT = (
    "You just answered a question. Reflect briefly and return ONLY JSON, no prose, "
    "no markdown fences.\n"
    'Schema: {{"critique": "<=1 sentence on what could be better>", '
    '"lessons": ["<durable, self-contained fact or correction worth remembering>", ...]}}\n'
    "Rules: at most {max_lessons} lessons. Each lesson must stand alone (no pronouns "
    'like "it"/"this" referring back to the question). If nothing durable was '
    "learned, return an empty lessons list.\n\n"
    "Question: {question}\n"
    "Answer given: {answer}\n"
)


class SelfReflectionEngine:
    def __init__(self, model, memory, max_lessons: int = 3, confidence: float = 0.5):
        if max_lessons < 0:
            raise ValueError("max_lessons must not be negative")
        self.model = model
        self.memory = memory
        self.max_lessons = int(max_lessons)
        self.confidence = float(confidence)

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None

    def reflect(self, question: str, answer: str) -> Dict[str, Any]:
        if self.max_lessons == 0 or not str(answer).strip():
            return {"stored": 0, "critique": "", "lessons": []}
        try:
            raw = self.model.generate(
                _PROMPT.format(question=question, answer=answer, max_lessons=self.max_lessons)
            )
        except Exception as exc:
            return {"stored": 0, "critique": "", "lessons": [],
                    "error": f"{type(exc).__name__}: reflection skipped"}

        parsed = self._extract_json(raw) or {}
        lessons: List[str] = [
            str(x).strip() for x in parsed.get("lessons", []) if str(x).strip()
        ][: self.max_lessons]
        critique = str(parsed.get("critique", "")).strip()

        stored = 0
        for lesson in lessons:
            try:
                self.memory.add("lesson", lesson, source="self_reflection", confidence=self.confidence)
                stored += 1
            except Exception:
                continue
        return {"stored": stored, "critique": critique, "lessons": lessons}
