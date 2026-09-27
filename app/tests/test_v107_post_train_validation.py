"""Post-train validation tests — real compare infrastructure, no fake production claims."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.post_train_validation import (
    DEFAULT_ACCEPTANCE,
    PostTrainValidator,
    checkpoint_hash,
)
from pfai.longevity.autonomous_training.types import ModelStatus


class TestPostTrainValidation(unittest.TestCase):
    def test_checkpoint_hashes_differ_for_v0001_v0003(self):
        root = Path("data/longevity/training_phase9_verify")
        if not root.exists():
            self.skipTest("phase9 verify absent")
        c1 = root / "artifacts/job-ed48fb2b07df/checkpoint-final"
        c3 = root / "artifacts/job-94d9f8c65f8a/checkpoint-final"
        if not (c1 / "adapter_model.safetensors").exists():
            self.skipTest("baseline adapter missing")
        if not (c3 / "adapter_model.safetensors").exists():
            self.skipTest("candidate adapter missing")
        h1 = checkpoint_hash(str(c1))
        h3 = checkpoint_hash(str(c3))
        self.assertTrue(h1)
        self.assertTrue(h3)
        self.assertNotEqual(h1, h3)

    def test_compare_detects_regression(self):
        from pfai.longevity.autonomous_training.post_train_validation import ModelEvalResult

        v = PostTrainValidator()
        baseline = ModelEvalResult(
            model_id="b",
            checkpoint_ref="x",
            checkpoint_hash="a",
            load_ok=True,
            inference_ok=True,
            passed=8,
            failed=2,
            pass_rate=0.8,
            mean_perplexity=50.0,
            perplexity_n=5,
        )
        candidate = ModelEvalResult(
            model_id="c",
            checkpoint_ref="y",
            checkpoint_hash="b",
            load_ok=True,
            inference_ok=True,
            passed=2,
            failed=8,
            pass_rate=0.2,
            mean_perplexity=90.0,
            perplexity_n=5,
        )
        cmp = v.compare(
            baseline=baseline,
            candidate=candidate,
            evaluation_dataset="unit",
            evaluation_examples=15,
        )
        self.assertTrue(cmp["regression_detected"])
        self.assertEqual(cmp["quality_gate_result"], "FAIL")
        self.assertEqual(cmp["decision"], "ROLLBACK_TO_LKG")
        self.assertFalse(cmp["production_quality_validated"])

    def test_production_bar_not_met_for_small_suite(self):
        from pfai.longevity.autonomous_training.post_train_validation import ModelEvalResult

        v = PostTrainValidator()
        baseline = ModelEvalResult(
            model_id="b",
            checkpoint_ref="x",
            checkpoint_hash="a",
            load_ok=True,
            inference_ok=True,
            passed=6,
            failed=4,
            pass_rate=0.6,
            mean_perplexity=100.0,
            perplexity_n=8,
        )
        candidate = ModelEvalResult(
            model_id="c",
            checkpoint_ref="y",
            checkpoint_hash="b",
            load_ok=True,
            inference_ok=True,
            passed=6,
            failed=4,
            pass_rate=0.6,
            mean_perplexity=98.0,
            perplexity_n=8,
        )
        cmp = v.compare(
            baseline=baseline,
            candidate=candidate,
            evaluation_dataset="unit",
            evaluation_examples=20,
        )
        self.assertEqual(cmp["quality_gate_result"], "PASS")
        self.assertFalse(cmp["production_quality_validated"])
        self.assertIn("PRODUCTION_BAR_NOT_MET", cmp["reasons"])
        self.assertGreaterEqual(
            DEFAULT_ACCEPTANCE["production_min_examples"], 200
        )

    def test_report_artifact_exists_after_real_run(self):
        report = Path(
            "data/longevity/training_phase9_verify/artifacts/post_train_validation.json"
        )
        if not report.exists():
            self.skipTest("validation report not present")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data.get("post_train_validation"), "complete")
        self.assertEqual(data.get("baseline_model"), "model-v0001")
        self.assertEqual(data.get("candidate_model"), "model-v0003")
        self.assertFalse(data.get("production_quality_validated"))
        self.assertTrue(data.get("real_evaluation_executed"))


if __name__ == "__main__":
    unittest.main()
