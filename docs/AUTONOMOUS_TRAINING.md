# Autonomous Training (PHASE 9 + continuous experience)

## Loop

```
real operational event → ContinuousExperienceBridge
→ LearningCandidate (sanitize / secret-PII / quality / dedupe / provenance)
→ dataset version only if content checksum changes
→ trigger decision (growth|schedule|owner|regression — not min_examples alone)
→ train → checkpoint → evaluate vs LKG → canary
→ activate OR reject/rollback → record
```

## Triggers

Autonomous `should_train` requires:

1. Enough total accepted examples (`TRAINING_MIN_EXAMPLES`)
2. **AND** a justification: `dataset_growth` (≥ `TRAINING_MIN_NEW_EXAMPLES`), schedule, regression recovery, performance opportunity, or owner/explicit request

`min_examples` alone never starts autonomous training.
A new dataset version alone never starts training.
Raw chat never trains.

Owner tick: `POST /platform/training/tick`  
Verification: `GET /platform/learning/verification`  
Learning stats: `GET /platform/learning/statistics`

## Honesty

- GPU is never faked; CPU resource/timeout limits apply
- `MODEL_QUALITY_PRODUCTION_VALIDATED` remains false for small/CPU runs
- Training cannot modify auth, OTP, permissions, secrets, or application source

## Current verified baseline (PHASE 9)

- Active/LKG: `model-v0001` (distilgpt2 + transformers_lora)
- Dataset: `dataset-v0002` (52 accepted)
- Growth since previous version: **0** (no new real accepted examples yet)
- Training eligible: **false** until real growth/schedule thresholds are met
