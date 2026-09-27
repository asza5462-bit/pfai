import time
from .app import build_app
from .audit import AuditLog
from .metrics import Metrics
from .model_registry import ModelRegistry
from .deployment import DeploymentController
from . import __version__

class PFAIRuntime:
    def __init__(self, config_path='configs/default.json'):
        self.agent,self.memory,self.tools,self.store,self.reasoner=build_app(config_path)
        self.model=self.agent.model
        self.config_path=config_path
        self.audit=AuditLog('data/audit.log'); self.metrics=Metrics('data/metrics.json')
        self.registry=ModelRegistry('data/model_registry.json'); self.deploy=DeploymentController('data/deployments.json',self.registry)
    def ask(self,question):
        t=time.perf_counter(); self.metrics.inc('requests_total')
        try:
            result=self.agent.answer(question); self.metrics.inc('requests_success'); return result
        except Exception:
            self.metrics.inc('requests_error'); raise
        finally: self.metrics.observe('request', (time.perf_counter()-t)*1000)
    def health(self, extra: dict | None = None):
        active = self.registry.active()
        payload = {
            'status':'ok',
            'runtime':'PFAI',
            'version': __version__,
            'model': active,
            'metrics_available': True,
            'model_provider': getattr(self.model, 'model', None) or type(self.model).__name__,
        }
        if extra:
            payload.update(extra)
        return payload
