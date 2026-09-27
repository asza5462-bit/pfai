from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable

@dataclass(frozen=True)
class LearningTrack:
    name: str
    priority: int
    weight: float
    description: str

DEFAULT_TRACKS = (
    LearningTrack('software_engineering', 1, 0.45, 'Python, systems, algorithms, testing, debugging, security, architecture, performance'),
    LearningTrack('ai_engineering', 2, 0.35, 'ML, deep learning, transformers, inference, fine-tuning, evaluation, alignment and MLOps'),
    LearningTrack('reasoning_and_agents', 3, 0.12, 'planning, tool use, verification, retrieval and agent reliability'),
    LearningTrack('general_knowledge', 4, 0.08, 'general knowledge and domain adaptation'),
)

class LearningCurriculum:
    """Deterministic curriculum used by continuous learning to prioritize high-value training."""
    def __init__(self, tracks: Iterable[LearningTrack] = DEFAULT_TRACKS):
        tracks = tuple(sorted(tracks, key=lambda x: x.priority))
        if not tracks or abs(sum(t.weight for t in tracks) - 1.0) > 1e-6:
            raise ValueError('track weights must sum to 1')
        self.tracks = tracks

    def allocate(self, total: int) -> dict[str, int]:
        if total < 0: raise ValueError('total must be >= 0')
        raw = {t.name: total*t.weight for t in self.tracks}
        counts = {k:int(v) for k,v in raw.items()}
        remainder = total-sum(counts.values())
        for t in self.tracks[:remainder]: counts[t.name] += 1
        return counts

    def describe(self): return [asdict(t) for t in self.tracks]
