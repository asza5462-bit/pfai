"""PHASE 15 — unified engineering + cyber defense + coding + web integration tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.elite.unified_orchestrator import EliteOrchestrator
from pfai.elite.web_fabric import (
    SearchProvider,
    FetchProvider,
    MockWebProvider,
    WebProvider,
    web_config_report,
    WEB_PROVIDER_UNAVAILABLE,
)
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.engineering.engineering_workflow import EngineeringWorkflow
from pfai.engineering.phase15_gates import evaluate_phase15_gates
from pfai.engineering.phase15_skills import register_phase15_skills
from pfai.engineering.project_inspector import ProjectInspector
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.security_regression import SecurityRegressionEngine
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.unified_coding_workflow import UnifiedCodingWorkflow
from pfai.model_router import ModelRouter


class TestProjectInspector(unittest.TestCase):
    def test_inspect_structure(self):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        out = ProjectInspector(tmp).inspect()
        self.assertTrue(out["ok"])
        self.assertTrue(out["has_tests"])
        self.assertIn("requirements.txt", out["dependencies"]["manifests"])
        self.assertIn("flask", out["dependencies"]["packages"])


class TestEngineeringWorkflowGuards(unittest.TestCase):
    def test_refuses_empty_affected_files(self):
        tmp = tempfile.mkdtemp()
        wf = EngineeringWorkflow(tmp)
        plan = wf.plan_modification(reason="x", affected_files=[])
        self.assertFalse(plan["ok"])

    def test_plan_apply_rollback_on_test_failure(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("app.py", "x=1\n", overwrite=True)
        ws.write_text("tests/test_app.py", "def test_ok():\n    assert True\n", overwrite=True)
        wf = EngineeringWorkflow(tmp)
        plan = wf.plan_modification(reason="break tests", affected_files=["tests/test_app.py"])
        self.assertTrue(plan["ok"])
        out = wf.apply_plan(
            plan["plan"],
            {"tests/test_app.py": "def test_ok():\n    assert False\n"},
            approved=True,
            actor="t",
            run_tests=True,
        )
        self.assertTrue(out.get("rolled_back"))
        self.assertEqual(ws.read_text("tests/test_app.py")["content"], "def test_ok():\n    assert True\n")

    def test_does_not_write_unrelated_files(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("keep.py", "ok\n", overwrite=True)
        wf = EngineeringWorkflow(tmp)
        plan = wf.plan_modification(reason="only a.py", affected_files=["a.py"])
        out = wf.apply_plan(plan["plan"], {"a.py": "print(1)\n", "keep.py": "HACKED\n"}, approved=True, actor="t", run_tests=False)
        # keep.py not in plan — must remain unchanged even if writer map includes it
        self.assertEqual(ws.read_text("keep.py")["content"], "ok\n")
        self.assertTrue((Path(tmp) / "a.py").exists() or out.get("rolled_back") is False)


class TestUnifiedCodingWorkflow(unittest.TestCase):
    def test_build_website(self):
        tmp = tempfile.mkdtemp()
        wf = UnifiedCodingWorkflow(root=tmp)
        out = wf.handle("Build me a website for Harbor Notes", actor="t", approved=True)
        self.assertEqual(out["intent"], "build")
        self.assertTrue(out.get("complete"), out)
        self.assertFalse(out.get("deployment_claimed"))

    def test_security_review_local(self):
        tmp = tempfile.mkdtemp()
        p = Path(tmp) / "bad.py"
        p.write_text("API_KEY = 'supersecretvalue123'\n", encoding="utf-8")
        wf = UnifiedCodingWorkflow(root=tempfile.mkdtemp())
        out = wf.handle(
            "Check my application for security problems",
            project_path=tmp,
            actor="owner",
            approved=True,
        )
        self.assertEqual(out["intent"], "security_review")
        self.assertGreaterEqual(out.get("finding_count", 0), 1)

    def test_unauthorized_external_denied(self):
        wf = UnifiedCodingWorkflow(root=tempfile.mkdtemp())
        out = wf.handle(
            "Find security weaknesses in https://example.com",
            actor="anon",
            approved=False,
            declaration="",
        )
        self.assertTrue(out.get("denied") or out.get("decision") == "DENY" or out.get("ok") is False)


class TestSecurityRegression(unittest.TestCase):
    def test_verify_and_regression(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("app.py", "API_KEY = 'supersecretvalue123'\nprint(1)\n", overwrite=True)
        finding = SecureCodeAnalyzer(tmp).analyze()["findings"][0]
        loop = RemediationLoop(ws)
        report = loop.run(approved=True, actor="t", auto_apply=True)
        self.assertGreaterEqual(report.get("fixed_count", 0), 1)
        engine = SecurityRegressionEngine(tmp)
        v = engine.verify_finding_fixed(finding)
        self.assertTrue(v["verified"])
        self.assertTrue(v["marked_fixed"])
        gen = engine.generate_from_finding({**finding, "verified": True, "marked_fixed": True})
        self.assertTrue(gen["ok"], gen)
        run = engine.run_regressions()
        self.assertTrue(run.get("passed"), run)

    def test_does_not_mark_fixed_without_verification(self):
        tmp = tempfile.mkdtemp()
        ws = ProjectWorkspace(tmp)
        ws.write_text("app.py", "API_KEY = 'supersecretvalue123'\n", overwrite=True)
        engine = SecurityRegressionEngine(tmp)
        finding = {"finding_id": "x", "category": "secret_exposure", "file_path": "app.py"}
        v = engine.verify_finding_fixed(finding)
        self.assertFalse(v["marked_fixed"])
        gen = engine.generate_from_finding(finding)
        self.assertFalse(gen["ok"])


class TestPhase15SkillsAndAuth(unittest.TestCase):
    def test_register_skills(self):
        tmp = tempfile.mkdtemp()
        reg = SkillRegistry2(path=str(Path(tmp) / "s.sqlite3"))
        boot = register_phase15_skills(reg, activate=True)
        self.assertGreaterEqual(boot["count"], 15)

    def test_target_auth_still_deny_default(self):
        gate = TargetAuthorizationGate(path=str(Path(tempfile.mkdtemp()) / "a.jsonl"))
        out = gate.require_authorized("https://example.com", declaration="", scope="", approved=True)
        self.assertEqual(out["decision"], "DENY")


class TestWebAliasesHonest(unittest.TestCase):
    def test_aliases_and_not_fabricated(self):
        self.assertTrue(issubclass(SearchProvider, object))
        self.assertTrue(issubclass(FetchProvider, object))
        self.assertTrue(issubclass(MockWebProvider, SearchProvider))
        self.assertIs(WebProvider.__name__, "WebInformationFabric")
        report = web_config_report()
        self.assertIn(report["WEB_FABRIC_STATUS"], ("NOT_CONFIGURED", "TEST_ONLY", "READY"))
        # Unavailable path must not fabricate
        from pfai.elite.web_fabric import UnavailableWebSearchProvider

        r = UnavailableWebSearchProvider().search("test")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], WEB_PROVIDER_UNAVAILABLE)
        self.assertEqual(r["results"], [])


class TestUnifiedChatPhase15(unittest.TestCase):
    def test_build_via_chat(self):
        tmp = tempfile.mkdtemp()
        elite = EliteOrchestrator(
            root=tmp,
            model_router=ModelRouter.from_config({"provider": "echo"}),
            bootstrap_skills=True,
        )
        out = elite.handle("Build me a website for Lake Cafe", actor="owner", approved=True)
        self.assertEqual(out["phase"], 15)
        self.assertTrue((out.get("phase15") or out.get("phase14") or {}).get("complete"))

    def test_security_via_chat_denied_without_auth(self):
        tmp = tempfile.mkdtemp()
        elite = EliteOrchestrator(root=tmp, model_router=ModelRouter.from_config({"provider": "echo"}))
        out = elite.handle("Find security weaknesses", actor="anon", approved=False)
        payload = out.get("phase15") or out.get("phase14") or {}
        self.assertTrue(payload.get("denied") or payload.get("decision") == "DENY" or out.get("ok") is False or payload.get("error"))

    def test_models_intact(self):
        root = Path(__file__).resolve().parents[1] / "data" / "longevity" / "training_phase9_verify" / "models"
        self.assertTrue((root / "model-v0007").is_dir())
        self.assertTrue((root / "model-v0001").is_dir())


class TestPhase15Gates(unittest.TestCase):
    def test_gates_pass_with_suite_evidence(self):
        g = evaluate_phase15_gates(full_tests={"ran": True, "failed": 0, "passed": 10, "skipped": 0})
        self.assertEqual(g["EXACT_BLOCKERS"], [], g)
        self.assertTrue(g["PHASE_15_ALLOWED"], g)
        self.assertFalse(g["PHASE_16_ALLOWED"])
        self.assertEqual(g["PHASE_15_STATUS"], "PASS")

    def test_gates_block_without_suite(self):
        from pfai.engineering import phase15_gates as gmod

        path = gmod._evidence_path()
        backup = path.read_text(encoding="utf-8") if path.is_file() else None
        try:
            if path.is_file():
                path.unlink()
            g = evaluate_phase15_gates()
            self.assertFalse(g["PHASE_15_ALLOWED"])
            self.assertIn("full_suite_evidence_missing", g["EXACT_BLOCKERS"])
            self.assertFalse(g["PHASE_16_ALLOWED"])
        finally:
            if backup is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
