# Dataset Pipeline — LearningCandidate + continuous experience

## Flow

```
REAL OPERATIONAL EVENT → ContinuousExperienceBridge
→ OBSERVATION → SANITIZATION → SECRET/PII → QUALITY → DEDUPE
→ PROVENANCE → LABEL → ACCEPTED|REJECTED|PENDING_REVIEW|INELIGIBLE
→ DATASET VERSION (only if content checksum changes)
→ USED_IN_DATASET
```

Never trains from raw chat. Never manufactures examples to inflate counts.

## Eligibility

`INELIGIBLE` | `PENDING_REVIEW` | `ACCEPTED` | `REJECTED` | `USED_IN_DATASET`

## Source attribution (trust-weighted)

`USER_APPROVED` `TASK_SUCCESS` `CODE_TEST_PASS` `KNOWLEDGE_VERIFIED` `FEEDBACK`
`TOOL_SUCCESS` `SKILL_SUCCESS` `SELF_CHECK` `CORRECTED_FAILURE` `EVALUATION`

Wired from: coding exercise pass, `/code/solve`, regression capture, durable knowledge store,
owner feedback, tool/skill success, eval suite pass, self-check pass.

## Versioning & growth

- Immutable `dataset-v000N`
- New version **only** when accepted content checksum changes
- Unchanged content → reuse prior version (`unchanged=true`)
- Growth = accepted-example count delta between consecutive versions
- Current verified: `dataset-v0002` with **52** accepted; growth since previous = **0**
- Insufficient real growth → `INSUFFICIENT_REAL_DATA` (keep collecting; do not train)

A small accepted count proves the pipeline — **not** production model quality.
