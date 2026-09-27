# Model Registry (PHASE 9)

Immutable versions (`model-v0001` …) store:

- base model path/hash/revision
- local path / license metadata
- dataset version, training backend, adapter type
- training config, code version, metrics, evaluation
- checkpoint path, parent model, timestamps
- states: CANDIDATE, VALIDATING, VALIDATED, CANARY, ACTIVE, REJECTED, ROLLED_BACK

LKG pointer is separate and never auto-deleted.

Activation preserves previous ACTIVE as LKG before switching.
Rollback restores LKG + ActiveModelRuntime atomically with audit.
