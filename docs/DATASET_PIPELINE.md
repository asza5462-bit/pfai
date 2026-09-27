# Dataset Pipeline — PHASE 10

## Flow

```
REAL EVENT → ContinuousExperienceBridge
→ sanitize → secret/PII → quality → dedupe → provenance
→ ACCEPTED | REJECTED | PENDING_REVIEW | INELIGIBLE
→ dataset version only if content checksum changes
→ USED_IN_DATASET
→ TrainingEligibilityEngine (growth since last trained)
```

Raw chat remains ineligible. No synthetic inflation.

## Growth

- Version growth: accepted-count delta between dataset versions  
- Training growth: accepted-count delta since **last trained** dataset (scheduler durable state)  
- Current verified: `dataset-v0002`, 52 accepted, growth **0** → not training-eligible

## Eligibility reason when blocked

`NO_REAL_DATASET_GROWTH` (alias `NO_NEW_DATASET_GROWTH`) when there are no new
accepted examples since the last trained / versioned baseline.

Do not treat historical seed data as new growth.
