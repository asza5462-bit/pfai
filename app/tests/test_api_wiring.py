import hashlib
import os
import unittest
from fastapi.testclient import TestClient

class TestAPIWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['PFAI_OWNER_USERNAME']='testowner'
        os.environ['PFAI_OWNER_SECRET_HASH']=hashlib.sha256(b'test-secret').hexdigest()
        from pfai.api import app, runtime
        from pfai.model import EchoProvider
        runtime.model=EchoProvider(); runtime.agent.model=runtime.model; runtime.agent.rag.model=runtime.model
        cls.client=TestClient(app)
    @classmethod
    def tearDownClass(cls):
        os.environ.pop('PFAI_OWNER_USERNAME',None); os.environ.pop('PFAI_OWNER_SECRET_HASH',None)
    def test_health_is_public(self): self.assertEqual(self.client.get('/health').status_code,200)
    def test_model_routes_require_owner(self):
        self.assertEqual(self.client.post('/ask',json={'question':'hello'}).status_code,401)
        self.assertEqual(self.client.post('/code/evaluate',json={'code':'print(1)'}).status_code,401)
    def test_authenticated_ask_uses_correct_rag_wiring(self):
        r=self.client.post('/ask',json={'question':'hello'},headers={'X-Owner-Secret':'test-secret'})
        self.assertEqual(r.status_code,200); self.assertIn('answer',r.json())
    def test_authenticated_code_evaluation_works(self):
        r=self.client.post('/code/evaluate',json={'code':'def add(a,b): return a+b','test_code':'assert add(1,2)==3'},headers={'X-Owner-Secret':'test-secret'})
        self.assertEqual(r.status_code,200); self.assertTrue(r.json()['passed'])
    def test_owner_identity_is_protected(self):
        self.assertEqual(self.client.get('/owner/identity').status_code,401)
        self.assertEqual(self.client.get('/owner/identity',headers={'X-Owner-Secret':'test-secret'}).status_code,200)

if __name__=='__main__': unittest.main()
