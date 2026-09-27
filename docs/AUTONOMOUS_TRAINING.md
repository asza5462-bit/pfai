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
| Active | model-v0003 |
| LKG | model-v0001 (preserved) |
| Dataset | dataset-v0003 (67 accepted; prior dataset-v0002 preserved) |
| Post-train validation | complete (real PEFT inference + perplexity vs LKG) |
| Quality gate | PASS (no regression vs LKG) |
| Production quality | **false** (suite too small / CPU LoRA insufficient) |
| GPU | false |
| Backend | transformers_lora |
| Last real job | job-94d9f8c65f8a |

Owner API: `POST /platform/training/validate`


## PHASE 10 verification (real eligibility + growth)

Blocker was empty candidate store + coding observers wired to `None`.

Fixed: `VerifiedOutcomeStore`, prior-dataset merge in builds, eligibility-aware `run_cycle`.

15 new ACCEPTED examples from sandbox-verified coding, regression fix, eval suite, and
owner-approved operational feedback → dataset-v0003 → real CPU LoRA training →
model-v0003 ACTIVE with model-v0001 LKG.
