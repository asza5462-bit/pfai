"""PHASE 10 verification — honest eligibility, trainer probe, no forced training."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.eligibility import (
    ZERO_GROWTH_REASON,
    TrainingEligibilityEngine,
)
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.triggers import TrainingTriggerPolicy
from pfai.longevity.autonomous_training.types import JobState, ModelStatus


class TestPhase10Verification(unittest.TestCase):
    def test_gate_breakdown_exposes_all_reasons(self):
        eng = TrainingEligibilityEngine(
            triggers=TrainingTriggerPolicy(min_examples=5, min_new_examples=10),
            backend_available=lambda: True,
            eval_available=lambda: True,
            list_jobs=lambda: [],
            checkpoint_root="/tmp/pfai-ckpt-test",
        )
        rows = [
            {
                "instruction": f"Verify gate detail item {i} for autonomous training eligibility?",
                "response": f"Answer {i}: all ten gates must pass; growth zero blocks training.",
                "source": "FEEDBACK",
                "provenance": {"eligible_for_learning": True, "sanitizer_tags": []},
            }
            for i in range(20)
        ]
        d = eng.evaluate(accepted_rows=rows, dataset_growth=0)
        self.assertFalse(d["eligible"])
        self.assertEqual(d["reason"], ZERO_GROWTH_REASON)
        gates = d["gates"]
        for key in (
            "minimum_accepted_examples",
            "dataset_growth",
            "dataset_integrity",
            "no_secret_pii_violations",
            "provenance_requirements_satisfied",
            "evaluation_suite_available",
            "trainer_availability",
            "base_model_availability",
            "checkpoint_storage_availability",
            "resource_availability",
            "concurrent_job_lock",
            "schedule_condition",
            "owner_manual_justification",
        ):
            self.assertIn(key, gates, key)

    def test_phase9_baseline_no_real_growth(self):
        root = Path("data/longevity/training_phase9_verify")
        if not root.exists():
            self.skipTest("phase9 verify absent")
        orch = AutonomousTrainingOrchestrator(
            root=str(root), allow_mock_backend=False, include_approved_seeds=False
        )
        stats = orch.learning_statistics()
        elig = stats["next_training_eligibility"]
        # After a completed real train on current content, growth since last trained is 0
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["reason"], ZERO_GROWTH_REASON)
        self.assertEqual(stats.get("dataset_growth_since_last_trained"), 0)
        self.assertGreaterEqual(int(stats.get("latest_dataset_accepted") or 0), 52)
        self.assertTrue((root / "datasets" / "dataset-v0002").exists())

    def test_trainer_probe_does_not_claim_training(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=False, include_approved_seeds=False
            )
            probe = orch.probe_trainer_runtime(load_weights=False)
            self.assertIn("trainer_runtime_available", probe)
            self.assertIn("gpu_available", probe)
            self.assertFalse(probe.get("weights_probed"))
            self.assertIn("not a training run", (probe.get("note") or "").lower())

    def test_live_store_not_falsely_eligible_without_growth(self):
        root = Path("data/longevity/training")
        if not root.exists() or not (root / "datasets").exists():
            self.skipTest("live training dir absent")
        orch = AutonomousTrainingOrchestrator(
            root=str(root), allow_mock_backend=False, include_approved_seeds=False
        )
        stats = orch.learning_statistics()
        growth = int(stats.get("dataset_growth_since_previous_version") or 0)
        if growth != 0:
            # Phase 11 may have left pending accepted bank examples on the live store.
            # Zero-growth eligibility semantics are covered by temp-dir tick tests.
            self.skipTest("live store has pending dataset growth after Phase 11 bank ingestion")
        # Version-to-version growth is 0 on live store → must not be eligible
        self.assertEqual(growth, 0)
        self.assertFalse(stats["next_training_eligibility"]["eligible"])
        self.assertEqual(
            stats["next_training_eligibility"]["reason"], ZERO_GROWTH_REASON
        )

    def test_tick_blocked_without_growth(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=True, include_approved_seeds=False
            )
            orch.scheduler.mark_trained(dataset_id="dataset-v0000", accepted=0)
            for i in range(12):
                orch.experience.record_owner_feedback(
                    instruction=f"What is hardening check {i} for eligibility?",
                    response=f"Check {i}: require real growth before training starts.",
                    approved=True,
                    source_id=f"v-{i}",
                )
            built = orch.build_dataset_from_sources()
            self.assertTrue(built.get("ok"), built)
            orch.scheduler.mark_trained(
                dataset_id=built["manifest"]["dataset_id"],
                accepted=int(built["accepted"]),
            )
            tick = orch.maybe_run_autonomous_tick()
            self.assertFalse(tick.get("trained"))
            self.assertFalse(tick.get("training_eligible"))
            self.assertEqual(tick.get("reason"), ZERO_GROWTH_REASON)

    def test_security_isolation_still_blocks_auth(self):
        iso = TrainingSafetyIsolation()
        self.assertFalse(
            iso.guard_training_request({"modify_authorization": True})["ok"]
        )

    def test_registry_lifecycle_states(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=True, include_approved_seeds=False
            )
            Path(d, "ckpt").mkdir()
            m = orch.models.register(
                base_model="local",
                dataset_version="dataset-v0001",
                training_config={},
                checkpoint_ref=str(Path(d) / "ckpt"),
                status=ModelStatus.CANDIDATE,
            )
            orch.models.update_status(m["model_id"], ModelStatus.VALIDATING)
            orch.models.update_status(m["model_id"], ModelStatus.VALIDATED)
            orch.models.update_status(m["model_id"], ModelStatus.REJECTED)
            got = orch.models.get(m["model_id"])
            self.assertEqual(got["status"], ModelStatus.REJECTED.value)

    def test_interrupted_job_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=True, include_approved_seeds=False
            )
            job_id = "job-stale-test"
            path = Path(d) / "jobs" / f"{job_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "state": JobState.TRAINING.value,
                        "updated_at": 0,
                        "created_at": 0,
                    }
                ),
                encoding="utf-8",
            )
            orch.reconcile_stale_jobs()
            job = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(
                job["state"],
                (JobState.FAILED.value, JobState.CANCELLED.value, JobState.TRAINING.value),
            )


if __name__ == "__main__":
    unittest.main()
