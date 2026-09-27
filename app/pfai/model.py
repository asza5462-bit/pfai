from abc import ABC, abstractmethod
class ModelProvider(ABC):
    @abstractmethod
    def generate(self,prompt,**kwargs): ...
class EchoProvider(ModelProvider):
    """Deterministic placeholder used for integration tests; replace with a real model adapter."""
    def generate(self,prompt,**kwargs): return f"[PFAI-ECHO] {prompt}"
