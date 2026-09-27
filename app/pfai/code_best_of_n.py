"""Best-of-N candidate selection for code generation.

The standard way self-taught code models actually get better (STaR / rejection
fine-tuning style): generate several candidate solutions for the same problem,
run every one of them against real tests, and only ever keep the ones that
truly pass -- never grade candidates by how plausible they look.

This module is pure selection logic. It does not call any model itself (the
caller supplies already-generated candidate code strings, e.g. from
IntelligentReasoner / Agent) and it does not touch the promotion gate -- it
only decides which of N candidates, if any, is worth curating as a training
example via ContinuousLearningOrchestrator.register_batch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .code_execution_evaluator import SandboxedCodeEvaluator, ExecutionEvalResult


@dataclass(frozen=True)
class BestOfNResult:
    best_index: Optional[int]
    best_code: Optional[str]
    passing_indices: List[int]
    results: List[ExecutionEvalResult]


def select_best_solution(candidates: List[str], test_code: str,
                          evaluator: Optional[SandboxedCodeEvaluator] = None) -> BestOfNResult:
    """Evaluate every candidate in the sandbox and pick a winner.

    Selection rule among passing candidates: shortest source wins (a simple,
    defensible proxy for "clearer, less over-fit to the specific test" without
    needing a second model call to break ties). No passing candidate ->
    best_index/best_code are None; the caller should not curate anything from
    this batch.
    """
    if not candidates:
        return BestOfNResult(None, None, [], [])

    evaluator = evaluator or SandboxedCodeEvaluator()
    results = [evaluator.evaluate(code, test_code) for code in candidates]
    passing_indices = [i for i, r in enumerate(results) if r.passed]

    if not passing_indices:
        return BestOfNResult(None, None, [], results)

    best_index = min(passing_indices, key=lambda i: len(candidates[i]))
    return BestOfNResult(best_index, candidates[best_index], passing_indices, results)
