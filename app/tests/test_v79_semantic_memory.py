import tempfile, unittest
from pathlib import Path

from pfai.memory import MemoryStore
from pfai.vector_store import VectorStore
from pfai.embeddings import HashEmbeddingProvider


class TestSemanticMemory(unittest.TestCase):
    def test_backward_compatible_without_vector_store(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            mem.add("fact", "PFAI uses gated tools", "test", 1.0)
            hits = mem.search("gated")
            self.assertEqual(len(hits), 1)

    def test_semantic_recall_beyond_exact_substring(self):
        with tempfile.TemporaryDirectory() as d:
            vs = VectorStore(str(Path(d) / "v.sqlite3"), HashEmbeddingProvider(64))
            mem = MemoryStore(str(Path(d) / "m.sqlite3"), vector_store=vs)
            mem.add("lesson", "Riyadh is the capital city of Saudi Arabia", "self_reflection", 0.6)
            mem.add("lesson", "Bananas are a good source of potassium", "self_reflection", 0.6)
            # Overlapping vocabulary but not a literal substring of either stored lesson.
            hits = mem.search("capital Saudi Arabia city")
            self.assertTrue(any("Riyadh" in h["content"] for h in hits))

    def test_falls_back_to_like_search_when_index_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            vs = VectorStore(str(Path(d) / "v.sqlite3"), HashEmbeddingProvider(64))
            mem = MemoryStore(str(Path(d) / "m.sqlite3"), vector_store=vs)
            # Insert directly into sqlite only, bypassing add(), to simulate a stale/empty index.
            mem.db.execute(
                "INSERT INTO memories(kind,content,source,confidence,created_at) VALUES(?,?,?,?,?)",
                ("fact", "unindexed legacy row", "legacy", 0.5, "2020-01-01T00:00:00+00:00"),
            )
            mem.db.commit()
            hits = mem.search("unindexed")
            self.assertTrue(any(h["content"] == "unindexed legacy row" for h in hits))

    def test_search_never_raises_if_vector_store_is_broken(self):
        class BrokenVectorStore:
            def add(self, *a, **k): raise RuntimeError("boom")
            def search(self, *a, **k): raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"), vector_store=BrokenVectorStore())
            mem.add("fact", "resilient storage test", "test", 1.0)  # add() must not raise either
            hits = mem.search("resilient")
            self.assertEqual(len(hits), 1)

    def test_add_returns_row_id(self):
        with tempfile.TemporaryDirectory() as d:
            mem = MemoryStore(str(Path(d) / "m.sqlite3"))
            row_id = mem.add("fact", "row id check", "test", 1.0)
            self.assertIsInstance(row_id, int)
            self.assertGreater(row_id, 0)


if __name__ == "__main__":
    unittest.main()
