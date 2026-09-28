# PFAI Project Memory

Last updated: 2026-09-28 (PFAI 8.5.0 — integrity harden · web latency bound)

## Snapshot

| Item | Value |
|---|---|
| Schema | target **5** |
| Public access | ON in production (no login) |
| Open chat tools | Unlocked in public/production (`PFAI_OPEN_CHAT_TOOLS`) |
| Owner auth | Username + password hash (OTP removed); optional in public mode |
| License | Apache-2.0 (`LICENSE`) |
| Training runtime | **AVAILABLE** (CPU) |
| GPU_AVAILABLE | **false** |
| Base open-weight | `data/models/distilgpt2` (~82M, operator-approved) |
| Tiny test model | `tiny-random-gpt2` (TEST_ONLY; not production) |
| Real training executed | **true** (Phase 9 LoRA on distilgpt2) |
| LKG / rollback | **implemented + verified** |
| Autonomous tick | **ready** (not per-chat) |
| MODEL_QUALITY_PRODUCTION_VALIDATED | **false** |
| Anthropic required | false |

## Advanced self-develop (8.5)

- Maturity stages: emerging → capable → advanced → sovereign_safe
- Multi-pass code build (review×3, repair≤6), sandbox-only accept
- Chat: advanced_status / awareness / self_develop / code_build
- Still never auto-promotes weights

## Unified Super Brain (8.5)

- One mind: `unified_brain_pulse` parallel local lanes
- Command Chat sole runtime when PFAI_UNIFIED_BRAIN=1
- Soft-degrade lanes; never invent; never silent weight promote

## Honesty

- MOCK ≠ REAL
- Pipeline success ≠ production quality
- No silent model downloads
