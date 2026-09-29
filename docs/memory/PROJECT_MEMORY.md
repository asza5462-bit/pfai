# PFAI Project Memory

Last updated: 2026-09-29 (PFAI 8.14.0 — cold-start wake/retry + Claude-grade ops)

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

## Legendary chat mind (8.13)

- Deep comprehension before plan/compose (internal only — not dumped to user)
- Legendary memory: facts + digests + ranked recall + desire ingest + guardian
- Elite replies: natural Arabic/EN via `elite_reply.py`; provider `pfai-brain`
- Short-circuits: remember confirm, name recall, honest empty-name (no JSON/timeline fog)
- `live_monitor.py`: 24/7 ensure continuous + evolution + LoRA-when-eligible + heal/develop
- Weight activation still never silent; monitor starts real jobs only

## Free Sovereign Integrity (8.9)

- `free_sovereign_cycle`: audit → schema migrate → heal → workers → sandbox code repair → re-audit
- Chat: صلاحية كاملة / بلا قيود / راجع كل شيء / ذكاء حر
- Auto schema apply on boot (backup-first); hourly evolution runs deep sovereign cycle
- Still hard-gated: weight promotion, SSRF, secrets, security policy, arbitrary host rewrite

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
