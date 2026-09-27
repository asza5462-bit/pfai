import tempfile, os, unittest
from pfai.vector_memory import SemanticMemory
class TestV04(unittest.TestCase):
 def test_semantic_retrieval(self):
  p=tempfile.mktemp(); m=SemanticMemory(p); m.add('Gold prices react to real yields','macro'); m.add('Cooking recipes use ingredients','food'); r=m.search('gold yields',1); self.assertEqual(r[0]['source'],'macro'); os.remove(p)
if __name__=='__main__': unittest.main()
