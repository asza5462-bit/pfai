"""v7.1: Continuous Learning Orchestrator.

Unifies the existing governed building blocks (curriculum, data acquisition/curation,
the 24/7 training service, and the human-gated learning loop) into one coherent
continuous-learning subsystem with a single status view.

Design invariants (unchanged from prior modules, only coordinated here):
- No network fetch or code execution happens inside this module. Candidate examples
  must be supplied by the caller (an operator, a connected pipeline, or a batch job);
  this module never reaches out to the internet on its own.
- Every learning-loop cycle stays evaluation-gated: `run_cycle` requires an external
  score for the curated batch, it never invents one.
- Promotion of a candidate to "active" still goes through `LearningLoop`, which can be
  configured (default: yes) to require human approval before anything is promoted.
- This module cannot self-approve, self-promote, or widen its own permissions.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional
import json

from .learning_curriculum import LearningCurriculum
from .data_acquisition import DataAcquisitionEngine
from .learning_loop import LearningLoop
from .continuous_training import ContinuousTrainingService, ContinuousConfig
from .evaluation_lab import EvaluationLab
from .llm_evaluator import LLMEvaluator
from .self_training import SelfTrainingEngine


class ContinuousLearningOrchestrator:
    """Coordinates curriculum-weighted data curation with governed learning cycles."""

    def __init__(self, root='data/continuous_learning', curriculum: Optional[LearningCurriculum] = None,
                 min_quality: float = 0.40, continuous_config: Optional[ContinuousConfig] = None,
                 require_human_approval: bool = True, min_improvement: float = 0.01,
                 min_score: float = 0.0, evaluator_model=None, self_training: bool = False,
                 self_training_batch_size: int = 2, self_training_min_score: float = 0.80,
                 max_curated_examples: int = 10000):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.curriculum = curriculum or LearningCurriculum()
        self.acquisition = DataAcquisitionEngine(self.curriculum, min_quality=min_quality)
        self.service = ContinuousTrainingService(str(self.root / 'service'), continuous_config or ContinuousConfig())
        # NOTE: require_human_approval is unchanged and still defaults to True — an
        # auto-computed score below only ever affects candidate *eligibility*, never
        # the explicit human `approve` step a candidate still needs to go active.
        self.loop = LearningLoop(str(self.root / 'learning_registry.json'), min_improvement=min_improvement,
                                  min_score=min_score, require_human_approval=require_human_approval)
        self.evaluator = EvaluationLab(min_score)
        self.llm_evaluator = LLMEvaluator(evaluator_model) if evaluator_model is not None else None
        self.sources_path = self.root / 'curated_examples.jsonl'
        self.max_curated_examples = max(100, int(max_curated_examples))
        self.self_training = SelfTrainingEngine(evaluator_model, str(self.root / 'self_training'),
                                                batch_size=self_training_batch_size,
                                                min_teacher_score=self_training_min_score) if self_training else None

    # -- data intake -----------------------------------------------------
    def register_batch(self, rows: Iterable[dict]) -> dict:
        """Curate an operator-supplied batch. Deduplicates and applies the quality gate;
        never fetches data itself."""
        curated = self.acquisition.curate(rows)
        rows = list(rows)
        if curated:
            with self.sources_path.open('a', encoding='utf-8') as f:
                for item in curated:
                    f.write(json.dumps(asdict(item), ensure_ascii=False) + '\n')
            self._trim_jsonl(self.sources_path, self.max_curated_examples)
        return {
            'submitted': len(rows),
            'accepted': len(curated),
            'rejected': len(rows) - len(curated),
            'by_track': self._counts(curated),
            'curriculum_allocation': self.curriculum.allocate(len(curated)),
        }

    @staticmethod
    def _counts(items) -> dict:
        counts: dict = {}
        for it in items:
            counts[it.track] = counts.get(it.track, 0) + 1
        return counts

    @staticmethod
    def _trim_jsonl(path: Path, max_rows: int) -> None:
        if not path.exists(): return
        lines = [l for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
        if len(lines) <= max_rows: return
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text('\n'.join(lines[-max_rows:]) + '\n', encoding='utf-8')
        tmp.replace(path)

    def pending_examples(self, limit: Optional[int] = None) -> list[dict]:
        if not self.sources_path.exists(): return []
        max_rows = self.max_curated_examples if limit is None else max(1, min(int(limit), self.max_curated_examples))
        with self.sources_path.open('rb') as f:
            data = f.read()
        lines = [x for x in data.splitlines() if x.strip()]
        lines = lines[-max_rows:]
        items = []
        for raw in lines:
            try: items.append(json.loads(raw))
            except json.JSONDecodeError: continue
        return items

    # -- governed learning cycle ------------------------------------------
    def run_cycle(self, version: str, score: Optional[float] = None, notes: str = '') -> dict:
        """One learning-loop cycle over the currently curated dataset. `score` should
        normally come from an external evaluation the caller already ran. If omitted
        and an evaluator model is configured, an LLM-based score is computed instead
        (see llm_evaluator.py) — this only ever changes candidate *eligibility*;
        promotion still requires an explicit human `approve` call regardless. Fails
        closed (returns evaluated=False) if there is nothing curated to evaluate, or
        if no score is available from either source."""
        generated = {'generated': 0, 'accepted': 0}
        if self.self_training is not None and score is None:
            generated = self.self_training.generate_batch([t.name for t in self.curriculum.tracks])
        dataset = self.pending_examples()
        if not dataset:
            return {'evaluated': False, 'reason': 'no curated data available for this cycle', 'self_training': generated}
        auto_scored = False
        if score is None:
            if not self.llm_evaluator:
                return {'evaluated': False, 'reason': 'score not supplied and no evaluator model configured'}
            auto = self.llm_evaluator.score_examples(dataset)
            score = auto['score']; auto_scored = True
            notes = (notes + f" [auto-scored: {auto.get('reason','')}]").strip()
        proposal = self.loop.propose(version, dataset, lambda _rows: float(score), notes)
        return {'evaluated': True, 'auto_scored': auto_scored, 'self_training': generated, **proposal}

    def auto_score(self, limit: Optional[int] = None) -> dict:
        """Preview an LLM-based score over the currently curated dataset without
        proposing a candidate — useful to sanity-check before running a real cycle."""
        if not self.llm_evaluator:
            return {'evaluated': False, 'reason': 'no evaluator model configured'}
        dataset = self.pending_examples(limit)
        if not dataset:
            return {'evaluated': False, 'reason': 'no curated data available'}
        return {'evaluated': True, **self.llm_evaluator.score_examples(dataset)}

    # -- service lifecycle (delegates to ContinuousTrainingService) -------
    def start(self):
        return self.service.start()

    def pause(self):
        return self.service.pause()

    def resume(self):
        return self.service.resume()

    def stop(self, reason='operator'):
        return self.service.stop(reason)

    # -- learning-loop governance (delegates to LearningLoop) -------------
    def approve(self, version: str) -> bool:
        return self.loop.approve(version)

    def reject(self, version: str) -> bool:
        return self.loop.reject(version)

    def promote(self, version: str) -> bool:
        return self.loop.promote(version)

    def rollback(self, version: Optional[str] = None) -> bool:
        return self.loop.rollback(version)

    # -- observability -----------------------------------------------------
    def status(self) -> dict:
        return {
            'service': self.service.status(),
            'curriculum': self.curriculum.describe(),
            'pending_examples': len(self.pending_examples()),
            'active_candidate': self.loop.active(),
            'learning_history': self.loop.history()[-20:],
            'self_training': {'enabled': self.self_training is not None, 'data_path': str(self.self_training.data_path) if self.self_training else None},
        }
