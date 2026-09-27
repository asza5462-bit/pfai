"""Legacy SFT entrypoint — delegates real training to RealLoRATrainingBackend."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import time


@dataclass
class TrainingCapability:
    torch: bool
    transformers: bool
    peft: bool
    trl: bool
    datasets: bool
    cuda: bool


class SFTLoRATrainer:
    def __init__(self, output_root="artifacts/training"):
        self.output_root = Path(output_root)

    def capabilities(self):
        def has(name):
            try:
                __import__(name)
                return True
            except Exception:
                return False

        cuda = False
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
        except Exception:
            pass
        return TrainingCapability(
            has("torch"),
            has("transformers"),
            has("peft"),
            has("trl"),
            has("datasets"),
            cuda,
        )

    def preflight(self, require_gpu=False):
        c = self.capabilities()
        d = asdict(c)
        missing = [k for k in ("torch", "transformers", "peft", "datasets") if not d[k]]
        if require_gpu and not c.cuda:
            missing.append("cuda")
        return {"ready": not missing, "missing": missing, "capabilities": d}

    def prepare_run(self, run_id, model_id, dataset_manifest, config=None):
        p = self.output_root / run_id
        p.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "model_id": model_id,
            "dataset_manifest": dataset_manifest,
            "config": config or {},
            "created_at": time.time(),
            "trainer": "SFTLoRA",
        }
        (p / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def resume_from(self, run_id):
        p = self.output_root / run_id
        cps = sorted(p.glob("checkpoint-*")) if p.exists() else []
        return str(cps[-1]) if cps else None

    def train(self, run_id, dry_run=True, require_gpu=False, model_id=None, rows=None, config=None):
        check = self.preflight(require_gpu)
        if dry_run:
            p = self.output_root / run_id
            p.mkdir(parents=True, exist_ok=True)
            cp = p / "checkpoint-0000"
            cp.mkdir(exist_ok=True)
            (cp / "trainer_state.json").write_text(
                json.dumps({"run_id": run_id, "dry_run": True, "capabilities": check["capabilities"]}, indent=2),
                encoding="utf-8",
            )
            return {"status": "dry_run", "checkpoint": str(cp), "preflight": check}
        if not check["ready"]:
            return {"status": "blocked", "reason": "real training backend unavailable", "preflight": check}
        if not model_id or not rows:
            return {"status": "blocked", "reason": "model_id and non-empty rows are required", "preflight": check}

        from pfai.longevity.autonomous_training.trainer import RealLoRATrainingBackend
        from pfai.longevity.autonomous_training.types import TrainingConfig

        cfg = TrainingConfig(
            method="lora",
            base_model=model_id,
            epochs=float((config or {}).get("epochs", 1)),
            learning_rate=float((config or {}).get("learning_rate", 2e-5)),
            batch_size=int((config or {}).get("batch_size", 1)),
            require_gpu=bool(require_gpu),
            extra={k: v for k, v in (config or {}).items() if k not in ("epochs", "learning_rate", "batch_size")},
        )
        out = RealLoRATrainingBackend().train(
            job_id=run_id,
            dataset_rows=list(rows),
            output_dir=str(self.output_root / run_id),
            config=cfg,
        )
        if out.ok:
            return {
                "status": "completed",
                "checkpoint": out.checkpoint_path,
                "train_loss": (out.metrics or {}).get("train_loss"),
                "preflight": check,
                "real_training": out.real_training,
                "real_weight_update": out.real_weight_update,
            }
        return {
            "status": "failed" if out.status == "FAILED" else "blocked",
            "reason": out.error or out.status,
            "preflight": check,
            "real_training": out.real_training,
        }
