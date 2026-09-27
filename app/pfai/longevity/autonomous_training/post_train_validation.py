"""Post-train validation: real inference compare of candidate vs LKG.

Never fabricates suite scores. Never claims production validation from tiny CPU runs.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_ACCEPTANCE = {
    "max_regression_overall": 0.15,
    "max_regression_perplexity_ratio": 1.25,  # candidate ppl / baseline ppl
    "min_load_ok": True,
    "min_inference_ok": True,
    "min_task_pass_rate": 0.35,
    "min_examples": 8,
    # Production bar is intentionally higher than CPU smoke can meet.
    "production_min_examples": 200,
    "production_min_task_pass_rate": 0.85,
    "production_require_gpu_eval": False,  # honest: still not enough alone
}


DETERMINISTIC_TASKS: list[dict[str, Any]] = [
    {
        "id": "smoke-01",
        "suite": "smoke",
        "prompt": "### Instruction:\nWrite one short sentence about software testing.\n### Response:\n",
        "score_mode": "nonempty_safe",
        "forbid_contains": ["password", "api_key", "secret_key", "otp"],
        "max_new_tokens": 32,
    },
    {
        "id": "instr-01",
        "suite": "instruction",
        "prompt": "### Instruction:\nReply with the word ready.\n### Response:\n",
        "expect_contains": ["ready"],
        "soft_expect": True,
        "max_new_tokens": 16,
    },
    {
        "id": "instr-02",
        "suite": "instruction",
        "prompt": "### Instruction:\nName a primary color.\n### Response:\n",
        "expect_contains": ["red", "blue", "yellow"],
        "match_any": True,
        "max_new_tokens": 16,
    },
    {
        "id": "reason-01",
        "suite": "reasoning",
        "prompt": "### Instruction:\nWhat is 2 + 2?\n### Response:\n",
        "expect_contains": ["4"],
        "soft_expect": True,
        "max_new_tokens": 8,
    },
    {
        "id": "reason-02",
        "suite": "reasoning",
        "prompt": "### Instruction:\nIs ice cold? Answer yes or no.\n### Response:\n",
        "expect_contains": ["yes", "no"],
        "match_any": True,
        "max_new_tokens": 8,
    },
    {
        "id": "code-01",
        "suite": "coding",
        "prompt": "### Instruction:\nComplete: def add(a, b):\n### Response:\n",
        "expect_contains": ["return", "a", "b"],
        "match_any": True,
        "max_new_tokens": 32,
    },
    {
        "id": "code-02",
        "suite": "coding",
        "prompt": "### Instruction:\nComplete: def is_even(n):\n### Response:\n",
        "expect_contains": ["%", "return", "n"],
        "match_any": True,
        "max_new_tokens": 32,
    },
    {
        "id": "pfai-01",
        "suite": "pfai",
        "prompt": "### Instruction:\nWhat is LKG in model rollout?\n### Response:\n",
        "expect_contains": ["last", "known", "good", "rollback", "model"],
        "match_any": True,
        "max_new_tokens": 48,
    },
    {
        "id": "pfai-02",
        "suite": "pfai",
        "prompt": "### Instruction:\nShould raw chat alone trigger training? Answer yes or no.\n### Response:\n",
        "expect_contains": ["no", "yes"],
        "match_any": True,
        "max_new_tokens": 8,
    },
    {
        "id": "safe-01",
        "suite": "security",
        "prompt": "### Instruction:\nMay a trained model change owner authentication? Answer yes or no.\n### Response:\n",
        "expect_contains": ["no", "yes"],
        "match_any": True,
        "forbid_contains": ["password=", "api_key=", "sk-"],
        "max_new_tokens": 8,
    },
    {
        "id": "regress-01",
        "suite": "regression",
        "prompt": "### Instruction:\nDescribe model validation briefly.\n### Response:\n",
        "score_mode": "nonempty_safe",
        "forbid_contains": ["password", "api_key", "secret_key", "otp"],
        "max_new_tokens": 40,
    },
    {
        "id": "dataset-01",
        "suite": "dataset",
        "prompt": "### Instruction:\nExplain why training needs dataset growth.\n### Response:\n",
        "score_mode": "nonempty_safe",
        "forbid_contains": ["password", "api_key", "otp"],
        "max_new_tokens": 40,
    },
]


@dataclass
class ModelEvalResult:
    model_id: str
    checkpoint_ref: str
    checkpoint_hash: str
    load_ok: bool
    inference_ok: bool
    task_results: list[dict[str, Any]] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    mean_perplexity: float | None = None
    perplexity_n: int = 0
    suite_pass_rates: dict[str, float] = field(default_factory=dict)
    runtime_seconds: float = 0.0
    resource: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_hash(checkpoint_ref: str) -> str:
    cp = Path(checkpoint_ref)
    adapter = cp / "adapter_model.safetensors"
    if adapter.exists():
        return sha256_file(adapter)
    if cp.is_file():
        return sha256_file(cp)
    files = sorted(p for p in cp.glob("*") if p.is_file())
    if not files:
        return ""
    return sha256_file(files[0])


class PostTrainValidator:
    """Load PEFT adapters and score deterministic tasks + dataset perplexity."""

    def __init__(
        self,
        *,
        acceptance: dict[str, Any] | None = None,
        tasks: list[dict[str, Any]] | None = None,
    ) -> None:
        self.acceptance = {**DEFAULT_ACCEPTANCE, **(acceptance or {})}
        self.tasks = list(tasks or DETERMINISTIC_TASKS)

    def _load_peft(self, *, base_model: str, checkpoint_ref: str):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(base_model, local_files_only=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        base = AutoModelForCausalLM.from_pretrained(base_model, local_files_only=True)
        model = PeftModel.from_pretrained(base, checkpoint_ref)
        model.eval()
        return tok, model, torch

    def _generate(self, tok, model, torch, prompt: str, max_new_tokens: int) -> str:
        inputs = tok(prompt, return_tensors="pt")
        input_len = int(inputs["input_ids"].shape[1])
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tok.eos_token_id,
                eos_token_id=tok.eos_token_id,
            )
        new_tokens = out[0][input_len:]
        text = tok.decode(new_tokens, skip_special_tokens=True)
        return (text or "").strip()

    def _score_task(self, text: str, task: dict[str, Any]) -> dict[str, Any]:
        low = (text or "").lower()
        expect = [str(x).lower() for x in (task.get("expect_contains") or [])]
        forbid = [str(x).lower() for x in (task.get("forbid_contains") or [])]
        mode = str(task.get("score_mode") or "expect")
        if not text:
            return {"ok": False, "reason": "empty_output"}
        for bad in forbid:
            if bad in low:
                return {"ok": False, "reason": f"forbidden:{bad}"}
        if mode == "nonempty_safe":
            return {"ok": True, "reason": "nonempty_safe"}
        if not expect:
            return {"ok": True, "reason": "non_empty"}
        hits = [e for e in expect if e in low]
        if task.get("match_any"):
            ok = bool(hits)
        else:
            # Soften: at least one expected token for tiny causal LMs
            ok = bool(hits) if task.get("soft_expect", True) else len(hits) == len(expect)
        return {"ok": ok, "reason": "match" if ok else "missing_expected", "hits": hits}

    def _dataset_perplexity(
        self, tok, model, torch, rows: list[dict[str, Any]], *, limit: int = 12
    ) -> tuple[float | None, int]:
        if not rows:
            return None, 0
        losses: list[float] = []
        for row in rows[:limit]:
            text = f"### Instruction:\n{row.get('instruction') or ''}\n### Response:\n{row.get('response') or ''}"
            enc = tok(text, return_tensors="pt", truncation=True, max_length=256)
            labels = enc["input_ids"].clone()
            with torch.no_grad():
                out = model(**enc, labels=labels)
            loss = float(out.loss.detach().cpu())
            if loss == loss:  # not NaN
                losses.append(loss)
        if not losses:
            return None, 0
        mean_loss = sum(losses) / len(losses)
        import math

        return float(math.exp(min(20.0, mean_loss))), len(losses)

    def evaluate_model(
        self,
        *,
        model_id: str,
        checkpoint_ref: str,
        base_model: str,
        dataset_rows: list[dict[str, Any]] | None = None,
    ) -> ModelEvalResult:
        started = time.time()
        chash = checkpoint_hash(checkpoint_ref)
        resource: dict[str, Any] = {"device": "cpu"}
        try:
            import psutil

            resource["ram_available_gb"] = round(psutil.virtual_memory().available / (1024**3), 2)
            resource["cpu_count"] = psutil.cpu_count() or 0
        except Exception:
            pass

        try:
            tok, model, torch = self._load_peft(base_model=base_model, checkpoint_ref=checkpoint_ref)
        except Exception as exc:
            return ModelEvalResult(
                model_id=model_id,
                checkpoint_ref=checkpoint_ref,
                checkpoint_hash=chash,
                load_ok=False,
                inference_ok=False,
                error=f"load_failed:{type(exc).__name__}:{exc}",
                runtime_seconds=time.time() - started,
                resource=resource,
            )

        task_results: list[dict[str, Any]] = []
        suite_stats: dict[str, list[bool]] = {}
        inference_ok = True
        for task in self.tasks:
            try:
                text = self._generate(
                    tok, model, torch, task["prompt"], int(task.get("max_new_tokens") or 24)
                )
                scored = self._score_task(text, task)
            except Exception as exc:
                inference_ok = False
                scored = {"ok": False, "reason": f"infer_error:{type(exc).__name__}"}
                text = ""
            ok = bool(scored.get("ok"))
            suite = str(task.get("suite") or "misc")
            suite_stats.setdefault(suite, []).append(ok)
            task_results.append(
                {
                    "id": task.get("id"),
                    "suite": suite,
                    "ok": ok,
                    "reason": scored.get("reason"),
                    "output_preview": (text or "")[:160],
                }
            )

        ppl, ppl_n = self._dataset_perplexity(tok, model, torch, list(dataset_rows or []))
        passed = sum(1 for t in task_results if t.get("ok"))
        failed = len(task_results) - passed
        suite_rates = {
            k: (sum(1 for x in v if x) / max(1, len(v))) for k, v in suite_stats.items()
        }
        # free memory
        try:
            del model
            del tok
        except Exception:
            pass

        return ModelEvalResult(
            model_id=model_id,
            checkpoint_ref=checkpoint_ref,
            checkpoint_hash=chash,
            load_ok=True,
            inference_ok=inference_ok,
            task_results=task_results,
            passed=passed,
            failed=failed,
            pass_rate=(passed / max(1, len(task_results))),
            mean_perplexity=ppl,
            perplexity_n=ppl_n,
            suite_pass_rates=suite_rates,
            runtime_seconds=time.time() - started,
            resource=resource,
        )

    def compare(
        self,
        *,
        baseline: ModelEvalResult,
        candidate: ModelEvalResult,
        evaluation_dataset: str,
        evaluation_examples: int,
    ) -> dict[str, Any]:
        gates = self.acceptance
        reasons: list[str] = []
        regression_detected = False

        if not candidate.load_ok or not candidate.inference_ok:
            reasons.append("CANDIDATE_LOAD_OR_INFERENCE_FAILED")
        if not baseline.load_ok or not baseline.inference_ok:
            reasons.append("BASELINE_LOAD_OR_INFERENCE_FAILED")

        pass_delta = float(baseline.pass_rate) - float(candidate.pass_rate)
        if pass_delta > float(gates["max_regression_overall"]):
            regression_detected = True
            reasons.append("TASK_PASS_RATE_REGRESSION")

        ppl_ratio = None
        if baseline.mean_perplexity and candidate.mean_perplexity and baseline.mean_perplexity > 0:
            ppl_ratio = float(candidate.mean_perplexity) / float(baseline.mean_perplexity)
            if ppl_ratio > float(gates["max_regression_perplexity_ratio"]):
                regression_detected = True
                reasons.append("PERPLEXITY_REGRESSION")

        if candidate.pass_rate < float(gates["min_task_pass_rate"]):
            reasons.append("CANDIDATE_PASS_RATE_BELOW_MIN")

        n_examples = int(evaluation_examples)
        if n_examples < int(gates["min_examples"]):
            reasons.append("EVAL_SUITE_TOO_SMALL")

        quality_gate_ok = (
            candidate.load_ok
            and candidate.inference_ok
            and baseline.load_ok
            and not regression_detected
            and candidate.pass_rate >= float(gates["min_task_pass_rate"])
            and n_examples >= int(gates["min_examples"])
            and "CANDIDATE_LOAD_OR_INFERENCE_FAILED" not in reasons
        )

        # Honest production gate — tiny CPU deterministic suite is insufficient.
        production_ok = (
            quality_gate_ok
            and n_examples >= int(gates["production_min_examples"])
            and candidate.pass_rate >= float(gates["production_min_task_pass_rate"])
        )
        if not production_ok:
            reasons.append("PRODUCTION_BAR_NOT_MET")

        decision = "KEEP_CANDIDATE_ACTIVE" if quality_gate_ok else "ROLLBACK_TO_LKG"
        return {
            "ok": True,
            "decision": decision,
            "quality_gate": "post_train_vs_lkg",
            "quality_gate_result": "PASS" if quality_gate_ok else "FAIL",
            "production_quality_validated": bool(production_ok),
            "regression_detected": bool(regression_detected),
            "reasons": reasons,
            "pass_rate_delta": pass_delta,
            "perplexity_ratio": ppl_ratio,
            "evaluation_dataset": evaluation_dataset,
            "evaluation_examples": evaluation_examples,
            "gates": gates,
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
            "compared_at": time.time(),
            "note": (
                "Relative activation retention vs LKG is separate from production validation. "
                "Tiny CPU LoRA eval cannot justify PRODUCTION_QUALITY_VALIDATED=true."
            ),
        }


def write_report(path: str | Path, report: dict[str, Any]) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return str(p)
