"""PHASE 11 — production banks integrity and train/eval leakage isolation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.evaluation_dataset import EvaluationDatasetBuilder
from pfai.longevity.autonomous_training.production_banks import (
    bank_stats,
    production_eval_examples,
    production_train_examples,
)


class TestProductionBanks(unittest.TestCase):
    def test_disjoint_and_sized(self):
        stats = bank_stats()
        self.assertTrue(stats["disjoint"])
        self.assertGreaterEqual(stats["train_count"], 100)
        self.assertGreaterEqual(stats["eval_count"], 200)
        train_h = {r["content_hash"] for r in production_train_examples()}
        eval_h = {r["content_hash"] for r in production_eval_examples()}
        self.assertEqual(len(train_h & eval_h), 0)
        for r in production_eval_examples():
            self.assertTrue((r.get("provenance") or {}).get("eligible_for_evaluation"))
            self.assertFalse((r.get("provenance") or {}).get("synthetic", True))

    def test_eval_harvest_excludes_train_bank(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ws = root / "data"
            (ws / "longevity").mkdir(parents=True)
            builder = EvaluationDatasetBuilder(str(root / "evalds"))
            harvested = builder.harvest(workspace=ws)
            train_h = {r["content_hash"] for r in production_train_examples()}
            leak = [e for e in harvested["examples"] if e["content_hash"] in train_h]
            self.assertEqual(leak, [])
            self.assertGreaterEqual(harvested["count"], 200)


if __name__ == "__main__":
    unittest.main()
