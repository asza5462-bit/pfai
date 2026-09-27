"""Educational memory bridge — stores only approved/useful learner facts in MemoryStore."""
from __future__ import annotations

from .command_memory import CommandMemoryService
from .memory import MemoryStore


class CodingAcademyMemory:
    KINDS = {
        "coding_goal",
        "coding_level",
        "coding_strength",
        "coding_weakness",
        "coding_error_pattern",
        "coding_project",
        "coding_preference",
        "coding_achievement",
    }

    def __init__(self, memory: MemoryStore | CommandMemoryService):
        self.memory = memory.memory if isinstance(memory, CommandMemoryService) else memory
        self.command_memory = memory if isinstance(memory, CommandMemoryService) else None

    def remember(self, kind: str, content: str, source: str = "coding_academy", confidence: float = 0.8) -> int:
        kind = kind if kind in self.KINDS else "coding_preference"
        # Dedup via search
        for hit in self.memory.search(content[:60], limit=5):
            if hit.get("kind") == kind and hit.get("content") == content:
                return int(hit["id"])
        return int(self.memory.add(kind, content, source, confidence))

    def relevant(self, query: str, limit: int = 8) -> list[dict]:
        hits = self.memory.search(query, limit=limit * 2)
        preferred = [h for h in hits if str(h.get("kind", "")).startswith("coding_")]
        return (preferred or hits)[:limit]

    def sync_from_profile(self, owner: str, profile: dict) -> list[int]:
        ids = []
        level = profile.get("display_level")
        if level:
            ids.append(self.remember("coding_level", f"{owner} coding level: {level}", source=owner))
        for g in profile.get("goals") or []:
            ids.append(self.remember("coding_goal", f"{owner} goal: {g}", source=owner))
        skills = profile.get("skills") or {}
        for sk, sc in skills.items():
            kind = "coding_strength" if float(sc) >= 0.7 else "coding_weakness"
            ids.append(self.remember(kind, f"{owner} skill {sk}={sc}", source=owner, confidence=float(sc)))
        for err, count in (profile.get("repeated_errors") or {}).items():
            if int(count) >= 2:
                ids.append(self.remember("coding_error_pattern", f"{owner} repeats error '{err}' x{count}", source=owner))
        return ids
