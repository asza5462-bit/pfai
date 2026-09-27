"""PHASE 1 contract tests — interfaces, package imports, SkillRegistry scaffold.

No API/Dashboard behavior changes are asserted here beyond import stability.
"""
from __future__ import annotations

import unittest

from pfai.interfaces import (
    EvalCase,
    EvalReport,
    Goal,
    KnowledgeHit,
    MemoryScope,
    ModelRole,
    ModelRouterProtocol,
    OrchestratorRequest,
    OrchestratorResult,
    PlanStep,
    Skill,
    SkillContext,
    SkillRegistryProtocol,
    SkillResult,
    SelfCheckReport,
    TaskPlan,
    TimelineStatus,
    ToolPermission,
)
from pfai.model import EchoProvider
from pfai.model_router import ModelRouter
from pfai.orchestrator import Orchestrator
from pfai.skills import SkillRegistry
from pfai.skills.registry import SkillRegistry as SkillRegistryDirect


class TestInterfaceExports(unittest.TestCase):
    def test_orchestrator_request_result_defaults(self):
        req = OrchestratorRequest(goal="فحص الصحة")
        self.assertEqual(req.mode, "general")
        self.assertTrue(req.require_owner_for_sensitive)
        res = OrchestratorResult(ok=True, reply="ok", timeline=[TimelineStatus("done", "جاهز")])
        self.assertEqual(len(res.timeline), 1)
        self.assertFalse(res.needs_approval)

    def test_model_roles_cover_architecture(self):
        expected = {"default", "coding", "reasoning", "fast", "vision", "embedding"}
        self.assertEqual({r.value for r in ModelRole}, expected)

    def test_tool_permission_owner_gate(self):
        self.assertFalse(ToolPermission.READ.requires_owner_gate())
        self.assertFalse(ToolPermission.LOW_RISK_WRITE.requires_owner_gate())
        for p in (
            ToolPermission.HIGH_RISK_WRITE,
            ToolPermission.PRODUCTION,
            ToolPermission.SECRETS,
            ToolPermission.DATA_DELETE,
        ):
            self.assertTrue(p.requires_owner_gate())

    def test_memory_scopes(self):
        self.assertIn(MemoryScope.COMMAND, MemoryScope)
        self.assertIn(MemoryScope.CODING, MemoryScope)


class TestScaffoldImports(unittest.TestCase):
    def test_scaffold_modules_import(self):
        import pfai.goal_system as goal_system
        import pfai.knowledge_layer as knowledge_layer
        import pfai.memory_system as memory_system
        import pfai.self_check as self_check
        import pfai.self_heal as self_heal
        import pfai.task_planner as task_planner

        self.assertEqual(memory_system.PHASE, 3)
        self.assertEqual(knowledge_layer.PHASE, 3)
        self.assertEqual(task_planner.PHASE, 4)
        self.assertEqual(self_check.PHASE, 7)
        self.assertEqual(self_heal.PHASE, 8)
        self.assertEqual(goal_system.PHASE, 9)

    def test_orchestrator_placeholder_raises(self):
        orch = Orchestrator()
        with self.assertRaises(NotImplementedError):
            orch.handle(OrchestratorRequest(goal="x"))

    def test_model_router_echo_when_provided(self):
        router = ModelRouter({ModelRole.DEFAULT.value: EchoProvider()})
        provider = router.resolve(ModelRole.DEFAULT)
        self.assertTrue(provider.generate("hi").startswith("[PFAI-ECHO]"))
        desc = router.describe()
        self.assertFalse(desc["anthropic_required"])
        self.assertIn("default", desc["roles"])

    def test_model_router_falls_back_to_default(self):
        router = ModelRouter({ModelRole.DEFAULT.value: EchoProvider()})
        provider = router.resolve(ModelRole.CODING)
        self.assertTrue(provider.generate("hi").startswith("[PFAI-ECHO]"))
        self.assertFalse(router.describe()["anthropic_required"])


class TestSkillRegistryScaffold(unittest.TestCase):
    def test_register_list_invoke(self):
        reg = SkillRegistry()
        self.assertIs(SkillRegistry, SkillRegistryDirect)

        def ping(msg: str = "", ctx=None):
            return {"echo": msg, "locale": getattr(ctx, "locale", None)}

        reg.register(
            Skill(name="ping", description="echo", permission=ToolPermission.READ, tags=("test",)),
            ping,
        )
        skills = reg.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "ping")
        result = reg.invoke("ping", {"msg": "hi"}, ctx=SkillContext(locale="ar"))
        self.assertTrue(result.ok)
        self.assertEqual(result.output["echo"], "hi")

    def test_sensitive_skill_needs_approval(self):
        reg = SkillRegistry()

        def danger(**_kwargs):
            return {"wiped": True}

        reg.register(
            Skill(name="wipe", description="delete", permission=ToolPermission.DATA_DELETE),
            danger,
        )
        blocked = reg.invoke("wipe", {})
        self.assertFalse(blocked.ok)
        self.assertTrue(blocked.meta.get("needs_approval"))
        allowed = reg.invoke("wipe", {}, approved=True)
        self.assertTrue(allowed.ok)

    def test_isinstance_protocols_structural(self):
        reg = SkillRegistry()
        self.assertIsInstance(reg, SkillRegistryProtocol)
        router = ModelRouter({ModelRole.DEFAULT.value: EchoProvider()})
        self.assertIsInstance(router, ModelRouterProtocol)


class TestDataclassHelpers(unittest.TestCase):
    def test_plan_and_eval_shapes(self):
        plan = TaskPlan(plan_id="p1", goal="g", steps=[PlanStep(id="1", action="health_check")])
        self.assertEqual(plan.status, "pending")
        report = EvalReport(suite="smoke", passed=1, ok=True, cases=[{"id": "a"}])
        self.assertEqual(report.passed, 1)
        hit = KnowledgeHit(source="docs", content="x", score=0.9)
        self.assertTrue(hit.verified)
        goal = Goal(goal_id="g1", title="stabilize")
        self.assertEqual(goal.status, "open")
        case = EvalCase(case_id="c1", name="health")
        self.assertEqual(case.name, "health")
        self.assertIsInstance(SkillResult(ok=True), SkillResult)
        self.assertIsInstance(SelfCheckReport(ok=True), SelfCheckReport)


class TestExistingSurfaceUntouched(unittest.TestCase):
    """Smoke: api app still imports and exposes prior routes."""

    def test_api_still_loads_health_chat_coding(self):
        from pfai.api import app

        paths = {getattr(r, "path", None) for r in app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/chat/message", paths)
        self.assertIn("/", paths)
        self.assertTrue(any(isinstance(p, str) and p.startswith("/coding/") for p in paths))


if __name__ == "__main__":
    unittest.main()
