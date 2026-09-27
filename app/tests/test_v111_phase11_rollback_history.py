"""PHASE 11 — durable promotion history + rollback resolution tests."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.active_runtime import ActiveModelRuntime
from pfai.longevity.autonomous_training.audit import TrainingAuditLog
from pfai.longevity.autonomous_training.checkpoints import CheckpointStore
from pfai.longevity.autonomous_training.isolation import TrainingSafetyIsolation
from pfai.longevity.autonomous_training.model_registry import ModelRegistry
from pfai.longevity.autonomous_training.promotion_history import (
    PromotionHistory,
    adapter_artifact_hash,
)
from pfai.longevity.autonomous_training.rollback import ModelRollbackManager
from pfai.longevity.autonomous_training.types import ModelStatus


def _write_adapter(dir_path: Path, payload: bytes) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    adapter = dir_path / "adapter_model.safetensors"
    adapter.write_bytes(payload)
    (dir_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    return adapter


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase11RollbackHistoryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p11-rb-")
        self.root = Path(self.tmp)
        self.models = ModelRegistry(str(self.root / "models"))
        self.runtime = ActiveModelRuntime(str(self.root / "active_runtime.json"))
        self.checkpoints = CheckpointStore(str(self.root / "checkpoints"))
        self.history = PromotionHistory(str(self.root / "promotion_history.jsonl"))
        self.audit = TrainingAuditLog(str(self.root / "training_audit.jsonl"))
        self.rb = ModelRollbackManager(
            self.models,
            audit_fn=self.audit.record,
            active_runtime=self.runtime,
            checkpoints=self.checkpoints,
            promotion_history=self.history,
        )
        # model-v0001
        self.cp1 = self.root / "cp-v1"
        self.ad1 = _write_adapter(self.cp1, b"LKG-V0001-BYTES")
        self.hash1 = _sha(self.ad1)
        self.v1 = self.models.register(
            base_model="base",
            dataset_version="dataset-v0002",
            training_backend="transformers_lora",
            training_config={},
            checkpoint_ref=str(self.cp1),
            status=ModelStatus.CANDIDATE,
            model_id="model-v0001",
        )
        self.models.activate("model-v0001", mark_as_lkg=True, production_ready=True)
        self.runtime.switch_to(
            model_id="model-v0001",
            checkpoint_ref=str(self.cp1),
            meta={"production_ready": True},
        )
        # model-v0007
        self.cp7 = self.root / "cp-v7"
        self.ad7 = _write_adapter(self.cp7, b"PROD-V0007-BYTES-XXXX")
        self.hash7 = _sha(self.ad7)
        self.v7 = self.models.register(
            base_model="base",
            dataset_version="dataset-v0006",
            training_backend="transformers_lora",
            training_config={},
            checkpoint_ref=str(self.cp7),
            status=ModelStatus.CANDIDATE,
            model_id="model-v0007",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _promote_v1_to_v7(self):
        self.models.activate(
            "model-v0007",
            mark_as_lkg=True,
            preserve_outgoing_as_lkg=False,
            production_ready=True,
            record_promotion=False,
        )
        self.models.mark_lkg("model-v0007", reason="production_quality_gate_pass")
        self.runtime.switch_to(
            model_id="model-v0007",
            checkpoint_ref=str(self.cp7),
            meta={"production_ready": True},
        )
        try:
            cur = self.runtime.current()
            cur["production_ready"] = True
            cur["serving_tier"] = "production_ready"
            self.runtime.path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        except Exception:
            pass
        return self.history.record_promotion(
            previous_active_model="model-v0001",
            previous_lkg_model="model-v0001",
            new_active_model="model-v0007",
            new_lkg_model="model-v0007",
            previous_active_hash=self.hash1,
            previous_lkg_hash=self.hash1,
            new_active_hash=self.hash7,
            new_lkg_hash=self.hash7,
            dataset_version="dataset-v0006",
            evaluation_dataset="prodeval-v0003",
            evaluation_samples=336,
            quality_gate_result="PASS",
            reason="production_quality_gate_pass",
        )


class TestPhase11PromotionHistory(Phase11RollbackHistoryBase):
    def test_A_promote_v0001_to_v0007_preserves_previous_lkg(self):
        promo = self._promote_v1_to_v7()
        self.assertEqual(promo["previous_lkg_model"], "model-v0001")
        self.assertEqual(promo["new_lkg_model"], "model-v0007")
        self.assertEqual(self.models.active()["model_id"], "model-v0007")
        self.assertEqual(self.models.last_known_good()["model_id"], "model-v0007")
        self.assertTrue(self.ad1.exists())
        self.assertEqual(_sha(self.ad1), self.hash1)
        resolved = self.rb.resolve_previous_production_model()
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["model_id"], "model-v0001")

    def test_B_rollback_v0007_to_v0001_resolves_from_history(self):
        self._promote_v1_to_v7()
        # Current LKG == active == v0007; must still resolve via history
        self.assertEqual(self.models.last_known_good()["model_id"], "model-v0007")
        rb = self.rb.rollback(reason="phase11_verification")
        self.assertTrue(rb["ok"], rb)
        self.assertEqual(rb["restored_model_id"], "model-v0001")
        self.assertEqual(rb["source"], "promotion_history")
        self.assertEqual(self.models.active()["model_id"], "model-v0001")

    def test_C_rollback_does_not_mutate_v0007(self):
        self._promote_v1_to_v7()
        before = _sha(self.ad7)
        mtime = self.ad7.stat().st_mtime_ns
        self.rb.rollback(reason="phase11_verification")
        self.assertEqual(_sha(self.ad7), before)
        self.assertEqual(self.ad7.stat().st_mtime_ns, mtime)

    def test_D_rollback_does_not_delete_v0007(self):
        self._promote_v1_to_v7()
        self.rb.rollback(reason="phase11_verification")
        self.assertTrue(self.ad7.exists())
        self.assertIsNotNone(self.models.get("model-v0007"))

    def test_E_rollback_preserves_v0001_integrity(self):
        self._promote_v1_to_v7()
        before = _sha(self.ad1)
        rb = self.rb.rollback(reason="phase11_verification")
        self.assertTrue(rb["ok"])
        self.assertEqual(_sha(self.ad1), before)
        integ = ActiveModelRuntime.verify_checkpoint(str(self.cp1))
        self.assertTrue(integ["ok"])

    def test_F_rollback_hashes_remain_unchanged(self):
        self._promote_v1_to_v7()
        h1_before, h7_before = _sha(self.ad1), _sha(self.ad7)
        self.rb.rollback(reason="phase11_verification")
        self.assertEqual(_sha(self.ad1), h1_before)
        self.assertEqual(_sha(self.ad7), h7_before)
        self.assertEqual(adapter_artifact_hash(str(self.cp1)), h1_before)
        self.assertEqual(adapter_artifact_hash(str(self.cp7)), h7_before)

    def test_G_rollback_is_idempotent(self):
        self._promote_v1_to_v7()
        rb1 = self.rb.rollback(reason="first")
        self.assertTrue(rb1["ok"])
        self.assertEqual(self.models.active()["model_id"], "model-v0001")
        # After rollback, history still has PROMOTION; resolve for current=v0001
        # may find older promotion's previous — seed only one promotion so
        # resolve for v0001 has no matching new_*=v0001 → fail closed OR
        # idempotent if somehow target==active.
        # Re-record that we are at v0001: second rollback should fail closed
        # without corruption when no previous for v0001.
        active_before = self.models.active()["model_id"]
        h1, h7 = _sha(self.ad1), _sha(self.ad7)
        rb2 = self.rb.rollback(reason="second")
        # Either idempotent-at-target or fail-closed; never corrupt
        self.assertEqual(_sha(self.ad1), h1)
        self.assertEqual(_sha(self.ad7), h7)
        self.assertTrue(self.models.get("model-v0001"))
        self.assertTrue(self.models.get("model-v0007"))
        if rb2.get("ok") and rb2.get("already_at_target"):
            self.assertEqual(self.models.active()["model_id"], "model-v0001")
        else:
            # fail closed keeps active
            self.assertEqual(self.models.active()["model_id"], active_before)

    def test_H_missing_previous_lkg_fails_closed(self):
        # Promote without history
        self.models.activate(
            "model-v0007", mark_as_lkg=True, preserve_outgoing_as_lkg=False, production_ready=True
        )
        self.runtime.switch_to(model_id="model-v0007", checkpoint_ref=str(self.cp7))
        active_before = self.models.active()["model_id"]
        rb = self.rb.rollback(reason="no_history")
        self.assertFalse(rb["ok"])
        self.assertEqual(rb.get("error"), "no_promotion_history")
        self.assertEqual(self.models.active()["model_id"], active_before)

    def test_I_corrupted_rollback_target_fails_closed(self):
        self._promote_v1_to_v7()
        # Corrupt v0001 adapter
        self.ad1.write_bytes(b"CORRUPTED")
        active_before = self.models.active()["model_id"]
        h7 = _sha(self.ad7)
        rb = self.rb.rollback(reason="corrupt_target")
        self.assertFalse(rb["ok"])
        self.assertIn(rb.get("error"), ("lkg_checkpoint_corrupt", "rollback_target_hash_mismatch"))
        self.assertTrue(rb.get("active_unchanged"))
        self.assertEqual(self.models.active()["model_id"], active_before)
        self.assertEqual(_sha(self.ad7), h7)

    def test_J_promotion_history_survives_restart(self):
        self._promote_v1_to_v7()
        # Re-open history from disk
        hist2 = PromotionHistory(str(self.root / "promotion_history.jsonl"))
        events = hist2.list_events()
        self.assertTrue(any(e.get("event_type") == "PROMOTION" for e in events))
        rb2 = ModelRollbackManager(
            self.models,
            audit_fn=self.audit.record,
            active_runtime=self.runtime,
            checkpoints=self.checkpoints,
            promotion_history=hist2,
        )
        resolved = rb2.resolve_previous_production_model()
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["model_id"], "model-v0001")

    def test_K_rollback_history_is_auditable(self):
        self._promote_v1_to_v7()
        self.rb.rollback(reason="audit_check")
        events = self.history.list_events()
        types = [e.get("event_type") for e in events]
        self.assertIn("PROMOTION", types)
        self.assertIn("ROLLBACK", types)
        promo = next(e for e in events if e["event_type"] == "PROMOTION")
        rb = next(e for e in reversed(events) if e["event_type"] == "ROLLBACK")
        self.assertEqual(promo["previous_lkg_model"], "model-v0001")
        self.assertEqual(promo["new_lkg_model"], "model-v0007")
        self.assertEqual(rb["from_model"], "model-v0007")
        self.assertEqual(rb["to_model"], "model-v0001")
        recent = self.audit.recent(20)
        self.assertTrue(any(a.get("event") == "model_rollback" for a in recent))

    def test_L_future_candidate_does_not_destroy_previous_lkg(self):
        self._promote_v1_to_v7()
        # Internal (non production_ready) candidate
        cp8 = self.root / "cp-v8"
        _write_adapter(cp8, b"CANDIDATE-V8")
        self.models.register(
            base_model="base",
            dataset_version="dataset-v0007",
            training_backend="transformers_lora",
            training_config={},
            checkpoint_ref=str(cp8),
            status=ModelStatus.CANDIDATE,
            model_id="model-v0008",
        )
        self.models.activate(
            "model-v0008",
            production_ready=False,
            preserve_outgoing_as_lkg=True,
        )
        # Existing production LKG pointer should remain model-v0007
        self.assertEqual(self.models.last_known_good()["model_id"], "model-v0007")
        self.assertTrue(self.ad7.exists())
        self.assertTrue(self.ad1.exists())
        # History still resolves previous of v0007 to v0001
        # (current active is v0008; resolve with explicit current_lkg)
        resolved = self.history.resolve_previous_production_model(
            current_active="model-v0007", current_lkg="model-v0007"
        )
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["model_id"], "model-v0001")

    def test_M_auth_and_training_isolation_remain_unchanged(self):
        iso = TrainingSafetyIsolation()
        for payload in (
            {"modify_authorization": True},
            {"modify_authentication": True},
            {"grant_permission": True},
            {"write_secrets": True},
            {"config": {"mutate_auth": True}},
        ):
            r = iso.guard_training_request(payload)
            self.assertFalse(r["ok"], payload)
        blocked = iso.assert_artifact_path_allowed(
            "/etc/owner/secrets", training_root=str(self.root)
        )
        self.assertFalse(blocked["ok"])


if __name__ == "__main__":
    unittest.main()
