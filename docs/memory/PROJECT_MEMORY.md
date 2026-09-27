# PFAI Project Memory

Last updated: 2026-09-27 (Longevity PHASE 9)

## Snapshot

| Item | Value |
|---|---|
| Schema | target **5** |
| Owner auth | Email OTP intact (PHASE 5) |
| Training runtime | **AVAILABLE** (CPU) |
| GPU_AVAILABLE | **false** |
| Base open-weight | `data/models/distilgpt2` (~82M, operator-approved) |
| Tiny test model | `tiny-random-gpt2` (TEST_ONLY; not production) |
| Real training executed | **true** (Phase 9 LoRA on distilgpt2) |
| LKG / rollback | **implemented + verified** |
| Autonomous tick | **ready** (not per-chat) |
| MODEL_QUALITY_PRODUCTION_VALIDATED | **false** |
| Anthropic required | false |

## Honesty

- MOCK ≠ REAL
- Pipeline success ≠ production quality
- No silent model downloads
