"""Tests for legitimate Phase 10 dataset growth via real experience wiring."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.verified_outcomes import VerifiedOutcomeStore


class TestRealGrowthWiring(unittest.TestCase):
    def test_verified_outcome_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = VerifiedOutcomeStore(d)
            store.append(
                {
                    "kind": "coding_passed",
                    "instruction": "Return 1 from answer().",
                    "response": "def answer():\n    return 1\n",
                    "id": "t1",
                }
            )
            items = store.list_passed_exercises()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], "t1")

    def test_bridge_mirrors_code_pass_to_outcome_store(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=True, include_approved_seeds=False
            )
            rec = orch.experience.record_code_test_pass(
                instruction="Implement answer() returning 21 for a verified sandbox pass?",
                code="def answer():\n    return 21\n",
                source_id="wire-test-1",
            )
            self.assertEqual(rec.get("eligibility"), "ACCEPTED")
            items = orch.verified_outcomes.list_passed_exercises()
            self.assertTrue(any(i.get("source_id") == "wire-test-1" or i.get("id") == "wire-test-1" for i in items))

    def test_build_preserves_prior_dataset_examples(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, allow_mock_backend=True, include_approved_seeds=False
            )
            for i in range(8):
                orch.experience.record_owner_feedback(
                    instruction=f"What is prior dataset preservation rule {i}?",
                    response=(
                        f"Rule {i}: when building a new dataset version, merge prior "
                        "immutable examples with newly accepted candidates and dedupe."
                    ),
                    approved=True,
                    source_id=f"prior-{i}",
                )
            first = orch.build_dataset_from_sources()
            self.assertTrue(first.get("ok") and first.get("created"), first)
            first_id = first["manifest"]["dataset_id"]
            first_n = int(first["accepted"])
            orch.experience.record_code_test_pass(
                instruction="Implement answer() returning 99 after prior version exists?",
                code="def answer():\n    return 99\n",
                source_id="growth-1",
            )
            second = orch.build_dataset_from_sources()
            self.assertTrue(second.get("ok") and second.get("created"), second)
            self.assertNotEqual(second["manifest"]["dataset_id"], first_id)
            self.assertGreaterEqual(int(second["accepted"]), first_n + 1)
            self.assertGreaterEqual(int(second.get("new_since_last_dataset") or 0), 1)

    def test_phase9_lineage_has_v0003_and_lkg(self):
        root = Path("data/longevity/training_phase9_verify")
        if not (root / "datasets" / "dataset-v0003").exists():
            self.skipTest("dataset-v0003 not present")
        self.assertTrue((root / "datasets" / "dataset-v0002").exists())
        orch = AutonomousTrainingOrchestrator(
            root=str(root), allow_mock_backend=False, include_approved_seeds=False
        )
        lkg = orch.models.last_known_good()
        self.assertEqual(lkg.get("model_id"), "model-v0001")
        active = orch.models.active()
        # After real training, active may be newer candidate; LKG stays v0001
        self.assertIsNotNone(active)
        ver = orch.pipeline_verification_status()
        self.assertEqual(ver.get("dataset_version"), "dataset-v0003")
        self.assertGreaterEqual(int(ver.get("dataset_accepted_examples") or 0), 67)


if __name__ == "__main__":
    unittest.main()
