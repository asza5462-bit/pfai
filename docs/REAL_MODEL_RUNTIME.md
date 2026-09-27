# Real Model Runtime (PHASE 9)

## Hardware (this environment)

- CPU: 4 cores
- RAM: ~15.6 GB total / ~4.7 GB available at audit time
- Disk free: ~108 GB
- GPU_AVAILABLE: **false** (no CUDA device; VRAM none)
- Training strategy: `cpu_lora_small_model`

## Current local models

| Path | Class | Notes |
|---|---|---|
| `data/models/tiny-random-gpt2` | TEST_ONLY | Phase 8 pipeline probe only |
| `data/models/distilgpt2` | LOCAL_MODEL_AVAILABLE | Real open-weight (~82M), operator-approved install |

## Selection rules

- No silent hub downloads at runtime.
- Missing model → `MODEL_NOT_INSTALLED` + documented install command.
- Install requires explicit `--approve`.

```bash
cd app
python -m pfai.longevity.autonomous_training.install_open_weight \
  --model distilgpt2 --dest data/models/distilgpt2 --approve
export MODEL_PATH=data/models/distilgpt2
export MODEL_PROVIDER=transformers_local
export MODEL_LICENSE=apache-2.0
```

## Inference provider

`transformers_local` loads from `MODEL_PATH` in-process and can bind a PEFT adapter from `ActiveModelRuntime`.

Statuses: `MODEL_AVAILABLE`, `MODEL_LOADABLE`, `MODEL_ACTIVE`, `MODEL_NOT_INSTALLED`, `MODEL_LOAD_ERROR`.

## Honesty

Pipeline completion ≠ production model quality. CPU LoRA on distilgpt2 with a small curated dataset is verification, not a quality claim.
