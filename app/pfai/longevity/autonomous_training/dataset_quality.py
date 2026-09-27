"""Dataset quality gates — do not train on insufficient or unsafe data."""
from __future__ import annotations

import os
from typing import Any

from .dataset import DatasetBuilder
from .validator import TrainingExampleValidator


class DatasetQualityGate:
    """Enforce minimum samples, splits, provenance, leakage, and quality before training."""

    def __init__(
        self,
        *,
        min_samples: int | None = None,
        min_train: int | None = None,
        min_avg_quality: float | None = None,
        require_val_test: bool | None = None,
        max_duplicate_ratio: float | None = None,
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
        self.max_duplicate_ratio = float(
            max_duplicate_ratio
            if max_duplicate_ratio is not None
            else os.environ.get("TRAINING_MAX_DUPLICATE_RATIO", "0.5")
        )
        self.builder = DatasetBuilder(TrainingExampleValidator())

    def evaluate(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "ok": False,
                "status": "INSUFFICIENT_DATA",
                "reasons": ["INSUFFICIENT_DATA"],
                "accepted": 0,
                "rejected": 0,
                "built": {"accepted": 0, "rejected": 0, "examples": [], "splits": {"train": [], "validation": [], "test": []}},
                "model_quality_claim": False,
                "quality_note": "Empty input — cannot train.",
            }
        built = self.builder.build(rows)
        accepted = int(built.get("accepted") or 0)
        rejected = int(built.get("rejected") or 0)
        examples = built.get("examples") or []
        qualities = [float(e.quality_score) for e in examples]
        avg_q = (sum(qualities) / len(qualities)) if qualities else 0.0
        train = built["splits"].get("train") or []
        val = built["splits"].get("validation") or []
        test = built["splits"].get("test") or []
        train_n, val_n, test_n = len(train), len(val), len(test)
        provenance_ok = all(bool(e.source) and bool(e.content_hash) for e in examples) if examples else False

        # Leakage: identical content hashes across train and test/val
        train_hashes = {e.content_hash for e in train}
        val_hashes = {e.content_hash for e in val}
        test_hashes = {e.content_hash for e in test}
        leakage = sorted((train_hashes & val_hashes) | (train_hashes & test_hashes) | (val_hashes & test_hashes))
        dup_ratio = (rejected / max(1, len(rows))) if rows else 0.0

        reasons: list[str] = []
        if accepted < self.min_samples:
            reasons.append("INSUFFICIENT_DATA")
        if train_n < self.min_train:
            reasons.append("INSUFFICIENT_TRAIN_SPLIT")
        if self.require_val_test and accepted >= 3 and (val_n < 1 or test_n < 1):
            reasons.append("MISSING_VAL_OR_TEST_SPLIT")
            if "DATASET_INVALID" not in reasons:
                reasons.append("DATASET_INVALID")
        if avg_q < self.min_avg_quality and accepted > 0:
            reasons.append("DATASET_QUALITY_BELOW_THRESHOLD")
        if accepted > 0 and not provenance_ok:
            reasons.append("MISSING_PROVENANCE")
            reasons.append("DATASET_INVALID")
        if leakage:
            reasons.append("TRAIN_TEST_LEAKAGE")
            reasons.append("DATASET_INVALID")
        if dup_ratio > self.max_duplicate_ratio and len(rows) >= self.min_samples:
            reasons.append("EXCESSIVE_DUPLICATES")

        # Deduplicate reason list while preserving order
        seen: set[str] = set()
        uniq_reasons = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                uniq_reasons.append(r)

        ok = not uniq_reasons
        if ok:
            status = "DATASET_READY"
        elif "INSUFFICIENT_DATA" in uniq_reasons or "INSUFFICIENT_TRAIN_SPLIT" in uniq_reasons:
            status = "INSUFFICIENT_DATA"
        elif any(r in uniq_reasons for r in ("DATASET_INVALID", "TRAIN_TEST_LEAKAGE", "MISSING_PROVENANCE")):
            status = "DATASET_INVALID"
        else:
            status = uniq_reasons[0]

        note = (
            "Small datasets prove pipeline function only — not production model quality."
            if accepted < 50
            else "Dataset size meets pipeline minimum; production quality still requires task evaluation."
        )
        return {
            "ok": ok,
            "status": status,
            "reasons": uniq_reasons,
            "built": built,
            "accepted": accepted,
            "rejected": rejected,
            "avg_quality": avg_q,
            "min_samples": self.min_samples,
            "min_avg_quality": self.min_avg_quality,
            "splits": {"train": train_n, "validation": val_n, "test": test_n},
            "provenance_ok": provenance_ok,
            "leakage_hashes": leakage[:10],
            "duplicate_ratio": round(dup_ratio, 4),
            "duplicates_rejected": max(0, rejected),
            "quality_note": note,
            "model_quality_claim": False,
        }
