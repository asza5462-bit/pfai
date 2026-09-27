# Autonomous Training (PHASE 10 production hardening)

## Architecture

```
ContinuousExperienceBridge
→ LearningCandidate (sanitize / secret-PII / quality / dedupe / provenance)
→ immutable dataset version (checksum change only)
→ TrainingEligibilityEngine (authoritative)
→ DurableTrainingScheduler (restart-safe; never per-chat)
→ AutonomousTrainingOrchestrator
→ train → checkpoint → evaluate vs LKG → canary → activate | reject/rollback
```

## TrainingEligibilityEngine (all gates)

1. sufficient accepted examples  
2. meaningful growth since **last trained** dataset  
3. dataset quality gate  
4. no secret/PII violations  
5. provenance satisfied  
6. evaluation suite available  
7. compatible training backend  
8. resource/time budget  
9. no conflicting training job  
10. justified trigger: growth **or** schedule **or** owner/explicit  

`min_examples` alone never enables autonomous training.  
If growth == 0 → `TRAINING_ELIGIBLE=false`, reason `NO_NEW_DATASET_GROWTH`.

## Observability (owner-only)

- `GET /platform/training/eligibility`
- `GET /platform/training/scheduler`
- `GET /platform/training/observability`
- `GET /platform/learning/verification`
- `POST /platform/training/tick`

## Current verified baseline

| Field | Value |
|-------|-------|
| Active / LKG | model-v0001 |
| Dataset | dataset-v0002 (52 accepted) |
| Growth | 0 |
| TRAINING_ELIGIBLE | false (`NO_NEW_DATASET_GROWTH`) |
| GPU | false (CPU LoRA only) |
| Backend | transformers_lora |
| Production quality | **false** |

No forced training. No synthetic dataset inflation. Phase 8 security intact.
