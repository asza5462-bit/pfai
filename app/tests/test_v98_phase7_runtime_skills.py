"""PHASE 7: runtime detection, skill packs, control center, activation/rollback runtime."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.interfaces.migration import PFAI_SCHEMA_VERSION
from pfai.longevity.autonomous_training.active_runtime import ActiveModelRuntime
from pfai.longevity.autonomous_training.canary import CanaryController
from pfai.longevity.autonomous_training.collector import ExperienceCollector
from pfai.longevity.autonomous_training.compatibility import ModelCompatibilityChecker
from pfai.longevity.autonomous_training.orchestrator import AutonomousTrainingOrchestrator
from pfai.longevity.autonomous_training.resources import TrainingResourceManager
from pfai.longevity.autonomous_training.runtime_detector import (
    RuntimeAvailability,
    TrainingRuntimeDetector,
)
from pfai.longevity.autonomous_training.types import TrainingConfig
from pfai.skills.packs import SkillPackRegistry, SkillPackVersion, skill_cannot_elevate
from pfai.interfaces.tools import ToolPermission


def _rows(n: int = 10):
    return [
        {
            "instruction": f"Describe reliable pattern {i} for long-lived AI systems",
            "response": f"Pattern {i}: isolate authority from model learning, version datasets, evaluate before activation. " * 2,
            "source": "phase7",
            "source_id": f"p7-{i}",
            "verified": True,
        }
        for i in range(n)
    ]


class TestRuntimeDetector(unittest.TestCase):
    def test_honest_unavailable_without_torch(self):
        det = TrainingRuntimeDetector(endpoint="http://127.0.0.1:9")
        result = det.detect(probe_inference=True)
        self.assertIn(
            result.status,
            (
                RuntimeAvailability.UNAVAILABLE.value,
                RuntimeAvailability.PARTIALLY_AVAILABLE.value,
                RuntimeAvailability.AVAILABLE.value,
                RuntimeAvailability.ERROR.value,
            ),
        )
        # Honest coupling: training_available iff status AVAILABLE
        if result.training_available:
            self.assertEqual(result.status, RuntimeAvailability.AVAILABLE.value)
        else:
            self.assertNotEqual(result.status, RuntimeAvailability.AVAILABLE.value)
        if not result.modules.get("torch"):
            self.assertFalse(result.training_available)


class TestCompatibilityAndResources(unittest.TestCase):
    def test_blocked_reasons(self):
        checker = ModelCompatibilityChecker()
        report = checker.check(config=TrainingConfig(base_model="", method="lora"), dataset_rows=[])
        self.assertTrue(report["blocked"])
        self.assertTrue(report["reasons"])

    def test_resource_admit(self):
        mgr = TrainingResourceManager()
        est = mgr.estimate(dataset_rows=100, method="lora")
        self.assertIn("expected_memory_gb", est)
        admit = mgr.admit(dataset_rows=10, method="lora", running_jobs=0)
        self.assertIn("action", admit)


class TestActiveRuntimeAndCanary(unittest.TestCase):
    def test_switch_and_rollback_pointer(self):
        with tempfile.TemporaryDirectory() as d:
            rt = ActiveModelRuntime(str(Path(d) / "active.json"))
            cp = Path(d) / "ckpt"
            cp.mkdir()
            (cp / "adapter_manifest.json").write_text("{}", encoding="utf-8")
            switched = rt.switch_to(model_id="model-v0001", checkpoint_ref=str(cp))
            self.assertEqual(switched["status"], "ACTIVE")
            self.assertTrue(switched["loaded"])
            cp2 = Path(d) / "ckpt2"
            cp2.mkdir()
            (cp2 / "x.json").write_text("{}", encoding="utf-8")
            rt.switch_to(model_id="model-v0002", checkpoint_ref=str(cp2))
            rb = rt.rollback_to_previous()
            self.assertTrue(rb["ok"])
            self.assertEqual(rt.current()["model_id"], "model-v0001")

    def test_canary_stop_on_regression(self):
        c = CanaryController()
        c.failure_threshold = 0.05
        out = c.evaluate_shadow({"ok": True, "decision": "CONTINUE", "regression": 0.5})
        self.assertEqual(out["decision"], "STOP_ACTIVATION")


class TestSkillPacks(unittest.TestCase):
    def test_register_activate_rollback_no_elevation(self):
        with tempfile.TemporaryDirectory() as d:
            reg = SkillPackRegistry(str(Path(d) / "packs.sqlite3"))
            p = SkillPackVersion(
                pack_id="coding",
                version="1.0.0",
                description="coding",
                skills=["coding_teach"],
                permission=ToolPermission.LOW_RISK_WRITE.value,
            )
            reg.register_pack(p, activate=True)
            p2 = SkillPackVersion(
                pack_id="coding",
                version="1.1.0",
                description="coding+",
                skills=["coding_teach", "coding_review"],
                permission=ToolPermission.LOW_RISK_WRITE.value,
            )
            reg.register_pack(p2, activate=True)
            self.assertEqual(reg.get("coding")["version"], "1.1.0")
            rb = reg.rollback("coding", approved=True, actor="owner")
            self.assertTrue(rb["ok"])
            self.assertEqual(reg.get("coding")["version"], "1.0.0")
            self.assertTrue(skill_cannot_elevate(ToolPermission.SECRETS.value, ToolPermission.READ.value))
            self.assertFalse(skill_cannot_elevate(ToolPermission.READ.value, ToolPermission.READ.value))


class TestOrchestratorPhase7(unittest.TestCase):
    def test_mock_cycle_switches_runtime_and_rollbacks(self):
        with tempfile.TemporaryDirectory() as d:
            collector = ExperienceCollector()
            collector.register("unit", lambda: _rows(10))
            orch = AutonomousTrainingOrchestrator(
                root=d,
                collector=collector,
                allow_mock_backend=True,
                eval_runner=lambda suite: {"ok": True, "score": 0.9, "suite": suite},
            )
            r1 = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True, base_model="tiny"),
            )
            self.assertTrue(r1["ok"], r1)
            self.assertFalse(r1["actual_training_executed"])
            self.assertTrue(r1.get("model_activated"))
            self.assertEqual(orch.active_runtime.current().get("status"), "ACTIVE")
            r2 = orch.run_cycle(
                owner_requested=True,
                config=TrainingConfig(allow_mock_backend=True, base_model="tiny"),
            )
            self.assertTrue(r2["ok"], r2)
            rb = orch.monitor_and_maybe_rollback(force_regression=True)
            self.assertTrue(rb.get("ok"), rb)
            # Runtime pointer should point at restored model
            self.assertEqual(orch.active_runtime.current().get("status"), "ACTIVE")

    def test_stale_job_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            orch = AutonomousTrainingOrchestrator(root=d, allow_mock_backend=True)
            job = {
                "job_id": "job-stale0001",
                "state": "RUNNING",
                "created_at": 1,
                "updated_at": 1,
            }
            orch._write_job(job)
            fixed = orch.reconcile_stale_jobs()
            self.assertIn("job-stale0001", fixed)
            self.assertEqual(orch._read_job("job-stale0001")["state"], "FAILED")


class TestPhase7API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, AUTONOMOUS_TRAINING
        from pfai.longevity.autonomous_training.collector import ExperienceCollector

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}
        coll = ExperienceCollector()
        coll.register("api_seed", lambda: _rows(10))
        AUTONOMOUS_TRAINING.collector = coll
        AUTONOMOUS_TRAINING.allow_mock_backend = True

    def test_runtime_and_control_center_owner_gated(self):
        self.assertEqual(self.client.get("/platform/runtime/status").status_code, 401)
        r = self.client.get("/platform/runtime/status", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("status", r.json())
        st = self.client.get("/platform/training/status", headers=self.headers)
        self.assertEqual(st.status_code, 200)
        self.assertIn("control_center", st.json())

    def test_skill_packs_api(self):
        r = self.client.get("/platform/skills/packs", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json().get("packs") or []), 1)

    def test_training_start_pause_cancel_paths(self):
        # Start may be UNAVAILABLE without mock flag in body — allow mock
        r = self.client.post(
            "/platform/training/start",
            headers=self.headers,
            json={"owner_requested": True, "allow_mock_backend": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn(body.get("status"), ("COMPLETED", "REJECTED", "INSUFFICIENT_DATA", "TRAINING_RUNTIME_UNAVAILABLE", "DATASET_QUALITY_BELOW_THRESHOLD", "TRIGGER_NOT_MET", "AUTONOMOUS_DISABLED"))
        if body.get("is_mock"):
            self.assertFalse(body.get("actual_training_executed"))
        p = self.client.post("/platform/training/pause", headers=self.headers)
        self.assertEqual(p.status_code, 200)

    def test_security_regression_otp_and_escalation(self):
        self.assertEqual(self.client.get("/owner/identity", params={"role": "owner"}).status_code, 401)
        self.assertEqual(self.client.post("/platform/training/start", json={"role": "owner", "admin": True}).status_code, 401)
        st = self.client.get("/owner/status")
        self.assertEqual(st.status_code, 200)
        self.assertNotIn("email_otp", st.json().get("auth_methods", []))
        self.assertIn("password", st.json().get("auth_methods", []))
        self.assertNotIn("otp_code", json.dumps(st.json()).lower())

    def test_schema_target_5(self):
        self.assertEqual(PFAI_SCHEMA_VERSION, 5)
        r = self.client.get("/platform/migrations", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("target"), 5)


if __name__ == "__main__":
    unittest.main()
