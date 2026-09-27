"""PHASE 11 production validation tests — never claim production without gates."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.canary import CanaryController
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.production_validation import (
    EvaluationSuiteRegistry,
    ProductionGateConfig,
    ProductionQualityGate,
    PromotionStageController,
)
from pfai.longevity.autonomous_training.resources import TrainingResourceManager
from pfai.longevity.autonomous_training.runtime_detector import TrainingRuntimeDetector


class TestProductionGateConfig(unittest.TestCase):
    def test_defaults_are_strict(self):
        cfg = ProductionGateConfig()
        self.assertGreaterEqual(cfg.min_evaluation_samples, 200)
        self.assertGreaterEqual(cfg.min_task_pass_rate, 0.8)
        self.assertTrue(cfg.require_rollback_available)
        self.assertTrue(cfg.require_security_pass)

    def test_env_override(self):
        import os

        os.environ["PRODUCTION_MIN_EVAL_SAMPLES"] = "12"
        try:
            cfg = ProductionGateConfig.from_env()
            self.assertEqual(cfg.min_evaluation_samples, 12)
        finally:
            os.environ.pop("PRODUCTION_MIN_EVAL_SAMPLES", None)


class TestEvaluationSuiteVersioning(unittest.TestCase):
    def test_content_addressed_suite(self):
        with tempfile.TemporaryDirectory() as d:
            reg = EvaluationSuiteRegistry(d)
            tasks = [{"id": "a", "suite": "smoke", "prompt": "x"}]
            s1 = reg.register_or_get(tasks=tasks)
            s2 = reg.register_or_get(tasks=tasks)
            self.assertEqual(s1.content_hash, s2.content_hash)
            self.assertEqual(s1.version, s2.version)
            tasks2 = tasks + [{"id": "b", "suite": "coding", "prompt": "y"}]
            s3 = reg.register_or_get(tasks=tasks2)
            self.assertNotEqual(s3.content_hash, s1.content_hash)


class TestPromotionSimulation(unittest.TestCase):
    def test_shadow_canary_path(self):
        ctrl = PromotionStageController(canary_failure_threshold=0.2)
        ok = ctrl.run_local_simulation(
            offline_ok=True,
            candidate_pass_rate=0.6,
            baseline_pass_rate=0.55,
            regression=0.0,
            inference_ok=True,
        )
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["decision"], "CONTINUE")
        bad = ctrl.run_local_simulation(
            offline_ok=True,
            candidate_pass_rate=0.2,
            baseline_pass_rate=0.8,
            regression=0.5,
            inference_ok=True,
        )
        self.assertFalse(bad["ok"])

    def test_canary_controller_simulation(self):
        c = CanaryController()
        r = c.simulate_promotion_path(
            offline_ok=True,
            regression=0.0,
            candidate_pass_rate=0.7,
            baseline_pass_rate=0.6,
        )
        self.assertTrue(r["ok"])


class TestProductionGateFromInjected(unittest.TestCase):
    def test_insufficient_samples_blocks_production(self):
        with tempfile.TemporaryDirectory() as d:
            gate = ProductionQualityGate(
                d,
                config=ProductionGateConfig(min_evaluation_samples=200, min_task_pass_rate=0.85),
            )
            baseline_eval = {
                "model_id": "model-v0001",
                "checkpoint_hash": "aaa",
                "load_ok": True,
                "inference_ok": True,
                "pass_rate": 0.6,
                "passed": 6,
                "failed": 4,
                "mean_perplexity": 100.0,
                "perplexity_n": 8,
                "suite_pass_rates": {"coding": 0.5, "security": 1.0},
                "task_results": [
                    {"suite": "security", "ok": True, "reason": "match", "output_preview": "no"},
                    {"suite": "smoke", "ok": True, "reason": "nonempty_safe", "output_preview": "ok"},
                ],
                "runtime_seconds": 1.0,
            }
            candidate_eval = dict(baseline_eval)
            candidate_eval["checkpoint_hash"] = "bbb"
            candidate_eval["mean_perplexity"] = 98.0
            comparison = {
                "quality_gate_result": "PASS",
                "regression_detected": False,
                "pass_rate_delta": 0.0,
                "perplexity_ratio": 0.98,
                "evaluation_examples": 20,
                "reasons": ["PRODUCTION_BAR_NOT_MET"],
            }
            report = gate.evaluate_from_results(
                candidate={"model_id": "model-v0003", "checkpoint_ref": "c"},
                baseline={"model_id": "model-v0001", "checkpoint_ref": "b"},
                dataset_id="dataset-v0003",
                baseline_eval=baseline_eval,
                candidate_eval=candidate_eval,
                comparison=comparison,
                rollback_available=True,
                dataset_integrity_ok=True,
            )
            self.assertFalse(report["model_quality_production_validated"])
            self.assertIn("INSUFFICIENT_EVALUATION_SAMPLES", report["blockers"])
            self.assertTrue(Path(report["evaluation_run_path"]).exists())

    def test_all_gates_pass_when_thresholds_met(self):
        with tempfile.TemporaryDirectory() as d:
            gate = ProductionQualityGate(
                d,
                config=ProductionGateConfig(
                    min_evaluation_samples=10,
                    min_task_pass_rate=0.5,
                    min_coding_pass_rate=0.4,
                    min_stability_rate=0.5,
                    min_inference_success_rate=0.9,
                ),
            )
            tasks = [
                {
                    "suite": "security",
                    "ok": True,
                    "reason": "match",
                    "output_preview": "no secrets here",
                }
            ] + [
                {
                    "suite": "smoke",
                    "ok": True,
                    "reason": "nonempty_safe",
                    "output_preview": f"stable output {i}",
                }
                for i in range(12)
            ]
            baseline_eval = {
                "load_ok": True,
                "inference_ok": True,
                "pass_rate": 0.7,
                "passed": 10,
                "failed": 4,
                "mean_perplexity": 100.0,
                "perplexity_n": 5,
                "suite_pass_rates": {"coding": 0.6, "security": 1.0},
                "task_results": tasks,
                "checkpoint_hash": "basehash",
                "runtime_seconds": 1.0,
            }
            candidate_eval = dict(baseline_eval)
            candidate_eval["checkpoint_hash"] = "candhash"
            candidate_eval["mean_perplexity"] = 95.0
            comparison = {
                "quality_gate_result": "PASS",
                "regression_detected": False,
                "pass_rate_delta": 0.0,
                "perplexity_ratio": 0.95,
                "evaluation_examples": 18,
                "reasons": [],
            }
            report = gate.evaluate_from_results(
                candidate={"model_id": "c", "checkpoint_ref": "c"},
                baseline={"model_id": "b", "checkpoint_ref": "b"},
                dataset_id="dataset-v0003",
                baseline_eval=baseline_eval,
                candidate_eval=candidate_eval,
                comparison=comparison,
                rollback_available=True,
                dataset_integrity_ok=True,
            )
            self.assertTrue(report["model_quality_production_validated"], report["blockers"])


class TestPhase11OrchestratorStatus(unittest.TestCase):
    def test_production_status_and_artifacts(self):
        root = Path("data/longevity/training_phase9_verify")
        if not root.exists():
            self.skipTest("phase9 verify absent")
        from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator

        orch = AutonomousTrainingOrchestrator(
            root=str(root), allow_mock_backend=False, include_approved_seeds=False
        )
        st = orch.production_validation_status()
        self.assertTrue(st["implemented"])
        self.assertIn("gate_config", st)
        self.assertEqual(orch.models.active()["model_id"], "model-v0003")
        self.assertEqual(orch.models.last_known_good()["model_id"], "model-v0001")
        # Isolation still intact
        self.assertFalse(
            TrainingSafetyIsolation().guard_training_request({"modify_authorization": True})["ok"]
        )

    def test_gpu_honesty(self):
        probe = TrainingRuntimeDetector().detect(probe_inference=False).to_dict()
        self.assertIn("gpu_available", probe)
        admit = TrainingResourceManager().admit(dataset_rows=10, method="lora", running_jobs=0)
        self.assertIn("ok", admit)


if __name__ == "__main__":
    unittest.main()
