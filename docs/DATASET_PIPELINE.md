# Dataset Pipeline — LearningCandidate growth layer

## Flow

```
OBSERVATION → SANITIZATION → SECRET/PII FILTER → QUALITY CHECK
→ DEDUPLICATION → PROVENANCE → LABEL/OUTCOME → EVALUATION
→ ACCEPTED DATASET → DATASET VERSION
```

Training does **not** run on every chat. Candidates are collected from:

- User-approved / owner-approved interactions
- Successful task completions & coding passes
- Corrected failures
- Knowledge / durable learning with provenance
- Evaluation lessons
- Tool/skill outcomes (no raw secrets)
- Explicitly eligible memory entries (via durable pipeline)

## Gates

- Sanitizer `sanitize_v2`: secrets, cookies, session tokens, PII → `[REDACTED]` / `[REDACTED_PII]`
- Authority isolation (auth/OTP/permission paths never enter corpora)
- Configurable `LEARNING_CANDIDATE_MIN_QUALITY` / `TRAINING_MIN_DATASET_QUALITY`
- Dedup by content hash
- Provenance + eligibility on every accepted example
- Train / validation / test split with leakage detection

Statuses: `DATASET_READY` | `INSUFFICIENT_DATA` | `DATASET_INVALID`

## Versioning

Immutable versions `dataset-v000N` are created **only** when the quality gate passes.

## Statistics (owner APIs)

`/platform/learning/statistics`, `/platform/learning/dataset`, `/platform/training/datasets`

Expose counts, rejection reasons, source/quality distribution, split counts — **never** secret payloads or private training text.

A small accepted count proves the pipeline — **not** production model quality.
