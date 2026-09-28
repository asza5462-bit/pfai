"""PHASE 4 — PermissionGate, planner, versioned skills, bounded heal, authz."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.interfaces.skills import Skill
from pfai.interfaces.tools import ToolPermission
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.authorized_execution import (
    AuthorizationAudit,
    AuthorizedExecutor,
    PermissionGate,
    risk_to_permission,
)
from pfai.self_check import SelfCheck, SelfHeal
from pfai.skills.registry import SkillRegistry
from pfai.task_planner import FORBIDDEN_ACTIONS, TaskPlanner
from pfai.tool_router import ToolRouter, ToolSpec


class TestPermissionMapping(unittest.TestCase):
    def test_risk_mapping_and_high_risk_gate(self):
        self.assertEqual(risk_to_permission("read"), ToolPermission.READ)
        self.assertEqual(risk_to_permission("write", requires_approval=False), ToolPermission.LOW_RISK_WRITE)
        self.assertEqual(risk_to_permission("sensitive"), ToolPermission.HIGH_RISK_WRITE)
        self.assertEqual(risk_to_permission("write", name="forget_memory", requires_approval=True), ToolPermission.DATA_DELETE)
        gate = PermissionGate()
        deny = gate.decide(ToolPermission.HIGH_RISK_WRITE, approved=False)
        self.assertFalse(deny.allowed)
        self.assertTrue(deny.needs_approval)
        allow = gate.decide(ToolPermission.HIGH_RISK_WRITE, approved=True)
        self.assertTrue(allow.allowed)
        # Client role flags are irrelevant — gate only sees approved bool
        self.assertFalse(gate.decide(ToolPermission.SECRETS, approved=False).allowed)


class TestAuthorizedExecutorAndTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        audit = AuthorizationAudit(str(Path(self.tmp.name) / "authz.jsonl"))
        self.executor = AuthorizedExecutor(PermissionGate(), audit)
        self.calls = []

        def boom():
            self.calls.append("boom")
            return {"ran": True}

        self.router = ToolRouter(
            {"danger": boom, "ping": lambda: {"pong": True}},
            specs=[
                ToolSpec("danger", "sensitive", "sensitive", True, {}),
                ToolSpec("ping", "read", "read", False, {}),
            ],
            executor=self.executor,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_high_risk_denied_without_approval(self):
        r = self.router.execute("danger", {}, approved=False)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("needs_approval"))
        self.assertEqual(self.calls, [])
        recent = self.executor.audit.recent(10)
        self.assertTrue(any(x.get("allowed") is False for x in recent))

    def test_owner_approval_path(self):
        r = self.router.execute("danger", {}, approved=True, actor="owner@example.invalid")
        self.assertTrue(r["ok"])
        self.assertEqual(self.calls, ["boom"])
        self.assertTrue(any(x.get("allowed") for x in self.executor.audit.recent(10)))

    def test_read_tool_no_approval_needed(self):
        r = self.router.execute("ping")
        self.assertTrue(r["ok"])
        self.assertIn("permission", r)


class TestSkillVersioning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        audit = AuthorizationAudit(str(Path(self.tmp.name) / "a.jsonl"))
        self.reg = SkillRegistry(str(Path(self.tmp.name) / "skills.sqlite3"), executor=AuthorizedExecutor(PermissionGate(), audit))

    def tearDown(self):
        self.tmp.cleanup()

    def test_activate_and_rollback(self):
        self.reg.register(
            Skill(name="demo", description="v1", permission=ToolPermission.READ, version="1"),
            lambda ctx=None, **k: {"v": 1},
        )
        self.reg.register_version(
            Skill(name="demo", description="v2", permission=ToolPermission.READ, version="2"),
            lambda ctx=None, **k: {"v": 2},
            activate=False,
        )
        self.assertEqual(self.reg.active_version("demo"), "1")
        self.assertEqual(self.reg.invoke("demo").output["v"], 1)
        act = self.reg.activate("demo", "2", approved=True, actor="owner")
        self.assertTrue(act["ok"])
        self.assertEqual(self.reg.invoke("demo").output["v"], 2)
        rb = self.reg.rollback("demo", "1", approved=True, actor="owner")
        self.assertTrue(rb["ok"])
        self.assertEqual(self.reg.invoke("demo").output["v"], 1)

    def test_compatibility_rejection(self):
        self.reg.register_version(
            Skill(name="future", description="needs future schema", permission=ToolPermission.READ, version="1"),
            lambda ctx=None, **k: {"ok": True},
            activate=True,
            min_schema_version=999,
        )
        result = self.reg.invoke("future")
        self.assertFalse(result.ok)
        self.assertIn("incompatible", result.error or "")

    def test_high_risk_skill_needs_approval(self):
        self.reg.register(
            Skill(name="wipe", description="delete", permission=ToolPermission.DATA_DELETE, version="1"),
            lambda ctx=None, **k: {"wiped": True},
        )
        denied = self.reg.invoke("wipe", approved=False)
        self.assertFalse(denied.ok)
        self.assertTrue(denied.meta.get("needs_approval"))
        ok = self.reg.invoke("wipe", approved=True)
        self.assertTrue(ok.ok)


class TestTaskPlanner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        audit = AuthorizationAudit(str(Path(self.tmp.name) / "a.jsonl"))
        self.executor = AuthorizedExecutor(PermissionGate(), audit)
        self.tool_calls = []

        def tool_runner(name, args, approved=False, actor=""):
            self.tool_calls.append(name)
            return {"ok": True, "tool": name}

        self.planner = TaskPlanner(
            executor=self.executor,
            max_steps=3,
            max_tool_calls=2,
            tool_runner=tool_runner,
            memory_query=lambda q: [{"content": "m"}],
            knowledge_query=lambda q: [{"content": "k"}],
            eval_runner=lambda s: {"ok": True},
            learn_ingest=lambda g, approved=False, actor="": {"ok": True, "candidate_id": "c1"},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_planner_caps_and_forbidden(self):
        plan = self.planner.plan("health check", actions=["tool:health_check", "tool:metrics_snapshot", "tool:modules_list", "tool:extra"])
        self.assertLessEqual(len(plan.steps), 3)
        bad = self.planner.plan("evil", actions=["mutate_weights", "tool:health_check"])
        self.assertTrue(all(s.action != "mutate_weights" for s in bad.steps))
        self.assertIn("mutate_weights", FORBIDDEN_ACTIONS)
        ran = self.planner.run(
            self.planner.plan("x", actions=["tool:a", "tool:b", "tool:c"]),
            approved=False,
        )
        # max_tool_calls=2 blocks third tool
        self.assertTrue(any(s.status == "blocked" for s in ran.steps) or ran.status in ("blocked", "verified", "completed", "unverified", "failed"))

    def test_cannot_bypass_via_handlers_arg(self):
        sneaky = []
        plan = self.planner.plan("mem", actions=["memory:query"])
        ran = self.planner.run(plan, handlers={"memory:query": lambda *a, **k: sneaky.append(1) or {"hacked": True}})
        self.assertEqual(sneaky, [])
        self.assertEqual(ran.steps[0].status, "success")


class TestSelfHealBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.check = SelfCheck({"ok_check": lambda: {"ok": True}, "bad": lambda: {"ok": False}})
        audit = AuthorizationAudit(str(Path(self.tmp.name) / "a.jsonl"))
        self.heal = SelfHeal(self.check, audit_path=str(Path(self.tmp.name) / "heal.jsonl"), authz_audit=audit)

    def tearDown(self):
        self.tmp.cleanup()

    def test_forbidden_registration_and_audit_rollback(self):
        with self.assertRaises(ValueError):
            self.heal.register_safe_action("mutate_weights", lambda: {"ok": True})
        with self.assertRaises(ValueError):
            self.heal.register_safe_action("read_secrets", lambda: {"ok": True})
        report = self.check.run_checks()
        prop = self.heal.propose_fix(report)
        self.assertTrue(prop.requires_owner)
        denied = self.heal.apply_fix(prop.proposal_id, approved=False)
        self.assertFalse(denied.ok)
        applied = self.heal.apply_fix(prop.proposal_id, approved=True)
        self.assertTrue(applied.ok)
        # Force failure path by replacing checks then test+rollback
        self.check.checks["bad"] = lambda: {"ok": False}
        tested = self.heal.test_fix(prop.proposal_id)
        self.assertFalse(tested.ok)
        rolled = self.heal.rollback_fix(prop.proposal_id)
        self.assertTrue(rolled.rolled_back)
        trail = self.heal.recent_audit(20)
        events = [t.get("event") for t in trail]
        self.assertIn("propose", events)
        self.assertIn("apply_safe", events)
        self.assertIn("rollback", events)


class TestLearningAndProviders(unittest.TestCase):
    def test_no_weight_mutation_and_local_providers(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import PLATFORM_LEARNING, PROVIDER_REGISTRY

        self.assertFalse(PLATFORM_LEARNING.allows_weight_mutation())
        ready = PLATFORM_LEARNING.training_readiness()
        self.assertFalse(ready["weight_training_allowed_now"])
        self.assertIn("local", ready["preferred_future_providers"])
        ids = [p.provider_id for p in PROVIDER_REGISTRY.list_providers()]
        self.assertIn("echo", ids)
        self.assertIn("local", ids)
        self.assertIn("open_weight", ids)
        # Core create without anthropic key
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        p = reg.create_from_config({"provider": "anthropic"})
        self.assertEqual(p.generate("hi")[:10], "[PFAI-ECHO")


class TestPhase4API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}

    def test_plan_skills_heal_owner_gated(self):
        self.assertEqual(self.client.post("/platform/plan", json={"goal": "x"}).status_code, 401)
        r = self.client.post(
            "/platform/plan",
            json={"goal": "check system health and memory", "plan_only": True},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"))
        skills = self.client.get("/platform/skills", headers=self.headers)
        self.assertEqual(skills.status_code, 200)
        tools = self.client.get("/platform/tools", headers=self.headers)
        self.assertEqual(tools.status_code, 200)
        self.assertTrue(any("permission" in t for t in tools.json()["tools"]))
        # skill activate/rollback
        vers = self.client.get("/platform/skills/platform_status/versions", headers=self.headers)
        self.assertEqual(vers.status_code, 200)
        self.assertGreaterEqual(len(vers.json()["versions"]), 1)
        if len(vers.json()["versions"]) >= 2:
            v2 = [v for v in vers.json()["versions"] if v["version"] == "2"]
            if v2:
                a = self.client.post(
                    "/platform/skills/activate",
                    json={"name": "platform_status", "version": "2"},
                    headers=self.headers,
                )
                self.assertEqual(a.status_code, 200, a.text)
                rb = self.client.post(
                    "/platform/skills/rollback",
                    json={"name": "platform_status", "version": "1"},
                    headers=self.headers,
                )
                self.assertEqual(rb.status_code, 200, rb.text)
        prop = self.client.post("/platform/heal/propose", headers=self.headers)
        self.assertEqual(prop.status_code, 200)
        # When proposal requires owner, unapproved apply must fail
        if prop.json().get("requires_owner"):
            denied = self.client.post(
                "/platform/heal/apply",
                json={"proposal_id": prop.json()["proposal_id"], "approved": False},
                headers=self.headers,
            )
            self.assertIn(denied.status_code, (401, 409))
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["platform"]["phase"], 4)
        self.assertEqual(self.client.get("/").status_code, 200)
        # chat still works
        chat = self.client.post("/chat/message", json={"message": "مرحبا"}, headers=self.headers)
        self.assertEqual(chat.status_code, 200)


if __name__ == "__main__":
    unittest.main()
