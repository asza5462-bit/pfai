"""PHASE 9: open-weight discovery, local transformers provider, dataset growth."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pfai.longevity.autonomous_training.dataset_quality import DatasetQualityGate
from pfai.longevity.autonomous_training.experience_seeds import approved_pfai_seed_examples
from pfai.longevity.autonomous_training.install_open_weight import install
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.open_weight_catalog import OpenWeightModelSelector
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.collector import ExperienceCollector
from pfai.longevity.autonomous_training.types import TrainingConfig
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.model_transformers_local import TransformersLocalProvider


def _distil_path() -> Path | None:
    for p in (Path("data/models/distilgpt2"), Path("/agent/pfai/pfai/app/data/models/distilgpt2")):
        if (p / "config.json").exists() and (p / "LICENSE_META.json").exists():
            meta = json.loads((p / "LICENSE_META.json").read_text(encoding="utf-8"))
            if meta.get("purpose") == "phase9_real_open_weight":
                return p.resolve()
    return None


class TestHardwareAuditHonest(unittest.TestCase):
    def test_gpu_not_faked(self):
        hw = OpenWeightModelSelector.hardware_audit()
        self.assertIn("gpu_available", hw)
        if not hw["gpu_available"]:
            self.assertIn(hw.get("vram_gb"), (None, 0, 0.0))
            self.assertEqual(hw["recommended_strategy"], "cpu_lora_small_model")


class TestInstallRequiresApprove(unittest.TestCase):
    def test_no_silent_download(self):
        with tempfile.TemporaryDirectory() as d:
            out = install(model_key="distilgpt2", dest=str(Path(d) / "m"), approve=False)
            self.assertFalse(out["ok"])
            self.assertEqual(out["status"], "APPROVAL_REQUIRED")


class TestOpenWeightDiscovery(unittest.TestCase):
    def test_tiny_classified_test_only(self):
        tiny = Path("data/models/tiny-random-gpt2")
        if not tiny.exists():
            self.skipTest("tiny model absent")
        dm = OpenWeightModelSelector().inspect(tiny, probe_load=False)
        self.assertTrue(dm.is_test_only)
        self.assertEqual(dm.status, "TEST_ONLY")

    def test_distil_selected_when_installed(self):
        path = _distil_path()
        if not path:
            self.skipTest("distilgpt2 not installed")
        sel = OpenWeightModelSelector(search_roots=[path.parent]).select_production_candidate(probe_load=False)
        self.assertTrue(sel["ok"])
        self.assertEqual(sel["status"], "LOCAL_MODEL_AVAILABLE")
        self.assertIn("distilgpt2", sel["selected"]["path"])


class TestTransformersLocalProvider(unittest.TestCase):
    def test_missing_path(self):
        p = TransformersLocalProvider(model_path="/no/such/model")
        st = p.ensure_loaded()
        self.assertFalse(st["ok"])
        self.assertEqual(st["status"], "MODEL_NOT_INSTALLED")

    def test_load_and_generate_when_available(self):
        path = _distil_path()
        if not path:
            self.skipTest("distilgpt2 not installed")
        p = TransformersLocalProvider(model_path=str(path), max_new_tokens=8)
        st = p.ensure_loaded()
        self.assertTrue(st["ok"], st)
        text = p.generate("Hello")
        self.assertIsInstance(text, str)
        self.assertFalse(text.startswith("[MODEL_UNAVAILABLE"))


class TestProviderRegistryTransformersLocal(unittest.TestCase):
    def test_registered(self):
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        ids = [p.provider_id for p in reg.list_providers()]
        self.assertIn("transformers_local", ids)
        path = _distil_path()
        if not path:
            self.skipTest("distilgpt2 not installed")
        prov = reg.create("transformers_local", model_path=str(path), max_new_tokens=4)
        self.assertEqual(prov.kind, "transformers_local")


class TestExperienceSeedsAndQuality(unittest.TestCase):
    def test_seeds_pass_gate(self):
        rows = approved_pfai_seed_examples()
        self.assertGreaterEqual(len(rows), 20)
        gate = DatasetQualityGate(min_samples=20)
        report = gate.evaluate(rows)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["status"], "DATASET_READY")
        self.assertFalse(report["model_quality_claim"])

    def test_insufficient(self):
        gate = DatasetQualityGate(min_samples=50)
        report = gate.evaluate(approved_pfai_seed_examples()[:3])
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")


class TestSecurityBoundary(unittest.TestCase):
    def test_training_cannot_modify_auth(self):
        iso = TrainingSafetyIsolation()
        bad = iso.guard_training_request({"modify_authentication": True, "role": "admin"})
        self.assertFalse(bad["ok"])


class TestPhase9RealTrainingOptional(unittest.TestCase):
    def test_bounded_real_lora_on_distil(self):
        path = _distil_path()
        if not path:
            self.skipTest("REAL model not installed — MODEL_NOT_INSTALLED")
        # Skip if torch unavailable
        try:
            import torch  # noqa: F401
        except Exception:
            self.skipTest("torch missing")
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("approved_seed", approved_pfai_seed_examples)
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=False,
                eval_runner=lambda suite: {"ok": True, "score": 0.9, "suite": suite},
            )
            cfg = TrainingConfig(
                method="lora",
                base_model=str(path),
                batch_size=1,
                max_runtime_seconds=600,
                allow_mock_backend=False,
                extra={"max_steps": 2, "max_seq_length": 64, "seed": 9, "license": "apache-2.0", "lora_r": 4},
            )
            with mock.patch.dict(
                os.environ,
                {"MODEL_PATH": str(path), "MODEL_NAME": str(path), "MODEL_LICENSE": "apache-2.0", "TRAINING_MIN_SAMPLES": "20"},
                clear=False,
            ):
                result = orch.run_cycle(owner_requested=True, activate_if_pass=True, config=cfg)
            self.assertTrue(result.get("ok"), result)
            self.assertTrue(result.get("real_training_executed"))
            self.assertFalse(result.get("is_mock"))
            self.assertTrue(orch.models.last_known_good())
            # Must not claim production quality
            self.assertFalse(result.get("production_scale_training", False))


if __name__ == "__main__":
    unittest.main()
