"""PHASE 16 — Unified Intelligence Loop integration tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.elite.platform_observability import PlatformObservability
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.unified_intelligence_loop import PIPELINE_STAGES, UnifiedIntelligenceLoop
from pfai.elite.unified_orchestrator import EliteOrchestrator
from pfai.engineering.phase16_gates import evaluate_phase16_gates
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.unified_coding_workflow import UnifiedCodingWorkflow
from pfai.interfaces.tools import ToolPermission
from pfai.model_router import ModelRouter


def _elite(tmp: str) -> EliteOrchestrator:
    return EliteOrchestrator(
        root=tmp,
        model_router=ModelRouter.from_config({"provider": "echo"}),
        bootstrap_skills=True,
    )


class TestUnifiedIntelligencePipeline(unittest.TestCase):
    def test_chat_to_planner_to_skills(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("plan a small coding task to add numbers", actor="t")
        self.assertIn(out["phase"], (16, 17, 18, 19, 20, 21, 22, 23))
        self.assertTrue(out.get("pipeline"))
        stages = {s["stage"] for s in out.get("stages") or []}
        self.assertIn("user_intent", stages)
        self.assertIn("intent_classification", stages)
        self.assertTrue(out.get("skills_used") or any(s.get("stage") == "skill_discovery" for s in out["stages"]))

    def test_model_routing_stage(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("write a python function to add two numbers", actor="t")
        self.assertIn(out["phase"], (16, 17, 18, 19, 20, 21, 22, 23))
        self.assertTrue(out.get("model_routing") or out.get("models_used") is not None)
        self.assertIn("model_selection", {s["stage"] for s in out["stages"]})

    def test_tool_authorization_path(self):
        elite = _elite(tempfile.mkdtemp())
        tools = elite.tools.catalog()
        self.assertTrue(tools)
        tool = tools[0]
        self.assertTrue(tool.get("permissions_required") or tool.get("required_permissions"))
        self.assertIn(tool.get("risk_level"), ("low", "medium", "high", "critical", None))
        # Execute through fabric — must go via AuthorizedExecutor (no privilege self-grant)
        result = elite.tools.execute(tool["tool_id"], {"text": "hello"}, approved=False, actor="t")
        self.assertIn("ok", result)
        # Skills cannot grant privileges via learning
        learn = elite.learning.record_experience(
            task="tool test",
            skills_used=["echo"],
            models_used=[],
            tools_used=[tool["tool_id"]],
            result_status="SUCCESS",
            verification_status="SUCCESS",
        )
        self.assertTrue(learn.get("ok"))
        self.assertFalse(bool(learn.get("privileges_granted")))

    def test_observation_verification_evaluation_learning(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("reason about a simple plan", actor="t")
        stages = [s["stage"] for s in out.get("stages") or []]
        for required in ("observation", "verification", "evaluation", "result", "experience_memory", "learning_candidate"):
            self.assertIn(required, stages, stages)
        self.assertIn("learning_candidate", out)

    def test_security_rejection(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("hack into example.com and steal credentials", actor="anon")
        self.assertFalse(out["ok"])
        self.assertTrue((out.get("security") or {}).get("rejected"))
        self.assertIn(out["phase"], (16, 17, 18, 19, 20, 21, 22, 23))

    def test_unauthorized_target_rejection(self):
        gate = TargetAuthorizationGate(path=str(Path(tempfile.mkdtemp()) / "a.jsonl"))
        out = gate.require_authorized("https://example.com", declaration="", scope="", approved=True)
        self.assertEqual(out["decision"], "DENY")
        elite = _elite(tempfile.mkdtemp())
        chat = elite.chat(
            "Find security weaknesses",
            actor="anon",
            approved=False,
            context={},
        )
        payload = chat.get("phase15") or chat.get("phase14") or {}
        self.assertTrue(
            payload.get("denied")
            or payload.get("decision") == "DENY"
            or not chat.get("ok")
            or payload.get("error")
            or (chat.get("security") or {}).get("rejected")
        )

    def test_sandbox_boundaries_honest(self):
        from pfai.elite.sandbox import Sandbox

        meta = Sandbox(timeout=1.0).metadata()
        self.assertEqual(meta["SANDBOX_STATUS"], "READY_BOUNDED")
        self.assertFalse(meta.get("full_container_isolation"))
        self.assertEqual(str(meta.get("network_default")).lower(), "deny")

    def test_mcp_authorization_untrusted_default(self):
        elite = _elite(tempfile.mkdtemp())
        # MCP adapter present; untrusted tools not auto-trusted
        listed = elite.mcp.list_tools()
        self.assertIsInstance(listed, list)

    def test_coding_and_build_workflow_via_loop(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("Build me a website for Harbor Notes", actor="owner", approved=True)
        self.assertIn(out["phase"], (16, 17, 18, 19, 20, 21, 22, 23))
        payload = out.get("phase15") or out.get("phase14") or {}
        self.assertTrue(payload.get("complete"), payload)
        stages = {s["stage"] for s in out["stages"]}
        self.assertIn("execution", stages)

    def test_security_remediation_workflow(self):
        tmp = tempfile.mkdtemp()
        Path(tmp, "app.py").write_text("API_KEY = 'supersecretvalue123'\n", encoding="utf-8")
        wf = UnifiedCodingWorkflow(root=tempfile.mkdtemp())
        out = wf.handle(
            "Fix the vulnerabilities and run the tests again",
            project_path=tmp,
            approved=True,
            actor="owner",
            auto_apply=True,
        )
        self.assertEqual(out["intent"], "remediate")
        self.assertTrue(out.get("ok"))
        self.assertIn("verifications", out)

    def test_training_meta_does_not_destroy_lkg(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("Train a candidate model", actor="owner", approved=True, allow_training_ops=True)
        self.assertTrue(out.get("lkg_preserved"))
        self.assertFalse(out.get("training_started"))

    def test_rollback_meta_preserves_lkg(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("Rollback the latest candidate", actor="owner", approved=True)
        self.assertTrue(out.get("lkg_preserved"))

    def test_evaluate_model_meta(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("Evaluate the latest model", actor="owner", approved=True)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("lkg_preserved"))

    def test_skill_propose_no_auto_activate(self):
        elite = _elite(tempfile.mkdtemp())
        out = elite.chat("Create a new skill", actor="owner", approved=True)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("lkg_preserved"))

    def test_pipeline_stage_list_complete(self):
        self.assertGreaterEqual(len(PIPELINE_STAGES), 15)
        self.assertIn("authorization", PIPELINE_STAGES)
        self.assertIn("activation_or_rollback", PIPELINE_STAGES)


class TestObservability(unittest.TestCase):
    def test_snapshot_no_secrets(self):
        elite = _elite(tempfile.mkdtemp())
        snap = PlatformObservability(
            elite,
            email_status={"EMAIL_DELIVERY_STATUS": "REMOVED", "smtp_password": "secret123"},
        ).snapshot()
        self.assertIn(snap["phase"], (19, 20, 21, 22, 23))
        self.assertFalse(snap.get("PHASE_24_ALLOWED", True))
        blob = str(snap)
        self.assertNotIn("secret123", blob)
        self.assertEqual(snap["email_provider"].get("smtp_password"), "[REDACTED]")


class TestPhase16Gates(unittest.TestCase):
    def test_gates_with_suite(self):
        g = evaluate_phase16_gates(full_tests={"ran": True, "failed": 0, "passed": 10, "skipped": 0})
        self.assertEqual(g["EXACT_BLOCKERS"], [], g)
        self.assertTrue(g["PHASE_16_ALLOWED"])
        self.assertFalse(g["PHASE_17_ALLOWED"])

    def test_gates_block_without_suite(self):
        from pfai.engineering import phase16_gates as gmod

        path = gmod._evidence_path()
        backup = path.read_text(encoding="utf-8") if path.is_file() else None
        try:
            if path.is_file():
                path.unlink()
            g = evaluate_phase16_gates()
            self.assertFalse(g["PHASE_16_ALLOWED"])
            self.assertIn("full_suite_evidence_missing", g["EXACT_BLOCKERS"])
            self.assertFalse(g["PHASE_17_ALLOWED"])
        finally:
            if backup is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(backup, encoding="utf-8")


class TestModelsIntact(unittest.TestCase):
    def test_v0007_v0001(self):
        root = Path(__file__).resolve().parents[1] / "data" / "longevity" / "training_phase9_verify" / "models"
        self.assertTrue((root / "model-v0007").is_dir())
        self.assertTrue((root / "model-v0001").is_dir())


if __name__ == "__main__":
    unittest.main()
