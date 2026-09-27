# Model Registry (PHASE 11)

Immutable versions (`model-v0001` …) store:

- base model path/hash/revision
- local path / license metadata
- dataset version, training backend, adapter type
- training config, code version, metrics, evaluation
- checkpoint path, parent model, timestamps
- states: CANDIDATE, VALIDATING, VALIDATED, CANARY, ACTIVE, REJECTED, ROLLED_BACK, LKG
- meta serving flags: `production_ready`, `serving_tier` (`internal_active` | `production_ready`)

## Semantic safety

| Concept | Meaning |
|---------|---------|
| ACTIVE / internal_active | Lab/eval serving pointer |
| production_ready | Passed ProductionQualityGate |
| LKG | Production fallback; not overwritten by internal activations |
| production serving | Uses LKG until candidate is production_ready |

Activation of a non-`production_ready` model does **not** replace an existing production LKG.

LKG pointer is separate and never auto-deleted.
Rollback restores LKG + ActiveModelRuntime atomically with audit.

## Current pointers (verified)

- Previous LKG checkpoint retained = model-v0001 (rollback available via promotion history)
- PREVIOUS_LKG_MODEL resolved from durable `promotion_history.jsonl` (not current LKG pointer alone)
- PRODUCTION_VALIDATED = true / PRODUCTION_READY = true
- LKG is updated only after ProductionQualityGate pass; internal ACTIVE never implied production_ready
- ROLLBACK_AVAILABLE = full (history → model-v0001)
