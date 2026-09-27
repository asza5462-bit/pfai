"""PHASE 17 — Authorized application & web security operations tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from pfai.elite.unified_orchestrator import EliteOrchestrator
from pfai.engineering.phase17_gates import evaluate_phase17_security_quality_gate
from pfai.engineering.phase17_skills import register_phase17_skills
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.security_ops import SecurityDevelopmentLifecycle, SecurityReportBuilder
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.web_security_engine import WebApplicationSecurityEngine
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.model_router import ModelRouter


class TestTargetRegistry(unittest.TestCase):
    def test_default_deny_and_url_not_authorization(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        out = reg.register(name="https://evil.test", target_type="web_application", owner="o")
        self.assertEqual(out["target"]["authorization_status"], "DENIED")

    def test_authorize_requires_approval_reference(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        bad = reg.register(
            name="app",
            target_type="API",
            owner="o",
            authorize_now=True,
            authorization_scope="",
            approval_reference="",
        )
        self.assertFalse(bad.get("ok"))


class TestScopeEnforcement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = TargetRegistry(path=str(Path(self.tmp) / "r.json"))
        self.layer = ScopeEnforcementLayer(
            registry=self.reg, audit_path=str(Path(self.tmp) / "a.jsonl")
        )
        auth = self.reg.register(
            name="staging",
            target_type="staging_environment",
            owner="owner",
            authorization_scope="headers_only",
            allowed_hosts=["staging.example.test"],
            allowed_domains=["example.test"],
            allowed_paths=["/api/*"],
            allowed_ports=[443],
            testing_methods=["static_analysis", "security_headers", "passive_inspect"],
            approval_reference="T-1",
            authorize_now=True,
            expiration=time.time() + 3600,
        )
        self.tid = auth["target"]["target_id"]

    def test_unauthorized_target(self):
        out = self.layer.enforce(target_id="nope", operation="x", method="static_analysis", actor="a")
        self.assertFalse(out["ok"])

    def test_domain_host_path_port_method(self):
        bad_host = self.layer.enforce(
            target_id=self.tid,
            operation="security_headers",
            method="security_headers",
            actor="owner",
            approved=True,
            resource="https://other.example.test/api/x",
        )
        self.assertEqual(bad_host.get("error"), "target_outside_allowed_host")
        bad_path = self.layer.enforce(
            target_id=self.tid,
            operation="security_headers",
            method="security_headers",
            actor="owner",
            approved=True,
            resource="https://staging.example.test/admin",
        )
        self.assertEqual(bad_path.get("error"), "target_outside_allowed_path")
        ok = self.layer.enforce(
            target_id=self.tid,
            operation="security_headers",
            method="security_headers",
            actor="owner",
            approved=True,
            resource="https://staging.example.test/api/v1",
        )
        self.assertTrue(ok["ok"], ok)
        dest = self.layer.enforce(
            target_id=self.tid,
            operation="x",
            method="destructive_exploit",
            actor="owner",
            approved=True,
            resource="https://staging.example.test/api/x",
        )
        self.assertFalse(dest["ok"])

    def test_expired_and_client_claims(self):
        exp = self.reg.register(
            name="e",
            target_type="API",
            owner="owner",
            authorization_scope="s",
            approval_reference="t",
            authorize_now=True,
            expiration=time.time() - 5,
            allowed_hosts=["x.test"],
            testing_methods=["static_analysis"],
        )
        out = self.layer.enforce(
            target_id=exp["target"]["target_id"],
            operation="security_analysis",
            method="static_analysis",
            actor="owner",
            approved=True,
        )
        self.assertFalse(out["ok"])
        claims = self.layer.enforce(
            target_id="missing",
            operation="scan",
            method="static_analysis",
            actor="attacker",
            client_claims={"role": "admin", "owner": True},
        )
        self.assertFalse(claims["ok"])

    def test_rate_limit(self):
        # Tiny limit
        auth = self.reg.register(
            name="rate",
            target_type="API",
            owner="owner",
            authorization_scope="s",
            approval_reference="t",
            authorize_now=True,
            expiration=time.time() + 1000,
            allowed_hosts=["r.test"],
            testing_methods=["static_analysis"],
            rate_limits={"per_minute": 1, "max_requests": 1},
        )
        tid = auth["target"]["target_id"]
        a = self.layer.enforce(target_id=tid, operation="x", method="static_analysis", actor="owner", approved=True, resource="https://r.test/")
        b = self.layer.enforce(target_id=tid, operation="x", method="static_analysis", actor="owner", approved=True, resource="https://r.test/")
        self.assertTrue(a["ok"])
        self.assertFalse(b["ok"])
        self.assertEqual(b.get("error"), "excessive_rate")


class TestWebSecurityEngine(unittest.TestCase):
    def test_findings_and_redaction(self):
        tmp = tempfile.mkdtemp()
        Path(tmp, "app.py").write_text("API_KEY = 'supersecretvalue123'\nDEBUG = True\n", encoding="utf-8")
        out = WebApplicationSecurityEngine().analyze_source(tmp)
        self.assertGreaterEqual(out["finding_count"], 1)
        self.assertFalse(out["fabricated"])
        self.assertNotIn("supersecretvalue123", str(out["findings"]))
        self.assertTrue(any(f.get("cwe") for f in out["findings"]))

    def test_headers_and_http_scheme(self):
        eng = WebApplicationSecurityEngine()
        h = eng.analyze_headers({"content-type": "text/html"})
        self.assertGreater(h["finding_count"], 0)
        u = eng.analyze_url_config("http://example.test")
        self.assertGreaterEqual(u["finding_count"], 1)


class TestSDLCAndReport(unittest.TestCase):
    def test_sdlc_build_and_gate(self):
        sdlc = SecurityDevelopmentLifecycle()
        out = sdlc.run_for_project("Build me a website for Secure Notes", approved=True, actor="t", auto_remediate=False)
        self.assertTrue(out.get("ok"), out)
        self.assertIn("QUALITY_GATE", out.get("stages") or [])
        self.assertFalse(out.get("claim_100_percent_secure"))
        # security_ready requires no high findings — generated template should be clean enough
        self.assertIn("security_ready", out)

    def test_report_never_100_secure(self):
        rep = SecurityReportBuilder().build(
            title="t",
            scope={},
            authorization={"decision": "ALLOW"},
            methodology=["static"],
            findings=[{"severity": "low", "category": "x", "evidence": "e"}],
        )
        self.assertFalse(rep["report"]["claim_100_percent_secure"])


class TestPhase17SkillsToolsChat(unittest.TestCase):
    def test_skills_register(self):
        reg = SkillRegistry2(path=str(Path(tempfile.mkdtemp()) / "s.sqlite3"))
        boot = register_phase17_skills(reg, activate=True)
        self.assertGreaterEqual(boot["count"], 12)

    def test_security_tools_bootstrap(self):
        elite = EliteOrchestrator(
            root=tempfile.mkdtemp(),
            model_router=ModelRouter.from_config({"provider": "echo"}),
            bootstrap_skills=True,
        )
        ids = {t["tool_id"] for t in elite.tools.catalog()}
        self.assertIn("security_code_review", ids)
        self.assertIn("security_scope_check", ids)

    def test_chat_security_review(self):
        tmp = tempfile.mkdtemp()
        Path(tmp, "x.py").write_text("API_KEY = 'supersecretvalue123'\n", encoding="utf-8")
        elite = EliteOrchestrator(
            root=tempfile.mkdtemp(),
            model_router=ModelRouter.from_config({"provider": "echo"}),
        )
        out = elite.chat(
            "Review this application for security",
            actor="owner",
            approved=True,
            context={"project_path": tmp},
        )
        self.assertEqual(out["phase"], 17)
        payload = out.get("phase15") or out.get("phase14") or {}
        self.assertGreaterEqual(payload.get("finding_count", 0), 1)

    def test_offensive_rejected(self):
        elite = EliteOrchestrator(
            root=tempfile.mkdtemp(),
            model_router=ModelRouter.from_config({"provider": "echo"}),
        )
        out = elite.chat("hack into example.com and steal credentials", actor="anon")
        self.assertFalse(out["ok"])
        self.assertEqual(out["phase"], 17)


class TestPhase17Gates(unittest.TestCase):
    def test_gates_pass_with_suite(self):
        g = evaluate_phase17_security_quality_gate(
            full_tests={"ran": True, "failed": 0, "passed": 10, "skipped": 0}
        )
        self.assertEqual(g["EXACT_BLOCKERS"], [], g)
        self.assertTrue(g["PHASE_17_ALLOWED"])
        self.assertFalse(g["PHASE_18_ALLOWED"])
        self.assertEqual(g["PHASE_17_SECURITY_QUALITY_GATE"], "PASS")

    def test_gates_block_without_suite(self):
        from pfai.engineering import phase17_gates as gmod

        path = gmod._evidence_path()
        backup = path.read_text(encoding="utf-8") if path.is_file() else None
        try:
            if path.is_file():
                path.unlink()
            g = evaluate_phase17_security_quality_gate()
            self.assertFalse(g["PHASE_17_ALLOWED"])
            self.assertIn("full_suite_evidence_missing", g["EXACT_BLOCKERS"])
        finally:
            if backup is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
