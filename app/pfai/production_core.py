from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, time

from .gpu_orchestrator import GPUOrchestrator
from .continuous_pipeline import ContinuousTrainingPipeline, PipelineConfig

@dataclass
class ProductionConfig:
    root: str = 'data/production'
    cycle_interval_seconds: int = 300
    code_ai_priority: int = 100
    auto_promote: bool = False
    dry_run: bool = True

class ProductionCore:
    """Unified stateful control plane for PFAI's continuous lifecycle.

    It coordinates scheduling and pipeline execution without inventing hardware,
    model quality, or training success. Execution remains delegated to workers.
    """
    def __init__(self, config: ProductionConfig | None = None):
        self.config = config or ProductionConfig()
        self.root = Path(self.config.root); self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / 'state.json'
        self.orchestrator = GPUOrchestrator(str(self.root / 'orchestrator.json'))
        self.pipeline = ContinuousTrainingPipeline(
            root=self.root / 'pipeline',
            config=PipelineConfig(dry_run=self.config.dry_run, auto_promote=self.config.auto_promote),
        )
        self._state = self._load()

    def _load(self):
        if not self.state_path.exists():
            return {'status':'idle','cycles':0,'last_cycle':None,'last_error':None,'updated_at':time.time()}
        return json.loads(self.state_path.read_text(encoding='utf-8'))

    def _save(self):
        self._state['updated_at'] = time.time()
        self.state_path.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding='utf-8')

    def submit_learning_job(self, kind='code_ai_training', priority=None, gpu_required=0, memory_gb=0.0, payload=None):
        p = self.config.code_ai_priority if priority is None else priority
        return self.orchestrator.submit(kind, priority=p, gpu_required=gpu_required, memory_gb=memory_gb, payload=payload or {})

    def tick(self):
        """One scheduler tick. Workers execute dispatched jobs externally."""
        started = self.orchestrator.dispatch()
        self._state['status'] = 'running' if started else 'idle'
        self._state['last_dispatch'] = started
        self._save()
        return {'started': started, 'status': self.status()}

    def record_cycle(self, result):
        self._state['cycles'] = int(self._state.get('cycles', 0)) + 1
        self._state['last_cycle'] = result
        self._state['last_error'] = None
        self._state['status'] = 'idle'
        self._save()

    def record_error(self, error):
        self._state['last_error'] = str(error)
        self._state['status'] = 'degraded'
        self._save()

    def recover(self):
        recovered = self.orchestrator.recover()
        self._state['status'] = 'recovered'
        self._save()
        return recovered

    def status(self):
        return {
            'runtime': 'PFAI Production Core',
            'state': self._state,
            'scheduler': self.orchestrator.status(),
            'pipeline': {
                'root': str(self.pipeline.root),
                'dry_run': self.pipeline.config.dry_run,
                'auto_promote': self.pipeline.config.auto_promote,
            },
        }

    def run_forever(self, stop_check=None, sleep_fn=time.sleep):
        """Long-running loop. stop_check is injectable for services/tests."""
        while True:
            if stop_check and stop_check():
                self._state['status'] = 'stopped'; self._save(); return
            try:
                self.tick()
            except Exception as exc:
                self.record_error(exc)
            sleep_fn(max(1, int(self.config.cycle_interval_seconds)))
