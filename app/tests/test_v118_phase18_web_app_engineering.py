"""PHASE 18 — Authorized Web & Application Engineering Fabric tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.unified_orchestrator import EliteOrchestrator
from pfai.engineering.application_engineering import ApplicationEngineering
from pfai.engineering.authorized_web_ops import AuthorizedWebFabricOps
from pfai.engineering.coding_agent_bridge import CodingAgentBridge
from pfai.engineering.engineering_metrics import EngineeringMetrics
from pfai.engineering.phase18_chat import Phase18ChatFabric
from pfai.engineering.phase18_gates import evaluate_phase18_gates
from pfai.engineering.phase18_security import Phase18SecurityAnalysis
from pfai.engineering.phase18_skills import register_phase18_skills
from pfai.engineering.remediation_engine import RemediationEngine
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.target_registry import TargetRegistry


class TestTargetRegistryV2(unittest.TestCase):
    def test_default_deny_and_aliases(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        out = reg.register(name="https://evil.test", target_type="web_app", owner="o")
        self.assertEqual(out["target"]["authorization_status"], "DENIED")
        self.assertEqual(out["target"]["version"], 1)
        self.assertIn("audit_metadata", out["target"])

    def test_authorize_requires_owner_scope_approval(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        bad = reg.register(
            name="app",
            target_type="api",
            owner="o",
            authorize_now=True,
            scope="",
            approval_reference="",
        )
        self.assertFalse(bad.get("ok"))
        amb = reg.register(
            name="amb",
            target_type="web_app",
            owner="anonymous",
            authorize_now=True,
            scope="x",
            approval_reference="t1",
        )
        self.assertFalse(amb.get("ok"))
        self.assertEqual(amb.get("error"), "ambiguous_authorization")

    def test_resolve_unknown(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        self.assertEqual(reg.resolve(target_id="nope").get("error"), "unknown_target")
        self.assertEqual(reg.resolve(name="https://x.test").get("error"), "unregistered_target_or_domain")

    def test_version_increments_on_authorize(self):
        reg = TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json"))
        created = reg.register(name="a", target_type="local_project", owner="owner")
        tid = created["target"]["target_id"]
        auth = reg.authorize(
            tid,
            approval_reference="T-18",
            authorization_scope="static_only",
            actor="owner",
            allowed_actions=["static_analysis", "code_modify"],
        )
        self.assertTrue(auth["ok"])
        self.assertEqual(auth["target"]["version"], 2)
        self.assertEqual(auth["target"]["authorization_status"], "AUTHORIZED")


class TestScopeAndUnauthorized(unittest.TestCase):
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
            scope="headers_only",
            allowed_hosts=["staging.example.test"],
            allowed_domains=["example.test"],
            allowed_paths=["/api/*"],
            allowed_actions=["static_analysis", "security_headers", "passive_inspect", "code_modify"],
            testing_methods=["static_analysis", "security_headers", "passive_inspect"],
            approval_reference="T-18",
            authorize_now=True,
            expiration=time.time() + 3600,
        )
        self.tid = auth["target"]["target_id"]

    def test_unauthorized_and_out_of_scope(self):
        self.assertFalse(self.layer.enforce(target_id="nope", operation="x", method="static_analysis", actor="a")["ok"])
        bad = self.layer.enforce(
            target_id=self.tid,
            operation="security_headers",
            method="security_headers",
            actor="owner",
            approved=True,
            resource="https://other.example.test/api/x",
        )
        self.assertEqual(bad.get("error"), "target_outside_allowed_host")
        ok = self.layer.enforce(
            target_id=self.tid,
            operation="code_modify",
            method="code_modify",
            actor="owner",
            approved=True,
            resource="/local/path",
        )
        self.assertTrue(ok["ok"], ok)


class TestApplicationEngineering(unittest.TestCase):
    def test_build_static_and_adapters(self):
        eng = ApplicationEngineering(root=tempfile.mkdtemp(prefix="p18-eng-"))
        adapters = eng.supported_adapters()
        self.assertGreaterEqual(len(adapters), 5)
        ids = {a["adapter_id"] for a in adapters}
        self.assertIn("fastapi_python", ids)
        self.assertIn("react_frontend", ids)
        self.assertIn("nextjs", ids)
        out = eng.build("Build a static website called DemoSite", actor="tester", run_tests=True)
        self.assertTrue(out.get("complete"), out)
        self.assertTrue(Path(out["artifact"]["root"]).exists())

    def test_fastapi_adapter(self):
        eng = ApplicationEngineering(root=tempfile.mkdtemp(prefix="p18-api-"))
        out = eng.build("Create a FastAPI backend API called DemoAPI", actor="tester", run_tests=True)
        self.assertTrue(out.get("complete"), out)
        self.assertEqual(out["spec"]["adapter_id"], "fastapi_python")


class TestCodingAgentBridge(unittest.TestCase):
    def test_inspect_search_modify_changeset(self):
        eng = ApplicationEngineering(root=tempfile.mkdtemp(prefix="p18-code-"))
        built = eng.build("Build a static website called CodeSite", actor="t", run_tests=True)
        root = built["artifact"]["root"]
        bridge = CodingAgentBridge(audit_path=str(Path(tempfile.mkdtemp()) / "c.jsonl"))
        insp = bridge.inspect_repository(root, actor="t")
        self.assertTrue(insp["ok"])
        search = bridge.search_code(root, "Content-Security-Policy", actor="t")
        self.assertTrue(search["ok"])
        self.assertGreaterEqual(len(search["hits"]), 1)
        mod = bridge.apply_modification(
            root,
            writers={"NOTES.md": "# notes\n"},
            reason="add notes",
            actor="t",
            approved=True,
        )
        self.assertTrue(mod["ok"], mod)
        self.assertIn("change_set", mod)
        self.assertIn("rollback_information", mod)
        self.assertIn("audit_record", mod)


class TestSecurityAndRemediation(unittest.TestCase):
    def test_analysis_redacts_and_remediates(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "app.py").write_text("API_KEY = 'supersecretvalue123'\n", encoding="utf-8")
        (tmp / "tests").mkdir()
        (tmp / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        analysis = Phase18SecurityAnalysis().analyze(str(tmp))
        self.assertFalse(analysis["claim_100_percent_secure"])
        self.assertGreaterEqual(analysis["finding_count"], 1)
        self.assertNotIn("supersecretvalue123", str(analysis["findings"]))
        engine = RemediationEngine(
            allow_auto_safe_fixes=True,
            audit_path=str(tmp / "rem.jsonl"),
        )
        rem = engine.run(str(tmp), approved=True, actor="owner", auto_apply=True)
        self.assertTrue(rem["ok"])
        self.assertEqual(rem["pipeline"][0], "DETECT")
        self.assertEqual(rem["pipeline"][-1], "AUDIT")


class TestWebFabricOps(unittest.TestCase):
    def test_status_and_reject_unregistered(self):
        ops = AuthorizedWebFabricOps(registry=TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json")))
        st = ops.status()
        self.assertIn(st["WEB_FABRIC_STATUS"], ("NOT_CONFIGURED", "READY"))
        self.assertFalse(st["arbitrary_internet_default"])
        rej = ops.reject_unregistered_url("https://evil.example")
        self.assertTrue(rej["denied"])
        denied = ops.http_request(
            target_id="missing",
            url="https://evil.example",
            actor="a",
            approved=True,
        )
        self.assertTrue(denied.get("denied"))


class TestChatFabric(unittest.TestCase):
    def test_arabic_build_and_url_never_authorizes(self):
        chat = Phase18ChatFabric(
            registry=TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json")),
            root=tempfile.mkdtemp(prefix="p18-chat-"),
        )
        denied = chat.handle("افحص موقعي", context={"url": "https://evil.example"})
        self.assertTrue(denied.get("denied"))
        built = chat.handle("ابنِ لي موقعاً بسيطاً اسمه ArabSite")
        self.assertEqual(built.get("intent"), "build")
        self.assertTrue(built.get("complete"), built)

    def test_remediate_and_improve_intents(self):
        eng = ApplicationEngineering(root=tempfile.mkdtemp(prefix="p18-imp-"))
        built = eng.build("Build a static website called ImpSite", actor="t")
        root = built["artifact"]["root"]
        chat = Phase18ChatFabric(
            registry=TargetRegistry(path=str(Path(tempfile.mkdtemp()) / "r.json")),
            root=tempfile.mkdtemp(),
        )
        rem = chat.handle("أصلح هذه الثغرة", context={"project_path": root, "auto_apply": False})
        self.assertEqual(rem.get("intent"), "remediate")
        imp = chat.handle("طوّر التطبيق", context={"project_path": root})
        self.assertEqual(imp.get("intent"), "improve")


class TestMetricsSecretIsolation(unittest.TestCase):
    def test_metrics_redact_secrets(self):
        path = Path(tempfile.mkdtemp()) / "m.jsonl"
        m = EngineeringMetrics(path=str(path))
        m.record("failed_authorization", 1.0, reason="password=hunter2", token="abc")
        blob = path.read_text(encoding="utf-8")
        self.assertNotIn("hunter2", blob)
        self.assertIn("[REDACTED]", blob)


class TestSkillsAndOrchestrator(unittest.TestCase):
    def test_register_skills_and_boot(self):
        tmp = tempfile.mkdtemp()
        reg = SkillRegistry2(path=str(Path(tmp) / "s.sqlite3"))
        boot = register_phase18_skills(reg, activate=True)
        self.assertGreaterEqual(boot["count"], 8)
        orch = EliteOrchestrator(
            root=str(Path(tmp) / "elite"),
            bootstrap_skills=True,
        )
        self.assertIsNotNone((orch._boot or {}).get("phase18"))
        self.assertGreaterEqual(int((orch._boot["phase18"] or {}).get("count") or 0), 8)


class TestPhase18Gate(unittest.TestCase):
    def test_gate_with_fake_suite_and_phase19_blocked(self):
        g = evaluate_phase18_gates(full_tests={"ran": True, "failed": 0, "passed": 10, "skipped": 0, "total": 10})
        self.assertFalse(g["PHASE_19_ALLOWED"])
        self.assertEqual(g["SANDBOX_STATUS"], "READY_BOUNDED")
        self.assertEqual(g["EMAIL_DELIVERY_STATUS"], "REMOVED")
        self.assertIn(g["WEB_FABRIC_STATUS"], ("NOT_CONFIGURED", "READY"))
        if g["EXACT_BLOCKERS"]:
            # Allow only missing suite when not stamped — we provided fake suite
            self.assertEqual(g["EXACT_BLOCKERS"], [], g["EXACT_BLOCKERS"])
        self.assertEqual(g["PHASE_18_STATUS"], "PASS")


if __name__ == "__main__":
    unittest.main()
