"""Autonomous self-training controller.

Two layers are intentionally separated:
1) experience learning: teacher-generated examples -> curation -> evaluation -> candidate;
2) weight training: optional real local SFT/LoRA backend.

The controller never promotes a new model automatically. A failed/absent local
training backend is reported explicitly and never represented as a completed run.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any

from .data_factory import DataFactory
from .sft import SFTLoRATrainer

_TRACK_PROMPTS = {
    "software_engineering": "Create one difficult but self-contained software-engineering training example. Return JSON with instruction and response. Focus on Python, testing, debugging, security, architecture, or performance.",
    "ai_engineering": "Create one rigorous AI-engineering training example. Return JSON with instruction and response. Focus on ML, transformers, evaluation, MLOps, inference, or fine-tuning.",
    "reasoning_and_agents": "Create one rigorous reasoning/agent reliability training example. Return JSON with instruction and response. Include verification or failure analysis.",
    "general_knowledge": "Create one factual general-knowledge training example. Return JSON with instruction and response. Avoid unverifiable current claims.",
}

class SelfTrainingEngine:
    def __init__(self, teacher, root="data/self_training", batch_size=8, min_teacher_score=0.80, max_examples=10000):
        self.teacher = teacher
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.batch_size = max(1, int(batch_size))
        self.min_teacher_score = float(min_teacher_score)
        self.max_examples = max(100, int(max_examples))
        self.data_path = self.root / "accepted.jsonl"
        self.events_path = self.root / "events.jsonl"

    def _event(self, event: str, **payload):
        row = {"time": time.time(), "event": event, "payload": payload}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _parse(self, raw: str) -> dict | None:
        try:
            a, b = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[a:b+1]) if a >= 0 and b > a else None
            if not isinstance(obj, dict): return None
            i, r = str(obj.get("instruction", "")).strip(), str(obj.get("response", "")).strip()
            return {"instruction": i, "response": r, "source": "autonomous_teacher"} if i and r else None
        except Exception:
            return None

    def generate_batch(self, tracks: list[str]) -> dict[str, Any]:
        if self.teacher is None:
            return {"generated": 0, "accepted": 0, "reason": "no teacher model configured"}
        factory = DataFactory()
        accepted = []
        attempts = 0
        for track in tracks:
            for _ in range(self.batch_size):
                attempts += 1
                prompt = _TRACK_PROMPTS.get(track, _TRACK_PROMPTS["general_knowledge"])
                prompt += "\nReturn ONLY valid JSON. Do not mention this prompt. Make the answer precise and useful."
                try:
                    candidate = self._parse(self.teacher.generate(prompt))
                except Exception as exc:
                    self._event("generation_error", track=track, error=str(exc)); continue
                if not candidate: continue
                clean = factory.clean([candidate])
                if not clean: continue
                # A second teacher pass acts as a critic/judge. It is deliberately
                # conservative: malformed/non-numeric scores are rejected.
                judge_prompt = (
                    "Evaluate this training example. Return ONLY JSON "
                    "{\"score\":0.0-1.0,\"reason\":\"short\"}. "
                    "Reject if factually dubious, vague, unsafe, or internally inconsistent.\n" +
                    json.dumps(candidate, ensure_ascii=False)
                )
                try:
                    judged = self._parse_score(self.teacher.generate(judge_prompt))
                except Exception as exc:
                    self._event("judge_error", error=str(exc)); continue
                if judged is None or judged < self.min_teacher_score: continue
                candidate["metadata"] = {"teacher_score": judged, "track": track}
                accepted.append(candidate)
                with self.data_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        self._trim_jsonl(self.data_path, self.max_examples)
        self._event("batch_complete", attempts=attempts, accepted=len(accepted))
        return {"generated": attempts, "accepted": len(accepted), "examples": accepted}

    @staticmethod
    def _trim_jsonl(path: Path, max_rows: int) -> None:
        if not path.exists(): return
        lines = [l for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
        if len(lines) <= max_rows: return
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text('\n'.join(lines[-max_rows:]) + '\n', encoding='utf-8')
        tmp.replace(path)

    @staticmethod
    def _parse_score(raw: str) -> float | None:
        try:
            a, b = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[a:b+1]) if a >= 0 and b > a else None
            value = float(obj.get("score")) if isinstance(obj, dict) else None
            return max(0.0, min(1.0, value)) if value is not None else None
        except Exception:
            return None

    def train_weights(self, model_id: str, run_id: str, require_gpu: bool = False) -> dict:
        """Run genuine local LoRA training when the optional ML stack is installed.
        Never reports completion unless a real training backend executes."""
        if not self.data_path.exists():
            return {"status": "skipped", "reason": "no accepted self-training data"}
        rows = [json.loads(x) for x in self.data_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        if not rows:
            return {"status": "skipped", "reason": "no accepted self-training data"}
        trainer = SFTLoRATrainer(str(self.root / "weights"))
        return trainer.train(run_id, dry_run=False, require_gpu=require_gpu, model_id=model_id, rows=rows)
