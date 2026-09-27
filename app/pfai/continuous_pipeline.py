from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional, Sequence
import json, time

from .data_factory import Example
from .training_factory import TrainingFactory
from .sft import SFTLoRATrainer
from .evaluation_lab import EvaluationLab
from .model_registry import ModelRegistry
from .deployment import DeploymentController
from .learning_curriculum import LearningCurriculum
from .data_acquisition import DataAcquisitionEngine

@dataclass
class PipelineConfig:
    dataset_id: str = "continuous"
    dataset_version_prefix: str = "auto"
    model_id: str = "local-model"
    dry_run: bool = True
    require_gpu: bool = False
    auto_promote: bool = False
    canary_traffic: float = 0.1
    minimum_score: float = 0.0
    require_improvement: bool = True

class ContinuousTrainingPipeline:
    """One bounded training cycle: data -> dataset -> train/resume -> eval -> registry -> optional canary/promotion."""
    def __init__(self, root="data/continuous_pipeline", config: Optional[PipelineConfig]=None,
                 data_factory=None, trainer=None, evaluator=None, registry=None, deployment=None):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.config=config or PipelineConfig()
        self.training_factory=TrainingFactory(data_factory=data_factory, workdir=self.root/"runs")
        self.curriculum=LearningCurriculum()
        self.acquisition=DataAcquisitionEngine(self.curriculum)
        self.trainer=trainer or SFTLoRATrainer(output_root=self.root/"artifacts/training")
        self.evaluator=evaluator or EvaluationLab(self.config.minimum_score)
        self.registry=registry or ModelRegistry(str(self.root/"model_registry.json"))
        self.deployment=deployment or DeploymentController(str(self.root/"deployments.json"), self.registry)
        self.state_path=self.root/"pipeline_state.json"

    def _save_state(self, payload):
        self.state_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    def run_cycle(self, rows: Sequence[Example], eval_suites: dict[str, Callable[[], float]], baseline_score: Optional[float]=None):
        if not rows: raise ValueError("no training examples supplied")
        curated=self.acquisition.curate([{"instruction":r.instruction,"response":r.response,"source":r.source,"metadata":r.metadata} for r in rows])
        if not curated: raise ValueError("no training examples passed acquisition quality gates")
        rows=[Example(x.instruction,x.response,source=x.source,metadata={**(x.metadata or {}),"learning_track":x.track,"quality":x.quality}) for x in curated]
        cycle_id=f"cycle-{int(time.time()*1000)}"
        version=f"{self.config.dataset_version_prefix}-{int(time.time())}"
        manifest=self.training_factory.prepare(self.config.dataset_id, version, list(rows))
        run=self.training_factory.start_run(self.config.dataset_id, version, backend="sft-lora")
        run_id=run["run_id"]
        prepared=self.trainer.prepare_run(run_id,self.config.model_id,asdict(manifest),{"dry_run":self.config.dry_run,"require_gpu":self.config.require_gpu})
        resume=self.trainer.resume_from(run_id)
        trained=self.trainer.train(run_id,dry_run=self.config.dry_run,require_gpu=self.config.require_gpu)
        evaluation=self.evaluator.evaluate(eval_suites)
        score=float(evaluation["overall"])
        improvement_ok = baseline_score is None or not self.config.require_improvement or score > float(baseline_score)
        accepted=bool(evaluation["passed"] and improvement_ok)
        model_version=f"{self.config.model_id}-{cycle_id}"
        registered=None
        if accepted:
            registered=self.registry.register(model_version,trained["checkpoint"],score,parent=(self.registry.active() or {}).get("version", ""))
            if self.config.auto_promote:
                self.deployment.canary(model_version,self.config.canary_traffic)
                self.deployment.promote(model_version)
        result={"evaluated":True,"accepted":accepted,"cycle_id":cycle_id,"dataset":asdict(manifest),
                "run":run,"training":trained,"resume_checkpoint":resume,"evaluation":evaluation,
                "improvement_ok":improvement_ok,"registered":registered,"auto_promote":self.config.auto_promote}
        self._save_state(result)
        return result
