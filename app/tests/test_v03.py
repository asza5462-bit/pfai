import tempfile, unittest
from pathlib import Path
from pfai.memory import MemoryStore
from pfai.ingest import TextIngestor
from pfai.retrieval import BM25Retriever
from pfai.model import EchoProvider
from pfai.rag import RAGEngine
from pfai.benchmark import Benchmark
class T(unittest.TestCase):
 def test_ingest_retrieve(self):
  with tempfile.TemporaryDirectory() as d:
   m=MemoryStore(str(Path(d)/'m.db')); TextIngestor(m).ingest_text('Gold liquidity sweep above resistance and market structure shift.','test')
   h=BM25Retriever(m).search('liquidity resistance'); self.assertTrue(h); self.assertGreater(h[0]['score'],0)
 def test_rag(self):
  with tempfile.TemporaryDirectory() as d:
   m=MemoryStore(str(Path(d)/'m.db')); TextIngestor(m).ingest_text('PFAI uses gated tools.','test')
   r=RAGEngine(EchoProvider(),BM25Retriever(m)).answer('What does PFAI use?'); self.assertIn('PFAI uses gated tools',r['answer']); self.assertEqual(r['sources'],['test'])
 def test_benchmark(self):
  x=Benchmark(EchoProvider()).run([{'id':'a','prompt':'hello world','must_contain':['hello world']}]); self.assertEqual(x['score'],1)
if __name__=='__main__': unittest.main()
