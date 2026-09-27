# Training Runtime (PHASE 8)

## What is implemented

- Honest runtime detection: AVAILABLE / PARTIAL / UNAVAILABLE
- Real LoRA backend (`transformers_lora` / `RealLoRATrainingBackend`)
- Dataset sanitize → validate → version → train → checkpoint → evaluate → shadow → canary → activate/reject/rollback
- Owner APIs under `/platform/runtime/*`, `/platform/training/*`, `/platform/models*`
- Mock backend for CI only (`real_training=false`, `real_weight_update=false`)

## Hardware / dependency requirements

| Component | Required for real LoRA |
|---|---|
| Python 3.10+ | yes |
| torch | yes |
| transformers | yes |
| peft | yes |
| datasets | yes |
| safetensors | yes |
| accelerate | recommended |
| trl | optional (PEFT Trainer path used) |
| bitsandbytes + CUDA | required only for QLoRA |
| GPU | optional (CPU LoRA supported for tiny models) |

### Deterministic install (this environment)

```bash
cd app
python -m pfai.longevity.autonomous_training.setup_runtime
# or: pip install -r requirements-training.txt
```

Does not require AWS. Does not couple to Anthropic/OpenAI.

## Model configuration

```bash
export MODEL_PROVIDER=local_open_weight
export MODEL_PATH=/absolute/or/relative/path/to/hf_model_dir
export MODEL_NAME=$MODEL_PATH          # or hub id
export MODEL_REVISION=main             # optional
export MODEL_LICENSE=apache-2.0        # operator-declared
export MODEL_CONTEXT_LENGTH=64
export TRAINING_METHOD=lora
export TRAINING_BACKEND=transformers_lora
export TRAINING_MAX_STEPS=5
# Hub download only when explicitly approved:
# export MODEL_DOWNLOAD_APPROVED=true
```

If no compatible model: `REAL_TRAINING_EXECUTED=false`, `REASON=NO_COMPATIBLE_MODEL`.

## Start a real training run

Owner-authenticated:

```bash
curl -X POST http://127.0.0.1:8000/platform/training/start \
  -H "Content-Type: application/json" \
  -H "X-Owner-Secret: …" \
  -d '{"owner_requested":true,"activate_if_pass":true,"method":"lora"}'
```

Or programmatic cycle via `AutonomousTrainingOrchestrator.run_cycle(...)`.

## Automatic triggers

Controlled by `TrainingTriggerPolicy` + `AUTONOMOUS_TRAINING_ENABLED`:

- min examples
- scheduled
- owner_requested / explicit_retrain
- regression_recovery / performance_opportunity

Training still cannot bypass evaluation/canary gates.

## Rollback

- `POST /platform/training/rollback` or `/platform/models/{id}/rollback`
- Restores last-known-good registry entry and `ActiveModelRuntime` pointer
- Reasons audited (no secrets)

## Honesty rules

| Label | Meaning |
|---|---|
| MOCK TESTS PASSED | CI mock backend succeeded |
| REAL TRAINING VERIFIED | Actual PEFT/Trainer loop produced a reloadable adapter |
| REAL_TRAINING_EXECUTED | Job recorded `real_weight_update=true` |
| REAL_MODEL_ACTIVE | Active runtime points at a non-mock checkpoint |

Never mark mock success as real training.

## Known limitations

- First verified run used a tiny open-weight test model for pipeline proof, not production quality
- A small accepted dataset (e.g. ~9 examples) proves the pipeline only — **not** model quality
- QLoRA unavailable without CUDA + bitsandbytes
- Inference endpoint probe is separate from training availability
- Training never modifies owner auth, OTP, permissions, secrets, or app source
- Checkpoint cleanup never deletes LKG/active paths
