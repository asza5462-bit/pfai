import unittest, tempfile, os
from pfai.vector_store import VectorStore
from pfai.embeddings import SimpleEmbedding
from pfai.research import ResearchEngine
from pfai.rag import RAG
class M:
    def generate(self,p): return 'TEST ANSWER'
class T(unittest.TestCase):
    def test_research_rag(self):
        with tempfile.TemporaryDirectory() as d:
            s=VectorStore(os.path.join(d,'v.json'),SimpleEmbedding())
            s.add('Gold is a precious metal.','manual',{'title':'Gold'})
            r=ResearchEngine(s)
            out=r.research('gold metal')
            self.assertGreaterEqual(out['count'],1)
            ans=RAG(M(),s,r).answer('gold metal')
            self.assertEqual(ans['answer'],'TEST ANSWER')
            self.assertTrue(ans['sources'])
if __name__=='__main__': unittest.main()
