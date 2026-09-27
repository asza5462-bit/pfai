"""PHASE 11 continuation — eval corpus integrity + activation ≠ production_ready."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pfai.longevity.autonomous_training.active_runtime import ActiveModelRuntime
from pfai.longevity.autonomous_training.evaluation_dataset import EvaluationDatasetBuilder
from pfai.longevity.autonomous_training.model_registry import ModelRegistry
from pfai.longevity.autonomous_training.types import ModelStatus


class TestEvaluationDatasetBuilder(unittest.TestCase):
    def test_dedupe_and_no_train_leakage(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ws = root / "data"
            train_dir = ws / "longevity" / "datasets" / "dataset-train"
            train_dir.mkdir(parents=True)
            (train_dir / "train.jsonl").write_text(
                json.dumps({"instruction": "train only prompt xx", "response": "train only answer yy"})
                + "\n",
                encoding="utf-8",
            )
            (train_dir / "validation.jsonl").write_text(
                json.dumps({"instruction": "heldout prompt aa", "response": "heldout answer bb"})
                + "\n",
                encoding="utf-8",
            )
            other = ws / "longevity" / "other"
            other.mkdir(parents=True)
            (other / "extra.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"instruction": "train only prompt xx", "response": "train only answer yy"}),
                        json.dumps({"instruction": "unique eval prompt zz", "response": "unique eval answer ww"}),
                        json.dumps({"instruction": "unique eval prompt zz", "response": "unique eval answer ww"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder = EvaluationDatasetBuilder(str(root / "evalds"))
            harvested = builder.harvest(
                exclude_train_dataset_dir=train_dir,
                workspace=ws,
            )
            texts = {(e["instruction"], e["response"]) for e in harvested["examples"]}
            self.assertNotIn(("train only prompt xx", "train only answer yy"), texts)
            self.assertIn(("heldout prompt aa", "heldout answer bb"), texts)
            self.assertIn(("unique eval prompt zz", "unique eval answer ww"), texts)
            # Deduped duplicate unique row
            self.assertEqual(
                sum(1 for e in harvested["examples"] if e["instruction"] == "unique eval prompt zz"),
                1,
            )

    def test_build_version_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ws = root / "data"
            (ws / "longevity").mkdir(parents=True)
            (ws / "longevity" / "a.jsonl").write_text(
                json.dumps({"instruction": "hello world prompt", "response": "hello world answer"})
                + "\n",
                encoding="utf-8",
            )
            builder = EvaluationDatasetBuilder(str(root / "evalds"))
            v1 = builder.build_version(workspace=ws, label="prodeval")
            v2 = builder.build_version(workspace=ws, label="prodeval")
            self.assertEqual(v1["content_hash"], v2["content_hash"])
            self.assertEqual(v1["dataset_id"], v2["dataset_id"])
            self.assertFalse(v2["created"])
            self.assertGreaterEqual(v1["count"], 1)
            self.assertTrue((root / "evalds" / v1["dataset_id"] / "manifest.json").exists())


class TestActivationNotProductionReady(unittest.TestCase):
    def test_activate_defaults_not_production_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            reg = ModelRegistry(str(root / "models"))
            m1 = reg.register(
                base_model="local",
                dataset_version="d1",
                training_config={},
                checkpoint_ref=str(root / "cp1"),
                status=ModelStatus.VALIDATED,
            )
            (root / "cp1").mkdir()
            (root / "cp1" / "adapter_config.json").write_text("{}", encoding="utf-8")
            act = reg.activate(m1["model_id"])
            self.assertEqual(act["model_id"], m1["model_id"])
            got = reg.get(m1["model_id"])
            self.assertFalse(bool((got.get("meta") or {}).get("production_ready")))
            self.assertEqual((got.get("meta") or {}).get("serving_tier"), "internal_active")

    def test_production_serving_uses_lkg_when_active_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cp_active = root / "cp_active"
            cp_lkg = root / "cp_lkg"
            for p in (cp_active, cp_lkg):
                p.mkdir()
                (p / "adapter_config.json").write_text("{}", encoding="utf-8")
            rt = ActiveModelRuntime(str(root / "active_runtime.json"))
            switched = rt.switch_to(
                model_id="model-v0003",
                checkpoint_ref=str(cp_active),
                meta={"production_ready": False, "serving_tier": "internal_active"},
            )
            self.assertEqual(switched["status"], "ACTIVE")
            self.assertFalse(switched["production_ready"])
            prod = rt.production_serving(
                lkg={"model_id": "model-v0001", "checkpoint_ref": str(cp_lkg)}
            )
            self.assertEqual(prod["model_id"], "model-v0001")
            self.assertEqual(prod["source"], "last_known_good")
            self.assertEqual(prod["internal_active_model"], "model-v0003")
            status = rt.describe_status(
                lkg={"model_id": "model-v0001", "checkpoint_ref": str(cp_lkg)}
            )
            self.assertFalse(status["MODEL_PRODUCTION_READY"])
            self.assertEqual(status["PRODUCTION_SERVING_MODEL"], "model-v0001")
            self.assertFalse(status["activation_semantics"]["active_implies_production_ready"])


if __name__ == "__main__":
    unittest.main()
