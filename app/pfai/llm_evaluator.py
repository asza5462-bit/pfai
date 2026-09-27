"""LLM-based quality scoring for curated continuous-learning examples.

This automates the tedious part of continuous learning — grading a curated batch of
instruction/response pairs — using the connected model instead of requiring an
operator to type a number by hand. It does NOT touch the promotion gate:
`LearningLoop` / `ContinuousLearningOrchestrator` still require an explicit human
`approve` call before any candidate becomes active (`require_human_approval` stays
True by default and is untouched here). This module only ever proposes the `score`
that governs whether a candidate is *eligible* for that human review — it fails
closed to 0.0 (never eligible) on any error, rather than inventing an optimistic
number.
"""
from __future__ import annotations
import json
from typing import Any, Dict, Iterable


_SCORE_PROMPT = (
    "Rate the overall quality of these instruction/response training examples on a "
    "scale from 0.0 (unusable) to 1.0 (excellent: correct, clear, well-scoped). "
    'Return ONLY JSON, no prose: {{"score": <float 0-1>, "reason": "<=1 sentence"}}\n'
    "Examples (truncated): {examples}\n"
)


class LLMEvaluator:
    def __init__(self, model, max_examples: int = 20, max_chars: int = 4000):
        if max_examples <= 0 or max_chars <= 0:
            raise ValueError("max_examples and max_chars must be positive")
        self.model = model
        self.max_examples = int(max_examples)
        self.max_chars = int(max_chars)

    def score_examples(self, examples: Iterable[dict]) -> Dict[str, Any]:
        rows = list(examples)[: self.max_examples]
        if not rows:
            return {"score": 0.0, "reason": "no examples to evaluate", "evaluated": 0}

        sample = [
            {"instruction": str(r.get("instruction", ""))[:500],
             "response": str(r.get("response", ""))[:500]}
            for r in rows
        ]
        payload = json.dumps(sample, ensure_ascii=False)[: self.max_chars]

        try:
            raw = self.model.generate(_SCORE_PROMPT.format(examples=payload))
            start, end = raw.find("{"), raw.rfind("}")
            parsed = json.loads(raw[start:end + 1]) if start != -1 and end > start else None
        except Exception:
            parsed = None

        if not isinstance(parsed, dict) or "score" not in parsed:
            return {"score": 0.0, "reason": "evaluation failed; failed closed to 0.0", "evaluated": 0}

        try:
            score = max(0.0, min(1.0, float(parsed["score"])))
        except (TypeError, ValueError):
            return {"score": 0.0, "reason": "evaluation returned a non-numeric score", "evaluated": 0}

        return {"score": score, "reason": str(parsed.get("reason", "")), "evaluated": len(rows)}
