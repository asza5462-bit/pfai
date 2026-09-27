# Autonomous Training (PHASE 11)

## Status labels (precise)

| Label | Meaning |
|-------|---------|
| **IMPLEMENTED** | Architecture/code present |
| **EXECUTED** | A real process ran (train/eval) |
| **VERIFIED** | Checked against artifacts/tests |
| **BLOCKED** | Gate prevented progress with reason |
| **NOT YET VALIDATED** | Production bar not met |

Do **not** conflate:

| Flag | Meaning |
|------|---------|
| REAL_TRAINING_EXECUTED | Weights/adapters actually updated |
| REAL_EVALUATION_EXECUTED | Real PEFT inference scoring ran |
| PRODUCTION_VALIDATED | ProductionQualityGate passed entirely |
| PRODUCTION_READY | Same as production validated + serving eligible |

ACTIVE / `internal_active` ≠ PRODUCTION_READY.

## Architecture

```
ContinuousExperienceBridge
→ LearningCandidate (sanitize / secret-PII / quality / dedupe / provenance)
→ immutable dataset version
→ TrainingEligibilityEngine
→ DurableTrainingScheduler (growth | schedule | owner)
→ AutonomousTrainingOrchestrator
→ train → checkpoint → evaluate vs LKG → shadow/canary → activate | reject
→ ProductionQualityGate (stricter; configurable)
→ monitor → automatic rollback if post-activation regression
```

Promotion path (local deterministic + auditable):

`offline → shadow → canary → production-activation-eligible`

Passing canary ≠ production validated.

## ProductionQualityGate

Configurable via env (`PRODUCTION_MIN_EVAL_SAMPLES`, `PRODUCTION_MIN_TASK_PASS_RATE`, …).
Thresholds are **not** lowered to force a pass.

`MODEL_QUALITY_PRODUCTION_VALIDATED=true` **only** when every production gate passes.

## Current verified baseline (production-validated)

| Field | Value | Label |
|-------|-------|-------|
| Active + LKG | model-v0007 | VERIFIED |
| Previous LKG (rollback) | model-v0001 (checkpoint retained) | VERIFIED |
| Prior candidates | model-v0003 … model-v0006 | VERIFIED |
| Train dataset | dataset-v0006 | VERIFIED |
| Eval dataset | prodeval-v0003 (executed 336; ≥200) | VERIFIED |
| Real training | transformers_lora CPU (distilgpt2), prompt format aligned | EXECUTED |
| Sample gate (≥200) | PASS | VERIFIED |
| Task pass rate | 0.8690 (need ≥0.85) | PASS |
| Coding pass rate | 0.7947 (need ≥0.70) | PASS |
| Canary/shadow | PASS | VERIFIED |
| Regression vs prior LKG | false | VERIFIED |
| PRODUCTION_VALIDATED | true | VERIFIED |
| PRODUCTION_READY | true | VERIFIED |
| GPU | false | VERIFIED |
| Rollback | available (model-v0001 checkpoint) | VERIFIED |

Note: CPU LoRA on distilgpt2 is **not** claimed equivalent to production-scale GPU training.
It passed the configured local ProductionQualityGate only.

## Eval / train banks

- `production_banks.py` provides disjoint, provenance-tagged train vs eval examples
- Evaluation harvest excludes train-bank content hashes (leakage isolation)
- Future validated experiences accumulate into `evaluation_datasets/accumulator.jsonl` (eval-only)

## Owner APIs

- `GET /platform/training/eligibility`
- `GET /platform/training/scheduler`
- `GET /platform/training/observability`
- `POST /platform/training/validate` (relative post-train)
- `POST /platform/training/production-validate`
- `GET /platform/training/production-validation`
- `POST /platform/training/tick`

## Security boundaries

Training cannot modify auth, authorization, secrets, permissions, or policies.
Training data excludes passwords, API keys, OTPs, cookies, owner auth material.
Isolation tests remain enforced.

## CPU / GPU

Dynamic detection. GPU unavailable → CPU LoRA when feasible; never fake GPU.
CPU tiny-LoRA is **not** claimed equivalent to production-scale training.
If resources insufficient → defer with explicit blocker.
