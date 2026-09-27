# Dataset Pipeline (PHASE 9)

Sources (approved, not raw logs):

- durable learning candidates
- approved seed examples
- coding examples
- owner-approved learning rows

Gates: sanitize, secrets/credentials filter, dedupe, provenance, quality score, train/val/test split, leakage detection.

Statuses: `DATASET_READY` | `INSUFFICIENT_DATA` | `DATASET_INVALID`

Versions are immutable (`dataset-v000N`) with checksum and rejection stats.

A small accepted count (tens of examples) proves the pipeline — **not** production model quality.
