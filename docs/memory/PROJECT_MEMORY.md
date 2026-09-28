# PFAI Project Memory

Last updated: 2026-09-28 (PFAI 8.8.0 — quantum-inspired speed + IoT + evolution cadence)

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

## Advanced self-develop (8.6)

- Maturity stages: emerging → capable → advanced → sovereign_safe
- Multi-pass code build (review×3, repair≤6), sandbox-only accept
- Chat: advanced_status / awareness / self_develop / code_build
- Still never auto-promotes weights

## Unified Super Brain (8.6)

- One mind: `unified_brain_pulse` parallel local lanes
- Command Chat sole runtime when PFAI_UNIFIED_BRAIN=1
- Soft-degrade lanes; never invent; never silent weight promote

## Legendary chat mind (8.6)

- Deep comprehension before plan/compose
- Legendary memory: facts + digests + ranked recall + desire ingest
- Elite replies: فهمتك → memory → live → next step

## Quantum-inspired + IoT + evolution (8.8)

- Classical parallel hypothesis core with measured ns/μs — **not** quantum hardware
- IoT mind: MQTT/Zigbee/Matter/CoAP/Modbus/OPC-UA/edge/security grounded cards
- Evolution cadence: minute (quantum+continuous), hour (autonomy), day (advanced develop)
- Chat tools: quantum_pulse/status, iot_understand, evolution_status/tick
- Still never auto-promotes weights; no fabricated sensor telemetry

## Smart continuous training (8.7)

- Focus curriculum + precision scoring + adaptive intervals (60–120s open)
- Seeds high-precision examples when queue thin; no empty-cycle stall
- Precision fallback when teacher/LLM evaluator unavailable
- Pushes curated rows into longevity experience for dataset growth
- Chat: `smart_continuous_status` + Arabic intents for تدريب بذكاء/تركيز/دقة
- Still never auto-promotes weights; SSRF/security unchanged
- Weight eligibility may still report TRAINING_BACKEND_UNAVAILABLE on hosts without torch

## Honesty

- MOCK ≠ REAL
- Pipeline success ≠ production quality
- No silent model downloads
