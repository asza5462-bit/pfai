"""PHASE 8: real training runtime enablement and honest verification labels."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.longevity.autonomous_training.collector import ExperienceCollector
from pfai.longevity.autonomous_training.compatibility import ModelCompatibilityChecker
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.runtime_detector import (
    RuntimeAvailability,
    TrainingRuntimeDetector,
)
from pfai.longevity.autonomous_training.sanitizer import TrainingDataSanitizer
from pfai.longevity.autonomous_training.trainer import (
    MockModelTrainer,
    RealLoRATrainingBackend,
    TrainingBackendRegistry,
)
from pfai.longevity.autonomous_training.types import TrainingConfig


def _rows(n: int = 10):
    return [
        {
            "instruction": f"Describe continuous improvement pattern {i}",
            "response": f"Pattern {i}: version datasets, train adapters, evaluate, canary, then activate only if gates pass. " * 2,
            "source": "phase8",
            "source_id": f"p8-{i}",
            "verified": True,
        }
        for i in range(n)
    ]


def _runtime_available() -> bool:
    return bool(TrainingRuntimeDetector().detect(probe_inference=False).training_available)


def _local_tiny_model() -> Path | None:
    candidates = [
        Path("data/models/tiny-random-gpt2"),
        Path("/agent/pfai/pfai/app/data/models/tiny-random-gpt2"),
    ]
    for p in candidates:
        if (p / "config.json").exists():
            return p.resolve()
    return None


class TestPhase8RuntimeDetector(unittest.TestCase):
    def test_status_enum_and_modules(self):
        det = TrainingRuntimeDetector(endpoint="http://127.0.0.1:9")
        result = det.detect(probe_inference=False)
        self.assertIn(
            result.status,
            (
                RuntimeAvailability.AVAILABLE.value,
                RuntimeAvailability.PARTIAL.value,
                RuntimeAvailability.UNAVAILABLE.value,
                RuntimeAvailability.ERROR.value,
            ),
        )
        self.assertIn("torch", result.modules)
        self.assertIn("safetensors", result.modules)
        self.assertIn("setup_path", result.to_dict())
        if result.training_available:
            self.assertEqual(result.status, RuntimeAvailability.AVAILABLE.value)
        else:
            self.assertNotEqual(result.status, RuntimeAvailability.AVAILABLE.value)


class TestPhase8ModelCompatibility(unittest.TestCase):
    def test_no_compatible_model_without_path_or_approval(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("MODEL_PATH", "MODEL_NAME", "MODEL_DOWNLOAD_APPROVED"):
                os.environ.pop(k, None)
            checker = ModelCompatibilityChecker()
            report = checker.check(
                config=TrainingConfig(base_model="some/hub-model", method="lora"),
                dataset_rows=_rows(3),
            )
            self.assertTrue(report["blocked"])
            self.assertTrue((report.get("details") or {}).get("no_compatible_model") or report["reasons"])


class TestPhase8SecretFiltering(unittest.TestCase):
    def test_secrets_never_train(self):
        s = TrainingDataSanitizer()
        cleaned, tags = s.sanitize_text("password=hunter2 api_key=sk-abcdef token")
        self.assertIn("[REDACTED]", cleaned)
        self.assertTrue(tags)


class TestPhase8MockVsRealSeparation(unittest.TestCase):
    def test_mock_never_marks_real(self):
        with tempfile.TemporaryDirectory() as d:
            trainer = MockModelTrainer()
            result = trainer.train(
                job_id="job-mock",
                dataset_rows=_rows(4),
                output_dir=str(Path(d) / "out"),
                config=TrainingConfig(allow_mock_backend=True),
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.is_mock)
            self.assertFalse(result.real_training)
            self.assertFalse(result.real_weight_update)

    def test_backend_select_prefers_real_when_model_ready(self):
        model = _local_tiny_model()
        if not (_runtime_available() and model):
            self.skipTest("real runtime/model unavailable in this environment")
        reg = TrainingBackendRegistry()
        reg.bootstrap_defaults()
        trainer, sel = reg.select(
            TrainingConfig(allow_mock_backend=False, method="lora", base_model=str(model))
        )
        self.assertIsNotNone(trainer)
        self.assertFalse(trainer.is_mock)
        self.assertEqual(sel.get("selected"), "transformers_lora")


class TestPhase8RealTrainingVerified(unittest.TestCase):
    def test_bounded_real_lora_when_available(self):
        model = _local_tiny_model()
        if not (_runtime_available() and model):
            self.skipTest("REAL TRAINING VERIFIED skipped — runtime or model unavailable")
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("phase8", lambda: _rows(12))
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=False,
                eval_runner=lambda suite: {"ok": True, "score": 0.9, "suite": suite},
            )
            cfg = TrainingConfig(
                method="lora",
                base_model=str(model),
                batch_size=2,
                max_runtime_seconds=300,
                allow_mock_backend=False,
                extra={"max_steps": 2, "max_seq_length": 64, "seed": 7, "license": "apache-2.0-or-upstream"},
            )
            with mock.patch.dict(
                os.environ,
                {
                    "MODEL_PATH": str(model),
                    "MODEL_NAME": str(model),
                    "MODEL_LICENSE": "apache-2.0-or-upstream",
                    "TRAINING_ALLOW_MOCK": "false",
                },
                clear=False,
            ):
                result = orch.run_cycle(owner_requested=True, activate_if_pass=True, config=cfg)
            self.assertTrue(result.get("ok"), result)
            self.assertTrue(result.get("real_training_executed") or result.get("actual_training_executed"))
            self.assertFalse(result.get("is_mock"))
            self.assertTrue(result.get("real_checkpoint_created"))
            self.assertTrue(result.get("real_evaluation_executed"))
            self.assertTrue(result.get("canary_executed"))
            self.assertTrue(result.get("model_activated"))
            cp = Path((result.get("job") or {}).get("result", {}).get("checkpoint_path") or "")
            self.assertTrue(cp.exists())
            self.assertTrue((cp / "adapter_model.safetensors").exists() or list(cp.glob("*.safetensors")))
            manifest = json.loads((cp / "adapter_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest.get("real_training"))
            self.assertFalse(manifest.get("is_mock"))


class TestPhase8OwnerAPIs(unittest.TestCase):
    def test_runtime_and_models_aliases_require_owner(self):
        from pfai.api import app

        client = TestClient(app)
        self.assertIn(client.get("/platform/runtime/status").status_code, (401, 403))
        self.assertIn(client.get("/platform/models").status_code, (401, 403))
        self.assertIn(client.post("/platform/models/x/activate").status_code, (401, 403, 404, 409, 422))


class TestPhase8DashboardLabels(unittest.TestCase):
    def test_control_center_exposes_real_labels(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(root=d, allow_mock_backend=True)
            cc = orch.control_center_status()
            self.assertIn("labels", cc)
            self.assertIn("REAL_TRAINING_AVAILABLE", cc["labels"])
            self.assertIn("REAL_TRAINING_EXECUTED", cc["labels"])
            self.assertIn("REAL_MODEL_ACTIVE", cc["labels"])


class TestPhase8CancellationAndLimits(unittest.TestCase):
    def test_cancel_and_resource_limits(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(root=d, allow_mock_backend=True)
            job = {
                "job_id": "job-cancelme",
                "state": "QUEUED",
                "created_at": 1,
                "updated_at": 1,
            }
            orch._write_job(job)
            cancelled = orch.cancel_job("job-cancelme")
            self.assertTrue(cancelled["ok"])
            self.assertEqual(cancelled["job"]["state"], "CANCELLED")
            admit = orch.resources.admit(dataset_rows=10, method="lora", running_jobs=99)
            self.assertFalse(admit["ok"])
            self.assertIn("max_concurrent_jobs", admit["reasons"])


if __name__ == "__main__":
    unittest.main()
