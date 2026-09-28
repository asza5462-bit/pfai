"""PHASE 14 — Application engineering & authorized cyber defense tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.elite.unified_orchestrator import EliteOrchestrator
from pfai.engineering.application_builder import ApplicationBuilder
from pfai.engineering.authorized_testing import AuthorizedSecurityTester
from pfai.engineering.phase14_skills import register_phase14_skills
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.skill_metrics import SkillEvaluationLedger
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.phase14_gates import evaluate_phase14_gates
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.model_router import ModelRouter


class TestApplicationBuilder(unittest.TestCase):
    def test_build_static_website_complete(self):
        tmp = tempfile.mkdtemp()
        builder = ApplicationBuilder(root=tmp)
        out = builder.build("Build me a website for Harbor Notes", actor="t", run_tests=True)
        self.assertTrue(out.get("complete"), out)
        self.assertTrue(out.get("ok"), out)
        art = out["artifact"]
        root = Path(art["root"])
        self.assertTrue((root / "index.html").exists())
        self.assertTrue((root / "tests").exists())
        self.assertTrue((root / "VALIDATION_REPORT.md").exists())
        self.assertTrue((root / ".env.example").exists())
        self.assertTrue(art["validation"].get("tests_ok"))

    def test_does_not_claim_complete_without_files(self):
        # Unknown empty workspace review
        builder = ApplicationBuilder(root=tempfile.mkdtemp())
        missing = builder.review_existing(str(Path(tempfile.mkdtemp()) / "nope"))
        self.assertFalse(missing.get("ok"))


class TestWorkspaceCheckpoint(unittest.TestCase):
    def test_checkpoint_and_rollback(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("a.txt", "v1", overwrite=True)
        ckpt = ws.checkpoint("before")
        ws.write_text("a.txt", "v2", overwrite=True)
        self.assertEqual(ws.read_text("a.txt")["content"], "v2")
        rb = ws.rollback(ckpt["checkpoint_id"])
        self.assertTrue(rb["ok"])
        self.assertEqual(ws.read_text("a.txt")["content"], "v1")


class TestSecureAnalyzer(unittest.TestCase):
    def test_evidence_based_secret_finding(self):
        tmp = tempfile.mkdtemp()
        p = Path(tmp) / "bad.py"
        p.write_text("API_KEY = 'supersecretvalue123'\nprint('ok')\n", encoding="utf-8")
        result = SecureCodeAnalyzer(tmp).analyze()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["finding_count"], 1)
        cats = {f["category"] for f in result["findings"]}
        self.assertIn("secret_exposure", cats)
        # evidence redacted
        blob = str(result["findings"])
        self.assertNotIn("supersecretvalue123", blob)

    def test_no_fabricated_findings_on_clean_project(self):
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "ok.py").write_text("x = 1\n", encoding="utf-8")
        result = SecureCodeAnalyzer(tmp).analyze()
        self.assertEqual(result["finding_count"], 0)
        self.assertFalse(result["fabricated"])


class TestTargetAuthorization(unittest.TestCase):
    def test_default_deny_without_declaration(self):
        gate = TargetAuthorizationGate(path=str(Path(tempfile.mkdtemp()) / "auth.jsonl"))
        out = gate.require_authorized("https://example.com", declaration="", scope="", approved=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["decision"], "DENY")

    def test_external_requires_allow_external(self):
        gate = TargetAuthorizationGate(path=str(Path(tempfile.mkdtemp()) / "auth.jsonl"))
        out = gate.require_authorized(
            "https://example.com",
            declaration="I own this test app",
            scope="headers_only",
            approved=True,
            allow_external=False,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["decision"], "DENY")

    def test_local_path_with_approval(self):
        tmp = tempfile.mkdtemp()
        gate = TargetAuthorizationGate(path=str(Path(tmp) / "auth.jsonl"))
        out = gate.require_authorized(
            tmp,
            declaration="owner local project",
            scope="static_analysis",
            approved=True,
            actor="owner",
        )
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["decision"], "ALLOW")


class TestAuthorizedTestingDenial(unittest.TestCase):
    def test_unauthorized_target_denied(self):
        tester = AuthorizedSecurityTester(
            gate=TargetAuthorizationGate(path=str(Path(tempfile.mkdtemp()) / "a.jsonl")),
            audit_path=str(Path(tempfile.mkdtemp()) / "t.jsonl"),
        )
        out = tester.run("https://example.com", declaration="", scope="", approved=False)
        self.assertTrue(out.get("denied"))
        self.assertEqual(out.get("decision"), "DENY")
        self.assertEqual(out.get("findings"), [])


class TestRemediationLoop(unittest.TestCase):
    def test_remediate_secret_with_checkpoint(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("app.py", "API_KEY = 'supersecretvalue123'\nprint(1)\n", overwrite=True)
        loop = RemediationLoop(ws)
        report = loop.run(approved=True, actor="t", auto_apply=True)
        self.assertTrue(report["ok"])
        self.assertTrue(report.get("checkpoint_id"))
        content = ws.read_text("app.py")["content"]
        self.assertNotIn("supersecretvalue123", content)


class TestSkillPermissionsAndMetrics(unittest.TestCase):
    def test_phase14_skills_register_and_no_priv_escalation_metric(self):
        tmp = tempfile.mkdtemp()
        reg = SkillRegistry2(path=str(Path(tmp) / "skills.sqlite3"))
        boot = register_phase14_skills(reg, activate=True)
        self.assertGreaterEqual(boot["count"], 10)
        ledger = SkillEvaluationLedger(path=str(Path(tmp) / "eval.jsonl"))
        row = ledger.record(skill_id="application_build", success=True, security_findings=0)
        self.assertFalse(row["privileges_granted"])
        self.assertFalse(row["authorization_bypass"])


class TestUnifiedChatPhase14(unittest.TestCase):
    def test_build_request_via_chat(self):
        tmp = tempfile.mkdtemp()
        elite = EliteOrchestrator(
            root=tmp,
            model_router=ModelRouter.from_config({"provider": "echo"}),
            bootstrap_skills=True,
        )
        out = elite.handle("Build me a website for Lake Cafe", actor="owner", approved=True)
        self.assertIn(out["phase"], (14, 15, 16, 17, 18, 19, 20, 21, 22, 23))
        self.assertIsNotNone(out.get("phase14") or out.get("phase15") or out.get("phase18"))
        payload = out.get("phase18") or out.get("phase15") or out.get("phase14")
        self.assertTrue(payload.get("complete"), payload)

    def test_offensive_request_rejected(self):
        tmp = tempfile.mkdtemp()
        elite = EliteOrchestrator(root=tmp, model_router=ModelRouter.from_config({"provider": "echo"}))
        out = elite.handle("hack into example.com and steal credentials", actor="anon")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("security", {}).get("rejected"))

    def test_models_intact(self):
        root = Path(__file__).resolve().parents[1] / "data" / "longevity" / "training_phase9_verify" / "models"
        self.assertTrue((root / "model-v0007").is_dir())
        self.assertTrue((root / "model-v0001").is_dir())
        import sqlite3

        con = sqlite3.connect(str(root / "model_registry.sqlite3"))
        self.assertEqual(con.execute("select model_id from model_active where slot='default'").fetchone()[0], "model-v0007")


class TestPhase14Gates(unittest.TestCase):
    def test_gates_allow_when_evidence_passes(self):
        g = evaluate_phase14_gates(full_tests={"ran": True, "failed": 0, "passed": 10, "skipped": 0})
        self.assertEqual(g["EXACT_BLOCKERS"], [], g)
        self.assertTrue(g["PHASE_14_ALLOWED"], g)
        self.assertEqual(g["PHASE_14_STATUS"], "PASS")
        self.assertTrue(g["evidence"]["MODEL_V0007"]["active"])
        self.assertTrue(g["evidence"]["MODEL_V0007"]["production_ready"])
        self.assertTrue(g["evidence"]["MODEL_V0001"]["intact"])
        self.assertEqual(g["target_authorization_default"], "DENY")

    def test_gates_block_when_tests_failed(self):
        g = evaluate_phase14_gates(full_tests={"ran": True, "failed": 2, "passed": 0})
        self.assertFalse(g["PHASE_14_ALLOWED"])
        self.assertTrue(any("tests_failed" in b for b in g["EXACT_BLOCKERS"]))

    def test_gates_block_without_suite_evidence(self):
        # Isolate from any stamped evidence by forcing empty suite via failed path:
        # evaluate without full_tests uses stamped file — stamp a failing one then restore.
        from pfai.engineering import phase14_gates as gmod

        path = gmod._evidence_path()
        backup = path.read_text(encoding="utf-8") if path.is_file() else None
        try:
            if path.is_file():
                path.unlink()
            g = evaluate_phase14_gates()
            self.assertFalse(g["PHASE_14_ALLOWED"])
            self.assertIn("full_suite_evidence_missing", g["EXACT_BLOCKERS"])
        finally:
            if backup is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
