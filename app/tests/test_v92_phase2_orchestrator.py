"""PHASE 2 — Orchestrator, ProviderRegistry/ModelRouter, durable learning."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.interfaces.learning import LearningSource, LearningStatus
from pfai.interfaces.memory import MemoryKind, MemoryRecord
from pfai.interfaces.types import OrchestratorRequest
from pfai.longevity.durable_learning import (
    DurableSafeLearningPipeline,
    KnowledgeVersionStore,
    LearningAuditLog,
)
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.memory import MemoryStore
from pfai.memory_system import LongTermMemory
from pfai.model import EchoProvider
from pfai.model_mock import MockCommandProvider
from pfai.model_router import ModelRouter
from pfai.orchestrator import Orchestrator
from pfai.platform_evaluation import PlatformEvaluation
from pfai.self_check import SelfCheck, SelfHeal
from pfai.skills.registry import SkillRegistry
from pfai.interfaces.skills import Skill
from pfai.interfaces.tools import ToolPermission


class TestProviderRegistryAndRouter(unittest.TestCase):
    def test_bootstrap_includes_offline_and_optional(self):
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        ids = {p.provider_id for p in reg.list_providers()}
        self.assertTrue({"echo", "mock", "openai_compatible", "anthropic"} <= ids)
        echo = reg.create("echo")
        self.assertIsInstance(echo, EchoProvider)
        mock_p = reg.create("mock")
        self.assertIsInstance(mock_p, MockCommandProvider)

    def test_create_from_config_falls_back_without_anthropic_key(self):
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            provider = reg.create_from_config({"provider": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"})
        self.assertIsInstance(provider, EchoProvider)

    def test_model_router_from_config_no_vendor_required(self):
        router = ModelRouter.from_config({"provider": "echo"})
        self.assertFalse(router.describe()["anthropic_required"])
        self.assertIn("default", router.available_roles())
        self.assertTrue(router.resolve("coding").generate("x"))


class TestDurableLearning(unittest.TestCase):
    def test_full_gated_pipeline_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            learn_path = str(Path(d) / "learn.sqlite3")
            know_path = str(Path(d) / "know.sqlite3")
            audit_path = str(Path(d) / "audit.jsonl")
            mem = MemoryStore(str(Path(d) / "mem.sqlite3"))
            remembered = []

            def remember(kind, content, source="", confidence=0.8):
                remembered.append(kind)
                return mem.add(kind, content, source=source, confidence=confidence)

            pipe = DurableSafeLearningPipeline(
                learn_path,
                knowledge_store=KnowledgeVersionStore(know_path),
                audit=LearningAuditLog(audit_path),
                memory_remember=remember,
            )
            self.assertFalse(pipe.allows_weight_mutation())
            self.assertFalse(pipe.training_readiness()["weight_training_allowed_now"])

            c = pipe.ingest(LearningSource.CORRECTION, "prefer local models when available")
            pipe.evaluate(c.candidate_id)
            rejected = pipe.validate(c.candidate_id, approved=False)
            self.assertEqual(str(rejected.status), LearningStatus.REJECTED.value)

            c2 = pipe.ingest(LearningSource.VERIFIED_KNOWLEDGE, "successful workflow: run health then metrics")
            pipe.evaluate(c2.candidate_id)
            with self.assertRaises(RuntimeError):
                pipe.store(c2.candidate_id)
            ok = pipe.validate(c2.candidate_id, approved=True)
            self.assertEqual(str(ok.status), LearningStatus.VALIDATED.value)
            stored = pipe.store(c2.candidate_id)
            self.assertEqual(str(stored.status), LearningStatus.STORED.value)
            self.assertTrue(remembered)
            kid = stored.meta["knowledge_id"]
            hist = pipe.knowledge.history(kid)
            self.assertGreaterEqual(len(hist), 1)

            # second version then rollback
            c3 = pipe.ingest(LearningSource.FEEDBACK, "bad lesson that should be rolled back!!")
            c3 = pipe.evaluate(c3.candidate_id)
            c3.meta["knowledge_id"] = kid
            pipe._save(c3)
            pipe.validate(c3.candidate_id, approved=True)
            pipe.store(c3.candidate_id)
            self.assertGreaterEqual(len(pipe.knowledge.history(kid)), 2)
            rolled = pipe.rollback(c3.candidate_id)
            self.assertEqual(str(rolled.status), LearningStatus.ROLLED_BACK.value)
            self.assertTrue(pipe.audit.recent(10))


class TestLTMAndOrchestrator(unittest.TestCase):
    def test_ltm_store_query(self):
        with tempfile.TemporaryDirectory() as d:
            store = MemoryStore(str(Path(d) / "m.sqlite3"))
            ltm = LongTermMemory(store)
            rec = ltm.store(
                MemoryRecord(
                    record_id="",
                    kind=MemoryKind.VERIFIED_KNOWLEDGE,
                    content="portable fact",
                    source="test",
                    confidence=0.9,
                )
            )
            self.assertTrue(rec.record_id)
            hits = ltm.query(query="portable", limit=5)
            self.assertTrue(any("portable" in h.content for h in hits))

    def test_orchestrator_modes(self):
        with tempfile.TemporaryDirectory() as d:
            checks = SelfCheck({"ok": lambda: {"ok": True}})
            heal = SelfHeal(checks)
            evals = PlatformEvaluation()
            skills = SkillRegistry()
            skills.register(Skill(name="ping", description="p", permission=ToolPermission.READ), lambda **k: {"pong": True})
            learn = DurableSafeLearningPipeline(str(Path(d) / "l.sqlite3"))
            store = MemoryStore(str(Path(d) / "m.sqlite3"))
            ltm = LongTermMemory(store)
            orch = Orchestrator(
                model_router=ModelRouter.from_config({"provider": "echo"}),
                skills=skills,
                ltm=ltm,
                learning=learn,
                evaluation=evals,
                self_check=checks,
                self_heal=heal,
                knowledge_search=lambda q, limit=5: [{"content": q, "source": "t"}],
            )
            st = orch.status()
            self.assertFalse(st["anthropic_required"])
            self.assertFalse(st["allows_weight_mutation"])

            r = orch.handle(OrchestratorRequest(goal="x", mode="self_check"))
            self.assertTrue(r.ok)
            r = orch.handle(OrchestratorRequest(goal="suite", mode="evaluate", context={"suite": "smoke"}))
            self.assertTrue(r.ok)
            r = orch.handle(OrchestratorRequest(goal="lesson about local first design", mode="learn", context={"action": "ingest"}))
            self.assertTrue(r.ok)
            cid = r.meta["candidate_id"]
            orch.handle(OrchestratorRequest(goal="x", mode="learn", context={"action": "evaluate", "candidate_id": cid}))
            blocked = orch.handle(
                OrchestratorRequest(
                    goal="x",
                    mode="learn",
                    context={"action": "validate", "candidate_id": cid, "approved": False},
                )
            )
            self.assertTrue(blocked.needs_approval)
            r = orch.handle(OrchestratorRequest(goal="ping", mode="skill", context={"skill": "ping"}))
            self.assertTrue(r.ok)
            r = orch.handle(OrchestratorRequest(goal="portable", mode="memory", context={"action": "store", "kind": "semantic"}))
            self.assertTrue(r.ok)
            r = orch.handle(OrchestratorRequest(goal="q", mode="knowledge"))
            self.assertTrue(r.ok)


class TestApiPlatformSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}

    def test_health_includes_platform(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertIn("platform", body)
        self.assertFalse(body["platform"]["anthropic_required"])

    def test_dashboard_still_serves(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("AI Command Chat", r.text)
        self.assertIn("Coding Academy", r.text)

    def test_orchestrate_and_providers(self):
        r = self.client.get("/platform/providers", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["anthropic_required"])
        self.assertIn("echo", {p["provider_id"] for p in r.json()["providers"]})

        r = self.client.post(
            "/orchestrate",
            headers=self.headers,
            json={"goal": "run diagnostics", "mode": "self_check"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        r = self.client.post(
            "/platform/learning",
            headers=self.headers,
            json={"content": "feedback: keep providers swappable", "action": "ingest", "source": "feedback"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_chat_route_unchanged(self):
        r = self.client.post(
            "/chat/message",
            headers=self.headers,
            json={"message": "فحص الصحة"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("reply", r.json())


if __name__ == "__main__":
    unittest.main()
