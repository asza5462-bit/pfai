"""PHASE 8 hardening: LKG, rollback, dataset gates, resources, isolation."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from pfai.longevity.autonomous_training.active_runtime import ActiveModelRuntime
from pfai.longevity.autonomous_training.collector import ExperienceCollector
from pfai.longevity.autonomous_training.dataset_quality import DatasetQualityGate
from pfai.longevity.autonomous_training.evaluation_gate import EvaluationGate
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.model_registry import ModelRegistry
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.resources import TrainingResourceManager
from pfai.longevity.autonomous_training.runtime_detector import TrainingRuntimeDetector
from pfai.longevity.autonomous_training.trainer import TrainingBackendRegistry
from pfai.longevity.autonomous_training.types import ModelStatus, TrainingConfig


def _rows(n: int = 10):
    return [
        {
            "instruction": f"Describe continuous improvement pattern {i}",
            "response": f"Pattern {i}: version datasets, train adapters, evaluate, canary, then activate only if gates pass. " * 2,
            "source": "phase8h",
            "source_id": f"p8h-{i}",
            "verified": True,
        }
        for i in range(n)
    ]


class TestDatasetQualityGates(unittest.TestCase):
    def test_insufficient_and_ready(self):
        gate = DatasetQualityGate(min_samples=5, min_train=2, min_avg_quality=0.5)
        bad = gate.evaluate(_rows(2))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], "INSUFFICIENT_DATA")
        self.assertFalse(bad["model_quality_claim"])
        good = gate.evaluate(_rows(10))
        self.assertTrue(good["ok"], good)
        self.assertIn("train", good["splits"])
        self.assertGreaterEqual(good["splits"]["validation"], 1)
        self.assertGreaterEqual(good["splits"]["test"], 1)


class TestModelVersioningAndLKG(unittest.TestCase):
    def test_immutable_version_and_first_lkg(self):
        with tempfile.TemporaryDirectory() as d:
            reg = ModelRegistry(d)
            m1 = reg.register(
                base_model="base-a",
                dataset_version="dataset-v0001",
                training_config={"epochs": 1},
                checkpoint_ref=str(Path(d) / "cp1"),
                training_backend="mock",
                metrics={"loss": 1.0},
                status=ModelStatus.CANDIDATE,
            )
            Path(m1["checkpoint_ref"]).mkdir()
            (Path(m1["checkpoint_ref"]) / "adapter_manifest.json").write_text("{}", encoding="utf-8")
            act = reg.activate(m1["model_id"])
            self.assertEqual(act["model_id"], m1["model_id"])
            lkg = reg.last_known_good()
            self.assertIsNotNone(lkg)
            self.assertEqual(lkg["model_id"], m1["model_id"])
            # Second model preserves first as LKG
            m2 = reg.register(
                base_model="base-a",
                dataset_version="dataset-v0002",
                training_config={"epochs": 1},
                checkpoint_ref=str(Path(d) / "cp2"),
                training_backend="mock",
                parent_model_id=m1["model_id"],
            )
            Path(m2["checkpoint_ref"]).mkdir()
            (Path(m2["checkpoint_ref"]) / "adapter_manifest.json").write_text("{}", encoding="utf-8")
            reg.activate(m2["model_id"])
            lkg2 = reg.last_known_good()
            self.assertEqual(lkg2["model_id"], m1["model_id"])
            self.assertEqual(reg.active()["model_id"], m2["model_id"])
            # Immutability
            with self.assertRaises(RuntimeError):
                reg.register(
                    base_model="x",
                    dataset_version="d",
                    training_config={},
                    checkpoint_ref="c",
                    model_id=m1["model_id"],
                )


class TestAutomaticRollback(unittest.TestCase):
    def test_activate_monitor_rollback_to_lkg(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("unit", lambda: _rows(10))
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=True,
                eval_runner=lambda suite: {"ok": True, "score": 0.85, "suite": suite},
            )
            r1 = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True, base_model="tiny-a"),
                activate_if_pass=True,
            )
            self.assertTrue(r1["ok"], r1)
            self.assertTrue(r1.get("lkg_available"))
            first = orch.models.active()["model_id"]
            self.assertEqual(orch.models.last_known_good()["model_id"], first)
            r2 = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True, base_model="tiny-b"),
                activate_if_pass=True,
            )
            self.assertTrue(r2["ok"], r2)
            second = orch.models.active()["model_id"]
            self.assertNotEqual(first, second)
            self.assertEqual(orch.models.last_known_good()["model_id"], first)
            rb = orch.monitor_and_maybe_rollback(force_regression=True)
            self.assertTrue(rb.get("ok"), rb)
            self.assertEqual(rb.get("action"), "rollback")
            self.assertEqual(orch.models.active()["model_id"], first)
            self.assertEqual(orch.active_runtime.current()["model_id"], first)
            # LKG checkpoint must still exist
            cp = orch.models.get(first)["checkpoint_ref"]
            self.assertTrue(Path(cp).exists())


class TestRejectionKeepsLKG(unittest.TestCase):
    def test_failed_gates_reject(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("unit", lambda: _rows(10))
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=True,
                eval_runner=lambda suite: {"ok": False, "score": 0.1, "suite": suite},
            )
            # Seed an LKG via a permissive gate first
            orch.gates = EvaluationGate(eval_runner=lambda suite: {"ok": True, "score": 0.9, "suite": suite})
            ok = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True),
                activate_if_pass=True,
            )
            self.assertTrue(ok["ok"])
            lkg_id = orch.models.active()["model_id"]
            # Now fail gates
            orch.gates = EvaluationGate(
                eval_runner=lambda suite: {"ok": False, "score": 0.05, "suite": suite},
                gates={"min_overall_score": 0.99, "max_regression": 0.0},
            )
            bad = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True),
                activate_if_pass=True,
            )
            self.assertEqual(bad.get("status"), "REJECTED")
            self.assertEqual(orch.models.active()["model_id"], lkg_id)


class TestActiveRuntimeReload(unittest.TestCase):
    def test_reload_and_corrupt_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            rt = ActiveModelRuntime(str(Path(d) / "active.json"))
            cp1 = Path(d) / "cp1"
            cp1.mkdir()
            (cp1 / "adapter_manifest.json").write_text("{}", encoding="utf-8")
            cp2 = Path(d) / "cp2"
            cp2.mkdir()
            (cp2 / "adapter_manifest.json").write_text("{}", encoding="utf-8")
            rt.switch_to(model_id="m1", checkpoint_ref=str(cp1), base_model="base")
            rt.switch_to(model_id="m2", checkpoint_ref=str(cp2), base_model="base")
            reloaded = rt.reload()
            self.assertTrue(reloaded["ok"])
            # Corrupt current checkpoint
            for f in cp2.iterdir():
                f.unlink()
            cp2.rmdir()
            fb = rt.reload()
            self.assertTrue(fb.get("ok"), fb)
            self.assertEqual(rt.current()["model_id"], "m1")


class TestResourcesAndStaleJobs(unittest.TestCase):
    def test_cpu_limits_and_cleanup_protects_lkg(self):
        mgr = TrainingResourceManager()
        admit = mgr.admit(dataset_rows=10, method="lora", running_jobs=0)
        self.assertIn("device", admit)
        self.assertIn(admit["device"], ("cpu", "cuda"))
        if not admit["probe_summary"]["gpu_available"]:
            self.assertEqual(admit["device"], "cpu")
            self.assertFalse(admit["limits"]["gpu_available"])
            # Honest: do not invent VRAM when GPU absent
            self.assertTrue(admit["probe_summary"].get("vram_gb") in (None, 0, 0.0))
        with tempfile.TemporaryDirectory() as d:
            arts = Path(d) / "artifacts"
            arts.mkdir()
            protect = arts / "keep"
            protect.mkdir()
            (protect / "x").write_text("1", encoding="utf-8")
            old = arts / "old"
            old.mkdir()
            (old / "y").write_text("1", encoding="utf-8")
            time.sleep(0.01)
            new = arts / "new"
            new.mkdir()
            (new / "z").write_text("1", encoding="utf-8")
            mgr.max_non_lkg_checkpoints = 1
            out = mgr.cleanup_old_checkpoints(arts, protect_paths={str(protect.resolve())})
            self.assertTrue(protect.exists())
            self.assertIn(str(protect.resolve()), out["kept_protected"])

    def test_stale_job_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(root=d, allow_mock_backend=True)
            job = {
                "job_id": "job-stale1",
                "state": "TRAINING",
                "created_at": time.time() - 10000,
                "updated_at": time.time() - 10000,
            }
            orch.STALE_RUNNING_SECONDS = 1
            orch._write_job(job)
            fixed = orch.reconcile_stale_jobs()
            self.assertIn("job-stale1", fixed)
            self.assertEqual(orch._read_job("job-stale1")["state"], "FAILED")


class TestAutonomousTickNotChat(unittest.TestCase):
    def test_tick_without_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("few", lambda: _rows(1))
            orch = AutonomousTrainingOrchestrator(
                root=d, collector=collector, allow_mock_backend=True
            )
            tick = orch.maybe_run_autonomous_tick()
            self.assertIn(tick.get("status"), ("TRIGGER_NOT_MET", "INSUFFICIENT_DATA", "INSUFFICIENT_TRAIN_SPLIT"))
            self.assertFalse(tick.get("trained"))


class TestBackendNeverSilentMock(unittest.TestCase):
    def test_real_unavailable_not_mock(self):
        reg = TrainingBackendRegistry()
        reg.bootstrap_defaults()
        trainer, sel = reg.select(TrainingConfig(allow_mock_backend=False, base_model="local"))
        self.assertIsNone(trainer)
        self.assertIn(sel.get("status"), ("TRAINING_RUNTIME_UNAVAILABLE", "NO_COMPATIBLE_MODEL"))


class TestSecurityIsolationPaths(unittest.TestCase):
    def test_cannot_target_auth_paths(self):
        iso = TrainingSafetyIsolation()
        with tempfile.TemporaryDirectory() as d:
            bad = iso.assert_artifact_path_allowed(str(Path(d) / "owner" / "x"), training_root=d)
            # path contains owner component
            self.assertFalse(bad["ok"])
            good_root = Path(d) / "training"
            good_root.mkdir()
            ok = iso.assert_artifact_path_allowed(str(good_root / "artifacts" / "a"), training_root=str(good_root))
            self.assertTrue(ok["ok"])
            blocked = iso.guard_training_request({"modify_authorization": True, "role": "admin"})
            self.assertFalse(blocked["ok"])


class TestControlCenterLabels(unittest.TestCase):
    def test_labels_include_lkg_and_autonomous(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(root=d, allow_mock_backend=True)
            cc = orch.control_center_status()
            labels = cc["labels"]
            for key in (
                "REAL_TRAINING_AVAILABLE",
                "LKG_AVAILABLE",
                "ROLLBACK_AVAILABLE",
                "AUTONOMOUS_TRAINING_READY",
            ):
                self.assertIn(key, labels)
            self.assertIn("quality_disclaimer", cc)


if __name__ == "__main__":
    unittest.main()
