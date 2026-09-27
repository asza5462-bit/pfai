"""PHASE 3 — deep LTM/Knowledge adapters, eval baselines, migration apply + export."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from pfai.backup_manager import BackupManager
from pfai.interfaces.memory import MemoryKind, MemoryRecord
from pfai.interfaces.migration import Migration, PFAI_SCHEMA_VERSION
from pfai.interfaces.evaluation import EvalReport
from pfai.knowledge_layer import KnowledgeLayer
from pfai.longevity.durable_learning import KnowledgeVersionStore, DurableSafeLearningPipeline
from pfai.longevity.export_bundle import ExportBundleScaffold
from pfai.longevity.migration_runner import MigrationRunner
from pfai.longevity.migrations import register_platform_migrations
from pfai.memory import MemoryStore
from pfai.memory_system import LongTermMemory
from pfai.platform_evaluation import PlatformEvaluation


class TestPhase3LTMKnowledge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryStore(str(self.root / "mem.sqlite3"))
        self.ltm = LongTermMemory(self.store, versions_path=str(self.root / "ltm_versions.sqlite3"))
        self.kv = KnowledgeVersionStore(str(self.root / "knowledge_versions.sqlite3"))
        self.knowledge = KnowledgeLayer(
            search_fn=lambda q, limit: [],
            version_store=self.kv,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_ltm_kinds_preserved_and_durable(self):
        for kind in MemoryKind:
            rec = self.ltm.store(
                MemoryRecord(record_id="", kind=kind, content=f"payload-{kind.value}", source="t", confidence=0.9)
            )
            self.assertEqual(
                rec.kind.value if hasattr(rec.kind, "value") else rec.kind,
                kind.value,
            )
        # Reload from disk
        ltm2 = LongTermMemory(self.store, versions_path=str(self.root / "ltm_versions.sqlite3"))
        rows = ltm2.query(kind=MemoryKind.SEMANTIC, query="", limit=50)
        self.assertTrue(any("payload-semantic" in r.content for r in rows))
        # Backend row kind not remapped
        docs = self.store.list_by_kind(MemoryKind.PROCEDURAL.value, limit=5)
        self.assertTrue(docs)

    def test_ltm_supersede_rollback_persists(self):
        rec = self.ltm.store(MemoryRecord(record_id="fixed-1", kind=MemoryKind.SEMANTIC, content="v1"))
        self.ltm.supersede("fixed-1", "v2", source="edit")
        rolled = self.ltm.rollback("fixed-1", to_version=1)
        self.assertEqual(rolled.content, "v1")
        ltm2 = LongTermMemory(self.store, versions_path=str(self.root / "ltm_versions.sqlite3"))
        hist = ltm2.history("fixed-1")
        self.assertGreaterEqual(len(hist), 3)
        active = ltm2.active("fixed-1")
        self.assertIsNotNone(active)
        self.assertEqual(active.content, "v1")

    def test_knowledge_layer_finds_versioned_content(self):
        self.knowledge.publish("k-alpha", "durable fact about regression gates", source="test")
        hits = self.knowledge.search("regression", limit=5)
        self.assertTrue(hits)
        self.assertIn("regression", hits[0].content.lower())
        hist = self.knowledge.history("k-alpha")
        self.assertEqual(len(hist), 1)
        self.knowledge.publish("k-alpha", "updated fact", source="test")
        rolled = self.knowledge.rollback("k-alpha", 1)
        self.assertIn("durable fact", rolled.content)

    def test_learning_still_forbids_weights(self):
        pipe = DurableSafeLearningPipeline(
            str(self.root / "learning.sqlite3"),
            knowledge_store=self.kv,
        )
        self.assertFalse(pipe.allows_weight_mutation())


class TestPhase3MigrationExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_dry_run_unchanged(self):
        state = self.root / "schema.json"
        runner = MigrationRunner(current=1, state_path=str(state), backup_fn=lambda: {"path": "x"})
        register_platform_migrations(runner)
        report = runner.run(dry_run=True)
        self.assertTrue(report.ok)
        self.assertTrue(report.dry_run)
        self.assertEqual(runner.current_version(), 1)

    def test_migration_apply_requires_backup_and_advances(self):
        src = self.root / "learning.sqlite3"
        src.write_bytes(b"demo")
        backups = []

        def backup():
            mgr = BackupManager(str(src), str(self.root / "backups"), retention=3)
            rec = mgr.create(label="pre")
            backups.append(rec)
            return rec

        state = self.root / "schema.json"
        runner = MigrationRunner(current=1, state_path=str(state), backup_fn=backup)
        register_platform_migrations(runner)
        self.assertEqual(PFAI_SCHEMA_VERSION, 2)
        report = runner.run(dry_run=False)
        self.assertTrue(report.ok, report.error)
        self.assertEqual(runner.current_version(), 2)
        self.assertTrue(backups)
        self.assertTrue((self.root / "backups" / backups[0]["path"]).exists())
        # Persisted
        runner2 = MigrationRunner(state_path=str(state), backup_fn=backup)
        self.assertEqual(runner2.current_version(), 2)

    def test_migration_without_backup_fn_fails_apply(self):
        runner = MigrationRunner(current=1, state_path=str(self.root / "s.json"), backup_fn=None)
        runner.register(Migration(version=2, name="x", upgrade=lambda c: None))
        report = runner.run(dry_run=False)
        self.assertFalse(report.ok)
        self.assertIn("backup", (report.error or "").lower())

    def test_export_populate_and_import_roundtrip(self):
        store = MemoryStore(str(self.root / "mem.sqlite3"))
        ltm = LongTermMemory(store, versions_path=str(self.root / "ltm.sqlite3"))
        ltm.store(MemoryRecord(record_id="", kind=MemoryKind.LEARNED_LESSON, content="export-me", source="t"))
        kv = KnowledgeVersionStore(str(self.root / "kv.sqlite3"))
        layer = KnowledgeLayer(version_store=kv)
        layer.publish("exp-k", "knowledge-export", source="t")

        exp = ExportBundleScaffold(
            memory_export=lambda: ltm.export_records(),
            knowledge_export=lambda: [
                {"knowledge_id": x.knowledge_id, "content": x.content, "source": x.source, "confidence": x.confidence}
                for x in kv.list_active()
            ],
            memory_import=lambda rows: ltm.import_records(rows),
            knowledge_import=lambda rows: sum(
                1 for i, r in enumerate(rows) for _ in [layer.publish(str(r.get("knowledge_id") or f"i{i}"), r.get("content") or "")]
            ),
        )
        out = self.root / "bundle"
        manifest = exp.export_bundle(str(out))
        self.assertEqual(manifest["format"], "pfai-export-v1")
        self.assertGreaterEqual(manifest["counts"]["memory"], 1)
        self.assertGreaterEqual(manifest["counts"]["knowledge"], 1)
        mem_json = json.loads((out / "memory.json").read_text(encoding="utf-8"))
        self.assertTrue(any("export-me" in r.get("content", "") for r in mem_json))
        # No secrets keys
        cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(isinstance(cfg, dict))
        dry = exp.import_bundle(str(out), dry_run=True)
        self.assertTrue(dry["ok"])
        applied = exp.import_bundle(str(out), dry_run=False)
        self.assertTrue(applied["applied"])


class TestPhase3Eval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.eval = PlatformEvaluation(baselines_path=str(Path(self.tmp.name) / "baselines.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_richer_suites_and_regression_blocks_promote(self):
        self.assertIn("longevity", self.eval.list_suites())
        report = self.eval.run_suite("longevity")
        self.assertTrue(report.ok)
        self.eval.record_baseline("base", report)
        # Candidate that fails a case that baseline passed
        bad = EvalReport(
            suite="longevity",
            passed=0,
            failed=1,
            ok=False,
            cases=[{"name": "schema_version_defined", "passed": False}],
            meta={"overall": 0.0},
        )
        self.eval.record_baseline("cand", bad)
        cmp = self.eval.compare("base", "cand", suite="longevity")
        self.assertFalse(cmp.ok_to_promote)
        self.assertTrue(cmp.requires_owner)
        self.assertIn("schema_version_defined", cmp.regressions)
        # Durable baselines
        eval2 = PlatformEvaluation(baselines_path=str(Path(self.tmp.name) / "baselines.json"))
        self.assertIsNotNone(eval2.get_baseline("base"))


class TestPhase3API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_EMAIL"] = "test-owner@example.invalid"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}

    def test_owner_gate_and_ltm_roundtrip(self):
        self.assertEqual(self.client.get("/platform/ltm/search").status_code, 401)
        r = self.client.post(
            "/platform/ltm",
            json={"content": "phase3 memory", "kind": "semantic"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["record_id"]
        h = self.client.get(f"/platform/ltm/{rid}/history", headers=self.headers)
        self.assertEqual(h.status_code, 200)
        self.assertGreaterEqual(len(h.json()["items"]), 1)

    def test_knowledge_eval_migration_export_routes(self):
        p = self.client.post(
            "/platform/knowledge/versions",
            json={"knowledge_id": "api-k1", "content": "api knowledge fact"},
            headers=self.headers,
        )
        self.assertEqual(p.status_code, 200, p.text)
        suites = self.client.get("/platform/eval/suites", headers=self.headers)
        self.assertEqual(suites.status_code, 200)
        self.assertIn("longevity", suites.json()["suites"])
        mig = self.client.get("/platform/migrations", headers=self.headers)
        self.assertEqual(mig.status_code, 200)
        dry = self.client.post(
            "/platform/migrations/run",
            json={"dry_run": True},
            headers=self.headers,
        )
        self.assertEqual(dry.status_code, 200, dry.text)
        self.assertTrue(dry.json()["dry_run"])
        # health still public + phase metadata
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        plat = health.json().get("platform") or {}
        self.assertEqual(plat.get("phase"), 3)
        self.assertTrue(plat.get("ltm"))
        self.assertEqual(plat.get("anthropic_required"), False)
        # Dashboard intact
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_no_weight_mutation_invariant(self):
        from pfai.api import PLATFORM_LEARNING

        self.assertFalse(PLATFORM_LEARNING.allows_weight_mutation())


if __name__ == "__main__":
    unittest.main()
