"""Future training dataset / evaluation scaffold (no automatic production fine-tune)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable


class CodingTrainingScaffold:
    """Collects approved coding examples for later offline evaluation/fine-tuning."""

    def __init__(self, root: str = "data/coding_academy/training_scaffold"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.examples = self.root / "approved_examples.jsonl"
        self.evals = self.root / "evaluations.jsonl"

    def add_example(self, *, owner: str, kind: str, prompt: str, response: str, metadata: dict | None = None) -> dict:
        row = {
            "ts": time.time(),
            "owner": owner,
            "kind": kind,
            "prompt": prompt,
            "response": response,
            "metadata": metadata or {},
            "approved_for_finetune": False,
        }
        with self.examples.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "stored": True, "finetune_queued": False}

    def record_eval(self, *, name: str, metrics: dict, notes: str = "") -> dict:
        row = {"ts": time.time(), "name": name, "metrics": metrics, "notes": notes}
        with self.evals.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True}

    def status(self) -> dict:
        ex = _count_lines(self.examples)
        ev = _count_lines(self.evals)
        return {
            "examples": ex,
            "evaluations": ev,
            "auto_finetune": False,
            "note": "Fine-tuning remains offline/manual and owner-gated; this scaffold only collects data.",
        }


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
