# PFAI Project Memory

Last updated: 2026-09-27 (Longevity PHASE 8)

## Snapshot

| Item | Value |
|---|---|
| Schema | target **5** |
| Owner auth | Email OTP intact (PHASE 5) |
| Autonomous training | Orchestrator + detector + real LoRA backend (PHASE 6–8) |
| Training runtime (this env) | **AVAILABLE** (CPU; torch/transformers/peft/datasets/safetensors) |
| Real training executed | **true** (bounded LoRA on local tiny-random-gpt2) |
| Real model active | **true** (phase8 verify run; adapter safetensors) |
| Skill packs | versioned registry enabled |
| Anthropic required | false |

## Honesty

- MOCK TESTS: CI/unit path with `allow_mock_backend`
- REAL TRAINING VERIFIED: PEFT Trainer loop + reloadable adapter checkpoint
- Never conflate the two
