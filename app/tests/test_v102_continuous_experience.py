"""Continuous real experience collection — no synthetic inflation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.experience_bridge import ContinuousExperienceBridge
from pfai.longevity.autonomous_training.learning_candidate import LearningCandidatePipeline
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.types import ExperienceSource, LearningEligibility


class _FakeOrch:
    def __init__(self, root: str):
        self.learning_pipeline_gate = LearningCandidatePipeline(root=str(Path(root) / "cands"))
        self.audit = type("A", (), {"record": staticmethod(lambda *a, **k: None)})()


class TestExperienceBridgeEligibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = ContinuousExperienceBridge(_FakeOrch(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_code_pass_creates_candidate(self):
        out = self.bridge.record_code_test_pass(
            instruction="Write a function that adds two numbers and return the sum.",
            code=(
                "def add(a, b):\n"
                "    \"\"\"Return the sum of a and b for verified coding tasks.\"\"\"\n"
                "    return a + b\n"
            ),
            source_id="ex-1",
        )
        self.assertEqual(out["eligibility"], LearningEligibility.ACCEPTED.value)
        self.assertFalse(out.get("trained"))

    def test_unsuccessful_task_ineligible(self):
        out = self.bridge.record_event(
            instruction="Do the task",
            response="I failed",
            attribution=ExperienceSource.TASK_SUCCESS.value,
            success=False,
            verified=False,
        )
        self.assertEqual(out["eligibility"], LearningEligibility.INELIGIBLE.value)

    def test_correction_requires_tests_passed(self):
        out = self.bridge.record_corrected_failure(
            instruction="Fix the bug in the parser so invalid tokens raise ValueError.",
            corrected_response="raise ValueError('bad token') when the lexer sees an unknown symbol.",
            tests_passed=False,
        )
        self.assertEqual(out["eligibility"], LearningEligibility.INELIGIBLE.value)
        out2 = self.bridge.record_corrected_failure(
            instruction="Fix the bug in the parser so invalid tokens raise ValueError.",
            corrected_response=(
                "When the lexer sees an unknown symbol, raise ValueError('bad token') "
                "and stop parsing so callers can handle the failure."
            ),
            tests_passed=True,
            source_id="fix-1",
        )
        self.assertEqual(out2["eligibility"], LearningEligibility.ACCEPTED.value)

    def test_raw_chat_never_trained(self):
        out = self.bridge.record_raw_chat_attempt(
            instruction="hello",
            response="hi there",
        )
        self.assertEqual(out["eligibility"], LearningEligibility.INELIGIBLE.value)
        self.assertEqual(out["reason"], "raw_chat_never_trained")

    def test_secrets_rejected(self):
        out = self.bridge.record_code_test_pass(
            instruction="Store the password for the database connection string.",
            code="password: hunter2-secret and api_key: sk-abcdef1234567890",
            source_id="sec-1",
        )
        self.assertEqual(out["eligibility"], LearningEligibility.REJECTED.value)

    def test_tool_success_with_secret_payload_ineligible(self):
        out = self.bridge.record_tool_success(
            instruction="Run the export tool",
            result_summary="Exported 3 rows successfully for the owner report.",
            raw_payload={"success": True, "secret": "x"},
        )
        self.assertEqual(out["eligibility"], LearningEligibility.INELIGIBLE.value)

    def test_provenance_on_accept(self):
        out = self.bridge.record_owner_feedback(
            instruction="How should PFAI label verified coding solutions for learning?",
            response=(
                "Only solutions that passed sandbox tests become CODE_TEST_PASS candidates "
                "with provenance and eligibility metadata attached."
            ),
            approved=True,
            source_id="fb-1",
        )
        self.assertEqual(out["eligibility"], LearningEligibility.ACCEPTED.value)
        item = self.bridge._pipeline().store.get(out["candidate_id"])
        self.assertTrue(item["provenance"].get("eligible_for_learning"))
        self.assertEqual(item["provenance"].get("attribution"), ExperienceSource.FEEDBACK.value)
        self.assertFalse(item["provenance"].get("synthetic"))


class TestDatasetVersionOnChange(unittest.TestCase):
    def test_version_only_when_data_changes(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            for i in range(12):
                orch.experience.record_owner_feedback(
                    instruction=f"What is a safe continuous learning rule number {i} for PFAI?",
                    response=(
                        f"Rule {i}: only verified operational outcomes enter the LearningCandidate "
                        "pipeline after sanitization, quality checks, and provenance tagging."
                    ),
                    approved=True,
                    source_id=f"r-{i}",
                )
            first = orch.build_dataset_from_sources()
            self.assertTrue(first["ok"], first)
            self.assertTrue(first.get("created"))
            ds1 = first["manifest"]["dataset_id"]
            second = orch.build_dataset_from_sources()
            self.assertTrue(second["ok"], second)
            self.assertTrue(second.get("unchanged"))
            self.assertFalse(second.get("created"))
            self.assertEqual(second["manifest"]["dataset_id"], ds1)
            versions = orch.datasets.list_versions(limit=10)
            self.assertEqual(len(versions), 1)

    def test_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            kwargs = dict(
                instruction="Explain continuous experience collection eligibility for PFAI.",
                response=(
                    "Successful verified tasks may become candidates; raw chats and secrets never do."
                ),
                approved=True,
                source_id="dup-a",
            )
            a = orch.experience.record_owner_feedback(**kwargs)
            b = orch.experience.record_owner_feedback(**{**kwargs, "source_id": "dup-b"})
            self.assertEqual(a["eligibility"], LearningEligibility.ACCEPTED.value)
            self.assertEqual(b["eligibility"], LearningEligibility.REJECTED.value)
            self.assertEqual(b.get("rejection_reason"), "duplicate")

    def test_insufficient_real_data_prevents_training(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            orch.autonomous_enabled = True
            tick = orch.maybe_run_autonomous_tick()
            self.assertFalse(tick.get("trained"))
            self.assertIn(
                tick.get("status"),
                (
                    "INSUFFICIENT_REAL_DATA",
                    "INSUFFICIENT_DATA",
                    "DATASET_INVALID",
                    "TRIGGER_NOT_MET",
                ),
            )

    def test_tick_safe_and_lkg_protected(self):
        from pfai.longevity.autonomous_training.types import ModelStatus

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
            orch.models.mark_lkg(lkg["model_id"], reason="test")
            orch.autonomous_enabled = True
            tick = orch.maybe_run_autonomous_tick()
            self.assertFalse(tick.get("trained"))
            still = orch.models.last_known_good()
            self.assertIsNotNone(still)
            self.assertEqual(still["model_id"], lkg["model_id"])
            self.assertTrue(
                orch.learning_statistics().get("lkg_model")
                or orch.models.last_known_good()
            )


class TestObservabilityNoPrivateContent(unittest.TestCase):
    def test_stats_omit_example_text(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(
                root=d, include_approved_seeds=False, allow_mock_backend=True
            )
            orch.experience.record_owner_feedback(
                instruction="Unique secret phrase should not appear in stats XYZUNIQUE99",
                response="A long enough safe response about continuous learning eligibility rules.",
                approved=True,
            )
            # Force reject path with secret to ensure stats still sanitize
            orch.experience.record_code_test_pass(
                instruction="leak password: hunter2",
                code="password: hunter2",
                source_id="bad",
            )
            stats = orch.learning_statistics()
            blob = str(stats)
            self.assertNotIn("XYZUNIQUE99", blob)
            self.assertNotIn("hunter2", blob)
            self.assertIn("next_training_eligibility", stats)
            self.assertIn("dataset_growth_since_previous_version", stats)


if __name__ == "__main__":
    unittest.main()
