"""Validate training examples before dataset inclusion."""
from __future__ import annotations

from typing import Any

from .sanitizer import TrainingDataSanitizer


class TrainingExampleValidator:
    def __init__(
        self,
        *,
        min_chars: int = 8,
        max_chars: int = 20000,
        min_quality: float = 0.5,
        sanitizer: TrainingDataSanitizer | None = None,
    ) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.min_quality = min_quality
        self.sanitizer = sanitizer or TrainingDataSanitizer()

    def score(self, instruction: str, response: str, *, verified: bool = False) -> float:
        score = 0.4
        if len(instruction) >= self.min_chars and len(response) >= self.min_chars:
            score += 0.2
        if len(response) >= 40:
            score += 0.15
        if verified:
            score += 0.2
        if "?" in instruction:
            score += 0.05
        return min(1.0, score)

    def validate(self, row: dict[str, Any]) -> dict[str, Any]:
        """Return {ok, reason, example?}."""
        cleaned = self.sanitizer.sanitize_example(row)
        if cleaned is None:
            return {"ok": False, "reason": "sanitizer_rejected"}
        instruction = cleaned["instruction"]
        response = cleaned["response"]
        if self.sanitizer.contains_forbidden_authority(instruction + "\n" + response):
            return {"ok": False, "reason": "authority_isolation_violation"}
        total = len(instruction) + len(response)
        if len(instruction) < self.min_chars or len(response) < self.min_chars:
            return {"ok": False, "reason": "too_short"}
        if total > self.max_chars:
            return {"ok": False, "reason": "too_long"}
        verified = bool((cleaned.get("provenance") or {}).get("verified") or row.get("verified"))
        quality = self.score(instruction, response, verified=verified)
        if quality < self.min_quality:
            return {"ok": False, "reason": "low_quality", "quality_score": quality}
        cleaned["quality_score"] = quality
        cleaned["validation_status"] = "validated"
        return {"ok": True, "example": cleaned, "quality_score": quality}
