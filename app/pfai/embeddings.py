from abc import ABC, abstractmethod
import hashlib, math, re

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text): ...

class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions=256): self.dimensions=dimensions
    def embed(self,text):
        v=[0.0]*self.dimensions
        for tok in re.findall(r"\w+", text.lower()):
            h=int(hashlib.sha256(tok.encode()).hexdigest(),16)
            v[h%self.dimensions]+=1.0
        n=math.sqrt(sum(x*x for x in v)) or 1.0
        return [x/n for x in v]

class SentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_name):
        from sentence_transformers import SentenceTransformer
        self.model=SentenceTransformer(model_name)
    def embed(self,text):
        return self.model.encode(text, normalize_embeddings=True).tolist()


SimpleEmbedding = HashEmbeddingProvider
