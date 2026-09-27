# Autonomous Training (PHASE 11)

## Status labels (precise)

| Label | Meaning |
|-------|---------|
| **IMPLEMENTED** | Architecture/code present |
| **EXECUTED** | A real process ran (train/eval) |
| **VERIFIED** | Checked against artifacts/tests |
| **BLOCKED** | Gate prevented progress with reason |
| **NOT YET VALIDATED** | Production bar not met |

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

`MODEL_QUALITY_PRODUCTION_VALIDATED=true` **only** when every production gate passes.

Current verified run on model-v0003:

- samples 20 < 200 → `INSUFFICIENT_EVALUATION_SAMPLES`
- pass_rate 0.58 < 0.85 → `TASK_PASS_RATE_BELOW_PRODUCTION_MIN`
- coding 0.5 < 0.7 → `CODING_PASS_RATE_BELOW_PRODUCTION_MIN`
- → **NOT_PRODUCTION_VALIDATED** (honest)

## Current verified baseline

| Field | Value | Label |
|-------|-------|-------|
| Active | model-v0003 | VERIFIED |
| LKG | model-v0001 | VERIFIED |
| Dataset | dataset-v0003 (67 accepted) | VERIFIED |
| Real training | job-94d9f8c65f8a / transformers_lora CPU | EXECUTED |
| Post-train quality gate | PASS (no regression vs LKG) | VERIFIED |
| Production validation | false | NOT YET VALIDATED |
| GPU | false | VERIFIED |
| CPU training | available | VERIFIED |
| Rollback | available | VERIFIED |

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
If resources insufficient → defer with explicit blocker.
