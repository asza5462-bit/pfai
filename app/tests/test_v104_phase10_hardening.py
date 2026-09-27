"""PHASE 10 — autonomous learning/training production hardening."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.eligibility import TrainingEligibilityEngine
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.resources import TrainingResourceManager
from pfai.longevity.autonomous_training.runtime_detector import TrainingRuntimeDetector
from pfai.longevity.autonomous_training.scheduler import (
    DurableTrainingScheduler,
    normalize_job_lifecycle_state,
)
from pfai.longevity.autonomous_training.triggers import TrainingTriggerPolicy
from pfai.longevity.autonomous_training.types import JobState, ModelStatus


def _row(i: int) -> dict:
    return {
        "instruction": f"What is Phase 10 hardening rule {i} for PFAI autonomous training?",
        "response": (
            f"Rule {i}: require growth, quality, provenance, backend, resources, and "
            "a justified trigger before any batch training job starts."
        ),
        "source": "FEEDBACK",
        "source_id": f"p10-{i}",
        "verified": True,
        "provenance": {
            "eligible_for_learning": True,
            "attribution": "FEEDBACK",
            "sanitizer_tags": [],
            "synthetic": False,
        },
    }


class TestEligibilityEngine(unittest.TestCase):
    def test_zero_growth_blocks(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=10),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [],
        )
        rows = [_row(i) for i in range(20)]
        d = eng.evaluate(accepted_rows=rows, dataset_growth=0)
        self.assertFalse(d["eligible"])
        self.assertEqual(d["reason"], "NO_NEW_DATASET_GROWTH")
        self.assertEqual(d["status"], "TRAINING_BLOCKED")

    def test_min_examples_alone_insufficient(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=10),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [],
        )
        rows = [_row(i) for i in range(12)]
        d = eng.evaluate(accepted_rows=rows, dataset_growth=0)
        self.assertFalse(d["eligible"])
        self.assertIn("NO_NEW_DATASET_GROWTH", d["blockers"])

    def test_growth_trigger_can_pass_other_gates(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=10),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [],
        )
        rows = [_row(i) for i in range(20)]
        d = eng.evaluate(accepted_rows=rows, dataset_growth=12)
        self.assertTrue(d["eligible"], d)
        self.assertEqual(d["reason"], "ELIGIBLE")

    def test_owner_can_bypass_growth_but_not_quality(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=10),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [],
        )
        d = eng.evaluate(
            accepted_rows=[_row(i) for i in range(12)],
            dataset_growth=0,
            owner_requested=True,
        )
        self.assertTrue(d["eligible"], d)
        self.assertNotIn("NO_NEW_DATASET_GROWTH", d.get("blockers") or [])

    def test_conflicting_job_blocks(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=5),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [{"job_id": "job-1", "state": JobState.TRAINING.value}],
        )
        d = eng.evaluate(accepted_rows=[_row(i) for i in range(12)], dataset_growth=10)
        self.assertFalse(d["eligible"])
        self.assertIn("CONFLICTING_TRAINING_JOB", d["blockers"])

    def test_backend_unavailable_blocks(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=5),
            backend_available=lambda: False,
            eval_available=lambda: True,
            list_jobs=lambda: [],
        )
        d = eng.evaluate(accepted_rows=[_row(i) for i in range(12)], dataset_growth=10)
        self.assertFalse(d["eligible"])
        self.assertIn("TRAINING_BACKEND_UNAVAILABLE", d["blockers"])


class TestDurableScheduler(unittest.TestCase):
    def test_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            s1 = DurableTrainingScheduler(d)
            s1.mark_trained(dataset_id="dataset-v0002", accepted=52, job_id="job-x")
            s2 = DurableTrainingScheduler(d)
            st = s2.status()
            self.assertEqual(st["last_trained_dataset_id"], "dataset-v0002")
            self.assertEqual(st["last_trained_accepted"], 52)
            self.assertEqual(s2.growth_since_last_trained(52), 0)
            self.assertEqual(s2.growth_since_last_trained(60), 8)

    def test_duplicate_job_prevention(self):
        with tempfile.TemporaryDirectory() as d:
            s = DurableTrainingScheduler(
                d,
                list_jobs=lambda: [{"job_id": "j1", "state": JobState.RUNNING.value}],
            )
            self.assertTrue(s.has_conflicting_job())

    def test_lifecycle_normalization(self):
        self.assertEqual(normalize_job_lifecycle_state("TRAINING"), "RUNNING")
        self.assertEqual(normalize_job_lifecycle_state("ACTIVE"), "ACCEPTED")
        self.assertEqual(normalize_job_lifecycle_state("REJECTED"), "REJECTED")


class TestOrchestratorPhase10(unittest.TestCase):
    def test_tick_reports_no_new_growth(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            # Seed baseline as already trained
            orch.scheduler.mark_trained(dataset_id="dataset-v0000", accepted=0)
            for i in range(12):
                orch.experience.record_owner_feedback(
                    instruction=_row(i)["instruction"],
                    response=_row(i)["response"],
                    approved=True,
                    source_id=f"t-{i}",
                )
            # First build creates dataset and may train if growth from 0 — mark trained after
            built = orch.build_dataset_from_sources()
            self.assertTrue(built.get("ok"), built)
            orch.scheduler.mark_trained(
                dataset_id=built["manifest"]["dataset_id"],
                accepted=int(built["accepted"]),
            )
            orch.autonomous_enabled = True
            tick = orch.maybe_run_autonomous_tick()
            self.assertFalse(tick.get("trained"))
            self.assertFalse(tick.get("training_eligible"))
            self.assertEqual(tick.get("reason"), "NO_NEW_DATASET_GROWTH")

    def test_verification_and_stats(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            ver = orch.pipeline_verification_status()
            self.assertTrue(ver["implemented"])
            self.assertFalse(ver["model_quality_production_validated"])
            self.assertFalse(ver["per_chat_training"])
            self.assertIn("training_eligibility_reason", ver)
            stats = orch.learning_statistics()
            self.assertIn("next_training_eligibility", stats)
            self.assertIn("scheduler", stats)

    def test_security_isolation(self):
        iso = TrainingSafetyIsolation()
        self.assertFalse(
            iso.guard_training_request({"modify_authorization": True})["ok"]
        )

    def test_cpu_honest(self):
        probe = TrainingRuntimeDetector().detect().to_dict()
        self.assertIn("gpu_available", probe)
        if not probe["gpu_available"]:
            self.assertIn(probe.get("vram_gb"), (None, 0, 0.0))

    def test_lkg_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            lkg = orch.models.register(
                base_model="local",
                dataset_version="dataset-v0001",
                training_config={},
                checkpoint_ref=str(Path(d) / "ckpt"),
                status=ModelStatus.CANDIDATE,
            )
            Path(d, "ckpt").mkdir(parents=True, exist_ok=True)
            orch.models.mark_lkg(lkg["model_id"], reason="p10")
            cand = orch.models.register(
                base_model="local",
                dataset_version="dataset-v0002",
                training_config={},
                checkpoint_ref=str(Path(d) / "ckpt2"),
                status=ModelStatus.CANDIDATE,
            )
            orch.models.update_status(cand["model_id"], ModelStatus.REJECTED)
            self.assertEqual(orch.models.last_known_good()["model_id"], lkg["model_id"])

    def test_phase9_artifacts_still_present(self):
        root = Path("data/longevity/training_phase9_verify")
        if not root.exists():
            self.skipTest("phase9 verify absent")
        ar = json.loads((root / "active_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(ar.get("model_id"), "model-v0001")
        self.assertTrue((Path(ar["checkpoint_ref"]) / "adapter_model.safetensors").exists())


if __name__ == "__main__":
    unittest.main()
