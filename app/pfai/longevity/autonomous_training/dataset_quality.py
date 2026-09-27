"""Dataset quality gates — do not train on insufficient or unsafe data."""
from __future__ import annotations

import os
from typing import Any

from .dataset import DatasetBuilder
from .validator import TrainingExampleValidator


class DatasetQualityGate:
    """Enforce minimum samples, splits, provenance, and quality before training."""

    def __init__(
        self,
        *,
        min_samples: int | None = None,
        min_train: int | None = None,
        min_avg_quality: float | None = None,
        require_val_test: bool | None = None,
    ) -> None:
        self.min_samples = int(
            min_samples
            if min_samples is not None
            else os.environ.get("TRAINING_MIN_SAMPLES", os.environ.get("TRAINING_MIN_EXAMPLES", "5"))
        )
        self.min_train = int(min_train if min_train is not None else os.environ.get("TRAINING_MIN_TRAIN_SAMPLES", "3"))
        self.min_avg_quality = float(
            min_avg_quality
            if min_avg_quality is not None
            else os.environ.get("TRAINING_MIN_DATASET_QUALITY", "0.55")
        )
        self.require_val_test = (
            require_val_test
            if require_val_test is not None
            else (os.environ.get("TRAINING_REQUIRE_VAL_TEST") or "true").lower() in ("1", "true", "yes")
        )
        self.builder = DatasetBuilder(TrainingExampleValidator())

    def evaluate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        built = self.builder.build(rows)
        accepted = int(built.get("accepted") or 0)
        rejected = int(built.get("rejected") or 0)
        examples = built.get("examples") or []
        qualities = [float(e.quality_score) for e in examples]
        avg_q = (sum(qualities) / len(qualities)) if qualities else 0.0
        train_n = len(built["splits"].get("train") or [])
        val_n = len(built["splits"].get("validation") or [])
        test_n = len(built["splits"].get("test") or [])
        provenance_ok = all(bool(e.source) and bool(e.content_hash) for e in examples) if examples else False

        reasons: list[str] = []
        if accepted < self.min_samples:
            reasons.append("INSUFFICIENT_DATA")
        if train_n < self.min_train:
            reasons.append("INSUFFICIENT_TRAIN_SPLIT")
        if self.require_val_test and accepted >= 3 and (val_n < 1 or test_n < 1):
            reasons.append("MISSING_VAL_OR_TEST_SPLIT")
        if avg_q < self.min_avg_quality and accepted > 0:
            reasons.append("DATASET_QUALITY_BELOW_THRESHOLD")
        if accepted > 0 and not provenance_ok:
            reasons.append("MISSING_PROVENANCE")

        ok = not reasons
        note = (
            "Small datasets prove pipeline function only — not production model quality."
            if accepted < 50
            else "Dataset size meets pipeline minimum; production quality still requires task evaluation."
        )
        return {
            "ok": ok,
            "status": "READY" if ok else (reasons[0] if reasons else "REJECTED"),
            "reasons": reasons,
            "built": built,
            "accepted": accepted,
            "rejected": rejected,
            "avg_quality": avg_q,
            "min_samples": self.min_samples,
            "min_avg_quality": self.min_avg_quality,
            "splits": {"train": train_n, "validation": val_n, "test": test_n},
            "provenance_ok": provenance_ok,
            "duplicates_rejected": max(0, rejected),  # includes validation failures + dupes
            "quality_note": note,
            "model_quality_claim": False,  # never claim quality from sample count alone
        }
