import tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pfai.embeddings import HashEmbeddingProvider
from pfai.vector_store import VectorStore
from pfai.rag import RAGEngine
from pfai.model import EchoProvider
class T(unittest.TestCase):
 def test_vectors(self):
  with tempfile.TemporaryDirectory() as d:
   s=VectorStore(Path(d)/'v.db',HashEmbeddingProvider()); s.add('Gold price and dollar relationship','src'); s.add('Python programming language','code'); r=s.search('gold dollar',1); self.assertEqual(r[0]['source'],'src')
 def test_rag(self):
  with tempfile.TemporaryDirectory() as d:
   s=VectorStore(Path(d)/'v.db',HashEmbeddingProvider()); s.add('PFAI is a private AI system.','doc'); x=RAGEngine(EchoProvider(),s); out=x.answer('What is PFAI?'); self.assertIn('PFAI',out['answer']); self.assertEqual(len(out['hits']),1)
if __name__=='__main__': unittest.main()
