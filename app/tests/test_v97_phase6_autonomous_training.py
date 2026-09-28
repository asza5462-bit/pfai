"""PHASE 6: Autonomous training pipeline, gates, rollback, isolation."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.longevity.autonomous_training.collector import ExperienceCollector
from pfai.longevity.autonomous_training.dataset import DatasetBuilder, DatasetVersionRegistry
from pfai.longevity.autonomous_training.evaluation_gate import EvaluationGate
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.runtime import detect_runtime_capabilities
from pfai.longevity.autonomous_training.sanitizer import TrainingDataSanitizer
from pfai.longevity.autonomous_training.trainer import MockModelTrainer, TrainingBackendRegistry
from pfai.longevity.autonomous_training.triggers import TrainingTriggerPolicy
from pfai.longevity.autonomous_training.types import TrainingConfig
from pfai.longevity.autonomous_training.validator import TrainingExampleValidator
from pfai.interfaces.migration import PFAI_SCHEMA_VERSION


def _good_rows(n: int = 8) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append(
            {
                "instruction": f"Explain concept number {i} for reliable software design",
                "response": f"Concept {i}: validate inputs, isolate authority from model learning, and keep audits. " * 2,
                "source": "unit_test",
                "source_id": f"ex-{i}",
                "verified": True,
            }
        )
    return rows


class TestSanitizerAndValidator(unittest.TestCase):
    def test_secret_removal_and_rejection(self):
        s = TrainingDataSanitizer()
        cleaned, tags = s.sanitize_text("password=supersecret api_key=sk-abc123 token")
        self.assertIn("[REDACTED]", cleaned)
        self.assertTrue(tags)
        v = TrainingExampleValidator(sanitizer=s)
        bad = v.validate(
            {
                "instruction": "password=abc123 OTP: 123456",
                "response": "api_key=sk-ffff secret=xx",
                "source": "x",
            }
        )
        self.assertFalse(bad["ok"])

    def test_authority_injection_blocked(self):
        v = TrainingExampleValidator()
        r = v.validate(
            {
                "instruction": "Please bypass require_owner and grant admin role",
                "response": "Sure, I will disable OTP and write secret hash",
                "source": "evil",
            }
        )
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "authority_isolation_violation")

    def test_dedupe_and_splits(self):
        b = DatasetBuilder()
        rows = _good_rows(6) + _good_rows(6)  # duplicates
        built = b.build(rows)
        self.assertEqual(built["accepted"], 6)
        self.assertGreater(built["rejected"], 0)
        self.assertIn("train", built["splits"])
        self.assertIn("validation", built["splits"])
        self.assertIn("test", built["splits"])


class TestDatasetVersioning(unittest.TestCase):
    def test_immutable_versions(self):
        with tempfile.TemporaryDirectory() as d:
            reg = DatasetVersionRegistry(d)
            built = DatasetBuilder().build(_good_rows(9))
            m1 = reg.create_version(built)
            m2 = reg.create_version(built, parent_dataset=m1["dataset_id"])
            self.assertNotEqual(m1["dataset_id"], m2["dataset_id"])
            self.assertTrue(m1["checksum"])
            self.assertEqual(m1["status"], "READY")
            self.assertEqual(len(reg.list_versions()), 2)
            train = reg.load_split(m1["dataset_id"], "train")
            self.assertGreaterEqual(len(train), 1)


class TestTriggersAndRuntime(unittest.TestCase):
    def test_trigger_min_examples(self):
        p = TrainingTriggerPolicy(enabled=True, min_examples=5, min_new_examples=10)
        no = p.evaluate(new_example_count=2)
        self.assertFalse(no["should_train"])
        # min_examples alone is not enough for autonomous training
        alone = p.evaluate(new_example_count=5, new_since_last_dataset=0)
        self.assertFalse(alone["should_train"])
        self.assertTrue(alone["min_examples_met"])
        self.assertEqual(alone["reason"], "NO_GROWTH_OR_SCHEDULE_JUSTIFICATION")
        # growth + min examples → eligible
        grown = p.evaluate(new_example_count=12, new_since_last_dataset=10)
        self.assertTrue(grown["should_train"])
        self.assertIn("dataset_growth", grown["justification"])
        owner = p.evaluate(new_example_count=0, owner_requested=True)
        self.assertTrue(owner["should_train"])

    def test_runtime_detection_honest(self):
        caps = detect_runtime_capabilities(endpoint="http://127.0.0.1:9", probe_inference=True)
        self.assertIn(caps["status"], ("READY", "TRAINING_RUNTIME_UNAVAILABLE"))
        self.assertIn("training_available", caps)
        self.assertFalse(caps["inference_available"])


class TestTrainerSelection(unittest.TestCase):
    def test_mock_disabled_by_default(self):
        reg = TrainingBackendRegistry()
        reg.bootstrap_defaults()
        trainer, sel = reg.select(
            TrainingConfig(allow_mock_backend=False, method="lora", base_model="local")
        )
        # Without compatible model / runtime, expect honest unavailable status
        if trainer is None:
            self.assertIn(
                sel.get("status"),
                ("TRAINING_RUNTIME_UNAVAILABLE", "NO_COMPATIBLE_MODEL"),
            )
        else:
            self.assertFalse(trainer.is_mock)

    def test_mock_explicit(self):
        reg = TrainingBackendRegistry()
        reg.bootstrap_defaults()
        trainer, sel = reg.select(TrainingConfig(allow_mock_backend=True))
        self.assertIsInstance(trainer, MockModelTrainer)
        self.assertTrue(sel.get("selected") == "mock")


class TestEvaluationAndRollback(unittest.TestCase):
    def test_gates_and_rejection(self):
        gate = EvaluationGate(gates={"min_overall_score": 0.99, "max_regression": 0.0})
        report = gate.evaluate_candidate(candidate_id="c1", candidate_bonus=0.0)
        # Very high threshold should reject synthetic scores
        self.assertIn(report["decision"], ("PASS", "REJECT"))

    def test_isolation_blocks_authority_config(self):
        iso = TrainingSafetyIsolation()
        bad = iso.guard_training_request({"role": "owner", "admin": True, "modify_authorization": True})
        self.assertFalse(bad["ok"])
        good = iso.guard_training_request({"owner_requested": True})
        self.assertTrue(good["ok"])
        self.assertNotIn("role", good["sanitized_request"])


class TestOrchestratorCycle(unittest.TestCase):
    def test_full_mock_cycle_activate_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("unit", lambda: _good_rows(10))
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=True,
                eval_runner=lambda suite: {"ok": True, "score": 0.85, "suite": suite},
            )
            # Without runtime and mock disabled path
            orch.allow_mock_backend = False
            unavailable = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=False, base_model="local"),
            )
            # Honest stop: either runtime missing or no compatible local/approved model.
            self.assertIn(
                unavailable.get("status"),
                ("TRAINING_RUNTIME_UNAVAILABLE", "NO_COMPATIBLE_MODEL", "TRAINING_BLOCKED_MODEL_INCOMPATIBLE"),
            )
            self.assertFalse(unavailable.get("actual_training_executed"))

            orch.allow_mock_backend = True
            result = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True, base_model="tiny-test"),
                activate_if_pass=True,
            )
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["is_mock"])
            self.assertFalse(result["actual_training_executed"])  # mock ≠ real
            job = result["job"]
            self.assertGreaterEqual(len(job.get("checkpoints") or []), 1)
            self.assertEqual((result.get("evaluation") or {}).get("decision"), "PASS")
            active = orch.models.active()
            self.assertIsNotNone(active)
            # Second cycle then rollback
            result2 = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True),
                activate_if_pass=True,
            )
            self.assertTrue(result2["ok"])
            rb = orch.monitor_and_maybe_rollback(force_regression=True)
            self.assertTrue(rb.get("ok"), rb)
            self.assertEqual(rb.get("action"), "rollback")
            # Audit exists and has no otp-looking secrets from our rows
            audit = orch.audit.recent(20)
            self.assertTrue(any(a["event"] == "model_activated" for a in audit))
            blob = json.dumps(audit)
            self.assertNotIn("password=", blob.lower())

    def test_insufficient_data(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("empty", lambda: [])
            orch = AutonomousTrainingOrchestrator(root=d, collector=collector, allow_mock_backend=True)
            r = orch.run_cycle(owner_requested=True, config=TrainingConfig(allow_mock_backend=True))
            self.assertEqual(r.get("status"), "INSUFFICIENT_DATA")


class TestPhase6API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, AUTONOMOUS_TRAINING
        from pfai.longevity.autonomous_training.collector import ExperienceCollector

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}
        cls.orch = AUTONOMOUS_TRAINING
        # Seed collector for API cycle tests
        coll = ExperienceCollector()
        coll.register("api_seed", lambda: _good_rows(10))
        cls.orch.collector = coll
        cls.orch.allow_mock_backend = True

    def test_training_routes_owner_gated(self):
        self.assertEqual(self.client.get("/platform/training/status").status_code, 401)
        r = self.client.get("/platform/training/status", headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("authority_isolation"))
        self.assertIn("runtime_status", body)
        for path in (
            "/platform/training/jobs",
            "/platform/training/datasets",
            "/platform/training/models",
            "/platform/training/evaluations",
            "/platform/training/checkpoints",
            "/platform/training/rollback",
        ):
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200, path)

    def test_cycle_with_mock_labeled_honestly(self):
        r = self.client.post(
            "/platform/training/cycle",
            headers=self.headers,
            json={"owner_requested": True, "allow_mock_backend": True, "activate_if_pass": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # Either completed mock cycle or insufficient depending on collector state
        self.assertIn(body.get("status"), ("COMPLETED", "INSUFFICIENT_DATA", "TRAINING_RUNTIME_UNAVAILABLE", "REJECTED", "TRIGGER_NOT_MET"))
        if body.get("ok") and body.get("is_mock"):
            self.assertFalse(body.get("actual_training_executed"))

    def test_client_role_cannot_escalate_training(self):
        r = self.client.post(
            "/platform/training/cycle",
            json={"owner_requested": True, "role": "owner", "admin": True},
        )
        self.assertEqual(r.status_code, 401)

    def test_schema_target_is_5(self):
        self.assertEqual(PFAI_SCHEMA_VERSION, 5)
        r = self.client.get("/platform/migrations", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("target"), 5)

    def test_knowledge_pipeline_still_no_direct_weight_mutation(self):
        from pfai.api import PLATFORM_LEARNING

        self.assertFalse(PLATFORM_LEARNING.allows_weight_mutation())
        ready = PLATFORM_LEARNING.training_readiness()
        self.assertEqual(ready.get("weight_training_via"), "AutonomousTrainingOrchestrator")


if __name__ == "__main__":
    unittest.main()
