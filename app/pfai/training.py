from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import json, os, hashlib

@dataclass
class TrainingRun:
    run_id: str
    base_version: str
    candidate_version: str
    dataset_hash: str
    status: str
    score: float
    artifact: str
    created_at: str
    metrics: Dict[str, Any]
    notes: str = ''

class TrainingBackend:
    """Safe local backend contract. Real GPU backends can implement this interface later."""
    def train(self, dataset: List[Dict[str, Any]], base_artifact: Optional[str], output_dir: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

class DryRunTrainingBackend(TrainingBackend):
    """Produces a reproducible training manifest without pretending to train model weights."""
    def train(self, dataset, base_artifact, output_dir, **kwargs):
        os.makedirs(output_dir, exist_ok=True)
        raw = json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()
        dataset_hash = hashlib.sha256(raw).hexdigest()
        manifest = {
            'type': 'training-manifest', 'dataset_hash': dataset_hash,
            'base_artifact': base_artifact, 'items': len(dataset),
            'backend': 'dry-run', 'hyperparameters': kwargs
        }
        path = os.path.join(output_dir, 'training_manifest.json')
        with open(path, 'w', encoding='utf-8') as f: json.dump(manifest, f, ensure_ascii=False, indent=2)
        return {'artifact': path, 'metrics': {'items': len(dataset), 'trained': False}}

class ModelLifecycle:
    """Orchestrates train -> evaluate -> candidate registration -> promotion/rollback."""
    def __init__(self, registry_path='data/training_runs.json', artifact_dir='data/artifacts', backend=None):
        self.registry_path = registry_path; self.artifact_dir = artifact_dir
        self.backend = backend or DryRunTrainingBackend()
        os.makedirs(os.path.dirname(registry_path) or '.', exist_ok=True); os.makedirs(artifact_dir, exist_ok=True)
        if not os.path.exists(registry_path): self._save([])

    def _load(self):
        with open(self.registry_path, 'r', encoding='utf-8') as f: return json.load(f)
    def _save(self, x):
        with open(self.registry_path, 'w', encoding='utf-8') as f: json.dump(x, f, ensure_ascii=False, indent=2)
    @staticmethod
    def _hash(dataset):
        return hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def train_candidate(self, run_id, base_version, candidate_version, dataset, evaluator: Callable[[str, List[Dict[str,Any]]], float], base_artifact=None, notes='', **kwargs):
        out = os.path.join(self.artifact_dir, candidate_version.replace('/', '_'))
        result = self.backend.train(dataset, base_artifact, out, **kwargs)
        score = float(evaluator(result['artifact'], dataset))
        status = 'evaluated'
        run = TrainingRun(run_id, base_version, candidate_version, self._hash(dataset), status, score, result['artifact'], datetime.now(timezone.utc).isoformat(), result.get('metrics', {}), notes)
        rows = self._load(); rows.append(asdict(run)); self._save(rows)
        return asdict(run)

    def history(self): return self._load()
    def latest(self):
        rows = self._load(); return rows[-1] if rows else None
