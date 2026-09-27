"""PHASE 1 longevity foundation — contracts, scaffolds, no API wiring."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pfai.interfaces import (
    CompatibilityLayerProtocol,
    ConfigVersion,
    EmbeddingPort,
    ExportPort,
    HealStep,
    KnowledgeVersion,
    LearningPipelineProtocol,
    LearningSource,
    LearningStage,
    LearningStatus,
    MemoryKind,
    MemoryRecord,
    Migration,
    PFAI_SCHEMA_VERSION,
    ProviderRegistryProtocol,
    Provenance,
    SkillVersion,
    VersionCompareReport,
    VersionStatus,
)
from pfai.longevity import (
    CompatibilityLayer,
    ExportBundleScaffold,
    InMemoryVersionedStore,
    MigrationRunner,
    ProviderRegistry,
    SafeLearningPipeline,
)
from pfai.model import EchoProvider


class TestLongevityContracts(unittest.TestCase):
    def test_memory_kinds_cover_requirements(self):
        needed = {
            "episodic",
            "semantic",
            "procedural",
            "user_preference",
            "project_knowledge",
            "learned_lesson",
            "verified_knowledge",
            "interaction_history",
        }
        self.assertEqual({k.value for k in MemoryKind}, needed)

    def test_memory_record_is_model_agnostic(self):
        rec = MemoryRecord(
            record_id="m1",
            kind=MemoryKind.VERIFIED_KNOWLEDGE,
            content="prefer local models when available",
            source="owner",
            confidence=0.9,
            provenance={"method": "manual"},
        )
        self.assertEqual(rec.version, 1)
        self.assertEqual(rec.status, "active")
        self.assertNotIn("anthropic", rec.content.lower())

    def test_learning_stages_and_no_weight_mutation(self):
        self.assertEqual(
            [s.value for s in LearningStage],
            ["ingest", "evaluate", "validate", "store", "improve"],
        )
        pipe = SafeLearningPipeline()
        self.assertIsInstance(pipe, LearningPipelineProtocol)
        self.assertFalse(pipe.allows_weight_mutation())

    def test_safe_learning_pipeline_gate(self):
        pipe = SafeLearningPipeline()
        c = pipe.ingest(LearningSource.CORRECTION, "use Echo offline", meta={"t": 1})
        self.assertEqual(c.status, LearningStatus.PROPOSED)
        c = pipe.evaluate(c.candidate_id)
        self.assertEqual(c.status, LearningStatus.EVALUATED)
        rejected = pipe.validate(c.candidate_id, approved=False)
        self.assertEqual(rejected.status, LearningStatus.REJECTED)
        c2 = pipe.ingest(LearningSource.FEEDBACK, "successful workflow documented here")
        pipe.evaluate(c2.candidate_id)
        ok = pipe.validate(c2.candidate_id, approved=True)
        self.assertEqual(ok.status, LearningStatus.VALIDATED)
        stored = pipe.store(c2.candidate_id)
        self.assertEqual(stored.status, LearningStatus.STORED)
        rolled = pipe.rollback(c2.candidate_id)
        self.assertEqual(rolled.status, LearningStatus.ROLLED_BACK)

    def test_knowledge_version_metadata(self):
        kv = KnowledgeVersion(
            knowledge_id="k1",
            version=1,
            content="fact",
            timestamp="2026-09-27T00:00:00Z",
            source="lesson",
            confidence=0.8,
            status=VersionStatus.ACTIVE,
            provenance=Provenance(source="learning", actor="owner"),
        )
        self.assertEqual(kv.provenance.actor, "owner")

    def test_schema_version_and_migration_dry_run(self):
        self.assertEqual(PFAI_SCHEMA_VERSION, 5)
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "schema_version.json"
            runner = MigrationRunner(current=1, state_path=str(state))
            runner.register(Migration(version=2, name="example_future", description="not applied yet"))
            # target beyond current schema constant still plans registered steps up to target
            plan = runner.plan(target=2)
            self.assertEqual(len(plan), 1)
            report = runner.run(target=2, dry_run=True)
            self.assertTrue(report.ok)
            self.assertTrue(report.dry_run)
            self.assertEqual(runner.current_version(), 1)

    def test_versioned_store_rollback(self):
        store = InMemoryVersionedStore()
        store.put_version("knowledge", "alpha", {"text": "v1"})
        store.put_version("knowledge", "alpha", {"text": "v2-bad"})
        active = store.get_active("knowledge", "alpha")
        self.assertEqual(active["payload"]["text"], "v2-bad")
        restored = store.rollback("knowledge", "alpha", 1)
        self.assertEqual(restored["payload"]["text"], "v1")
        self.assertEqual(store.get_active("knowledge", "alpha")["payload"]["text"], "v1")

    def test_provider_registry_offline_defaults(self):
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        self.assertIsInstance(reg, ProviderRegistryProtocol)
        ids = {p.provider_id for p in reg.list_providers()}
        self.assertIn("echo", ids)
        self.assertIn("mock", ids)
        echo = reg.create("echo")
        self.assertIsInstance(echo, EchoProvider)
        anthropic = reg.get("anthropic")
        # Optional adapter may be registered, but must never be required for Core.
        if anthropic is not None:
            self.assertTrue(anthropic.requires_api_key)
            self.assertFalse(anthropic.offline_capable)
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            readiness = reg.create_from_config({"provider": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"})
        self.assertIsInstance(readiness, EchoProvider)

    def test_export_bundle_roundtrip_dry_run(self):
        exp = ExportBundleScaffold()
        self.assertIsInstance(exp, ExportPort)
        with tempfile.TemporaryDirectory() as d:
            man = exp.export_bundle(d)
            self.assertEqual(man["format"], "pfai-export-v1")
            self.assertTrue((Path(d) / "pfai_export_manifest.json").exists())
            result = exp.import_bundle(d, dry_run=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])

    def test_compat_layer(self):
        layer = CompatibilityLayer()
        self.assertIsInstance(layer, CompatibilityLayerProtocol)
        report = layer.check()
        self.assertTrue(report.python_ok)
        self.assertEqual(layer.schema_version(), 5)
        self.assertIn("echo", layer.supported_provider_kinds())
        self.assertIn("sqlite", layer.supported_storage_kinds())

    def test_heal_steps_and_eval_compare_shapes(self):
        self.assertEqual(
            [s.value for s in HealStep],
            ["detect", "diagnose", "propose", "apply_safe", "test", "rollback"],
        )
        cmp = VersionCompareReport(
            baseline_id="b",
            candidate_id="c",
            baseline_score=0.9,
            candidate_score=0.7,
            regressions=["suite.x"],
            ok_to_promote=False,
        )
        self.assertTrue(cmp.requires_owner)
        self.assertFalse(cmp.ok_to_promote)

    def test_config_skill_version_shapes(self):
        cfg = ConfigVersion(config_id="default", version=1, payload={"a": 1}, timestamp="t")
        sk = SkillVersion(skill_name="ping", version="1.0.0", status=VersionStatus.ACTIVE)
        self.assertEqual(cfg.status, VersionStatus.DRAFT)
        self.assertEqual(sk.skill_name, "ping")

    def test_embedding_port_structural(self):
        from pfai.embeddings import HashEmbeddingProvider

        emb = HashEmbeddingProvider(32)
        self.assertIsInstance(emb, EmbeddingPort)
        vec = emb.embed("hello")
        self.assertEqual(len(vec), 32)

    def test_existing_api_surface_intact(self):
        from pfai.api import app

        paths = {getattr(r, "path", None) for r in app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/chat/message", paths)
        self.assertIn("/", paths)
        self.assertTrue(any(isinstance(p, str) and p.startswith("/coding/") for p in paths))


if __name__ == "__main__":
    unittest.main()
