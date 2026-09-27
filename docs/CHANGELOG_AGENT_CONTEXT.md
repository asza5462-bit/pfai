# Agent Context Changelog

## 2026-09-27 — Longevity PHASE 9: Real open-weight upgrade + autonomous training

### Added
- `OpenWeightModelSelector` + hardware audit (honest GPU/VRAM)
- Explicit installer `install_open_weight` (requires `--approve`; no silent download)
- `transformers_local` provider (in-process MODEL_PATH + optional LoRA adapter)
- Approved experience seeds + stronger DatasetQualityGate (`DATASET_READY` / leakage)
- Docs: REAL_MODEL_RUNTIME, AUTONOMOUS_TRAINING, MODEL_REGISTRY, DATASET_PIPELINE, TRAINING_LIMITATIONS
- Tests `test_v100_phase9_open_weight.py`

### Executed (this environment)
- Installed **distilgpt2** locally with explicit `--approve`
- Real LoRA on distilgpt2 → safetensors checkpoint → eval/canary → activate → LKG → rollback
- GPU_AVAILABLE=false; CPU LoRA strategy
- MODEL_QUALITY_PRODUCTION_VALIDATED=**false** (small dataset / bounded steps)

## 2026-09-27 — Longevity PHASE 8: Real training runtime enablement + first verified real training

### Added
- Deterministic install path: `requirements-training.txt` + `setup_runtime.py`
- Fully functional `RealLoRATrainingBackend` (PEFT LoRA loop, safetensors adapters, reload validation)
- Explicit model gating: `MODEL_PATH` / `MODEL_NAME` + `MODEL_DOWNLOAD_APPROVED` (no silent hub downloads)
- Job states: DATA_VALIDATION, TRAINING, SHADOW, CANARY, ACTIVATING, ACTIVE, ROLLED_BACK, NO_COMPATIBLE_MODEL
- Owner aliases: `GET /platform/models`, `POST /platform/models/{id}/activate|rollback`
- Control Center honest labels: REAL_TRAINING_AVAILABLE / EXECUTED / REAL_MODEL_ACTIVE
- Tests `test_v99_phase8_real_training.py`; ADR-028; `docs/TRAINING_RUNTIME.md`

### Hardening (same day, still PHASE 8)
- Immutable model metadata: backend, metrics, parent, code version, base hash/revision
- Explicit LKG pointer (`model_lkg`); first activation marks LKG; never auto-deleted
- Automatic rollback to LKG on regression with audit + runtime restore
- DatasetQualityGate (min samples/splits/provenance/quality) → INSUFFICIENT_DATA without training
- Evaluation vs LKG + load/reload/inference checks; CANARY model state
- Resource admission: CPU honesty, max RAM/disk/time; checkpoint cleanup protects LKG
- Autonomous tick (`/platform/training/tick`) — dataset/schedule triggers only, never per-chat
- Tests `test_v99b_phase8_hardening.py`; full suite **445 passed**

### Verified (this environment)
- Runtime: **AVAILABLE** (CPU torch 2.5.1; no CUDA)
- Model: local `data/models/tiny-random-gpt2` (operator-declared license metadata)
- REAL_TRAINING_EXECUTED = **true**
- REAL_CHECKPOINT_CREATED = **true** (`adapter_model.safetensors`)
- REAL_EVALUATION_EXECUTED = **true**; CANARY_EXECUTED = **true**; MODEL_ACTIVATED = **true**
- Full pytest: **445 passed**; smoke **8/8** hardening checks
- Mock remains tests-only and never labeled as real
- LKG + automatic rollback verified in tests
- **Not claimed:** 9-example tiny-model run = production model quality

### Not done
- No deploy; no Phase 9; QLoRA blocked honestly without CUDA+bitsandbytes

## 2026-09-27 — Longevity PHASE 7: Real runtime integration + Skill Packs + Control Center

### Added
- TrainingRuntimeDetector, ModelCompatibilityChecker, TrainingResourceManager, ActiveModelRuntime, CanaryController
- SkillPackRegistry + default packs; `/platform/skills/packs*`
- Training controls: start/pause/cancel/autonomous/model activate; `/platform/runtime/status`
- Schema **v5**; Learning Control Center dashboard enrichment
- Tests `test_v98_phase7_runtime_skills.py`; ADR-027

### Behavior
- No fake real training; mock remains tests-only
- Rollback switches ActiveModelRuntime pointer
- PHASE 5 OTP + PHASE 6 orchestrator preserved

### Verified
- Targeted PHASE 7 tests: 13 passed
- Full pytest: **425 passed**
- Smoke: 11/11; schema **5**; runtime **UNAVAILABLE**; OTP intact
- REAL_TRAINING_EXECUTED = **false** (no torch/transformers/peft/trl in environment)
- MOCK_TRAINING_EXECUTED = true (tests only)
- No deploy; no git remote; no secrets exposed

## 2026-09-27 — Longevity PHASE 6: Autonomous Training + Model Lifecycle

### Added
- `longevity/autonomous_training/` — collector, sanitizer, validator, dataset versions, trainers, model registry, checkpoints, evaluation gates, rollback, orchestrator, isolation, audit
- Owner routes `/platform/training/status|jobs|datasets|models|evaluations|checkpoints|cycle|rollback`
- Dashboard **تدريب النماذج** view
- Schema **v4** `autonomous_training_foundation` (backup-first)
- Tests `test_v97_phase6_autonomous_training.py`; ADR-026

### Behavior
- Knowledge pipeline still does not mutate weights directly
- Weight training only via AutonomousTrainingOrchestrator under eval gates
- Mock trainer is tests-only (`is_mock=true`, `real_weight_update=false`)
- Missing training runtime → `TRAINING_RUNTIME_UNAVAILABLE` (no fake success)
- PHASE 5 Email OTP + authz preserved

### Verified
- Targeted PHASE 6 tests: 17 passed
- Full pytest: **412 passed**
- Smoke: health/dashboard/OTP/schema4/training status honest (`TRAINING_RUNTIME_UNAVAILABLE` here)
- No deploy; no git remote; no secrets; no fake real training success
- Actual real weight training executed: **NO** (training stack/runtime unavailable in this environment)

## 2026-09-27 — Longevity PHASE 5: Email OTP / Local providers / Migration audit

### Added
- `email_provider.py` — EmailProvider, SMTPEmailProvider, MockEmailProvider
- Owner Email OTP request/verify in `owner_auth.py` + `/owner/otp/request|verify`
- Dashboard OTP UI (no OTP in localStorage)
- `model_local.py` — LocalModelProvider / OpenWeightModelProvider + env settings
- MigrationRunner audit + verify + rollback_one; platform schema verify helper
- Tests `test_v96_phase5_otp_providers.py`; ADR-025

### Behavior
- Passcode login + session cookie + X-Owner-Secret preserved
- Authz/planner/skills/heal unchanged and still owner-gated
- Local/open_weight are real adapters; runtime connectivity reported honestly
- Learning: no weight mutation; coding/orchestrator wiring preserved
- Dev schema apply: 1 → 3 with backup (this environment only — not a production claim)

### Verified
- Targeted PHASE 5 tests: 21 passed
- Full pytest: **395 passed**
- Smoke: `/health`, `/`, `/system`, `/metrics`, `/owner/status|otp/request`, `/platform/migrations` (schema 3), `/platform/providers` (local readiness), coding/chat/plan
- No deploy; no secrets exposed; no weight training
- Note: fixed `test_v91` MigrationRunner temp state_path so tests no longer clobber live `schema_version.json`

## 2026-09-27 — Longevity PHASE 4: Planner / Authz / Skills / Heal

### Added
- `authorized_execution.py` — ActionPermissionGate, AuthorizedExecutor, AuthorizationAudit
- ToolRouter → ToolPermission mapping via AuthorizedExecutor
- Versioned SkillRegistry (activate/rollback/compatibility)
- Real TaskPlanner (ReasoningCore adapter, caps, forbidden actions)
- Orchestrator `mode=plan`; bounded auditable SelfHeal
- Providers: `local`, `open_weight` readiness (Echo fallback)
- Schema **3** migration (skill version tables); routes `/platform/plan|skills*|tools|heal*|authz/audit`
- Tests `test_v95_phase4_platform.py`; ADR-024

### Behavior
- HIGH_RISK_WRITE+ always requires explicit owner approval
- No weight training; learning via durable pipeline only
- Legacy PermissionGate escalation ledger preserved
- `/chat/*`, `/coding/*`, Dashboard, owner auth unchanged

### Verified
- pytest: **374 passed**
- Smoke: `/health`, `/`, `/system`, `/metrics`, `/platform/plan`, chat, coding tracks
- No deploy; no git remote; no secrets added

## 2026-09-27 — Longevity PHASE 3: LTM / Knowledge / Migrations / Export

### Added
- Durable `LongTermMemory` version history (SQLite) + dedicated LTM content store
- `KnowledgeLayer` ↔ `KnowledgeVersionStore` (search/publish/history/rollback)
- `MigrationRunner` apply with mandatory backup; schema → **2**; `longevity/migrations.py`
- Populated `pfai-export-v1` export/import; durable eval baselines + `longevity` suite
- Additive owner-gated routes: `/platform/ltm*`, `/platform/knowledge/versions*`, `/platform/eval*`, `/platform/migrations*`, `/platform/export*`
- Tests `test_v94_phase3_longevity.py`; ADR-023

### Behavior
- `/chat/*`, Dashboard, owner auth unchanged
- Learning still `allows_weight_mutation()==False`; Anthropic not required
- Memory substring hits preferred alongside semantic index (search merge)

### Verified
- pytest: **362 passed**
- No deploy; no git remote added

## 2026-09-27 — Owner Authentication + first-time setup

### Added
- `owner_auth.py` — setup lock, PBKDF2 hashing, HttpOnly sessions, rate-limit lockout
- Routes: `/owner/status`, `/owner/setup`, `/owner/login`, `/owner/logout` (identity remains gated)
- Dashboard login/setup modal (no passcode in sessionStorage)
- `python -m pfai.hash_owner_secret`, `docs/OWNER_AUTH.md`, ADR-022
- Tests `test_v93_owner_auth.py`

### Security
- Never stores/logs/returns plaintext passcodes
- Legacy `X-Owner-Secret` still verified server-side for automation
- Setup cannot be re-run after lock / existing configuration
- Dev-shared passcodes treated as compromised before any deploy

### Verified
- pytest: **342 passed**
- No plaintext passcodes in source/docs/frontend

## 2026-09-27 — Longevity PHASE 2: Orchestrator + ProviderRegistry

### Added
- Real `ProviderRegistry` (echo/mock/openai_compatible/anthropic optional) + `ModelRouter.from_config`
- Real `Orchestrator` coordinating Command/Coding/Skills/LTM/Knowledge/Eval/Self-check/heal/Learning
- `DurableSafeLearningPipeline` + `KnowledgeVersionStore` + learning audit (SQLite/JSONL)
- `LongTermMemory` / `MemorySystem` adapters; `KnowledgeLayer` search adapter; `PlatformEvaluation`; bounded `SelfCheck`/`SelfHeal`
- Additive API: `/orchestrate`, `/platform/status`, `/platform/learning`, `/platform/learning/audit`, `/platform/providers`
- `/health.platform` metadata (non-breaking)
- Tests `test_v92_phase2_orchestrator.py`; ADR-021

### Behavior
- Existing `/chat/*`, `/coding/*`, Dashboard unchanged as primary UX
- Learning never mutates weights; validate/store require approval path
- Core runs without Anthropic key (fallback Echo)

### Verified
- pytest: **329 passed**
- Smoke: `/health` + Dashboard `/` 200

## 2026-09-27 — Longevity PHASE 1: 20–30 year Architecture Foundation

### Added
- `docs/LONGEVITY.md` — mission, coupling audit, target architecture, phase boundary
- Interfaces: `ports`, expanded `memory` (LTM kinds), `learning`, `versioning`, `migration`, `backup`, `compat`; expanded model registries + eval compare + bounded heal
- Package `pfai/longevity/`: ProviderRegistry, SafeLearningPipeline, MigrationRunner, InMemoryVersionedStore, ExportBundleScaffold, CompatibilityLayer
- ADRs 012–020
- Tests `tests/test_v91_longevity_foundation.py`

### Behavior
- **No user-facing change** — FastAPI/Dashboard untouched; scaffolds not wired
- Core remains runnable without Anthropic; safe learning forbids weight mutation

### Verified
- pytest: **319 passed**
- Live `/health` + Dashboard `/` 200
- No API/Dashboard wiring changes

## 2026-09-27 — PHASE 1: Orchestrator platform interfaces

### Added
- `pfai/interfaces/` — Protocols + dataclasses: OrchestratorRequest/Result, ModelRole, MemorySystem, Knowledge, Planner, Skill, ToolPermission, Eval, Self-check/heal, Goals
- Scaffold modules (not wired to API): `orchestrator.py`, `model_router.py`, `memory_system.py`, `knowledge_layer.py`, `task_planner.py`, `self_check.py`, `self_heal.py`, `goal_system.py`
- `pfai/skills/registry.py` — in-memory SkillRegistry with Owner Gate on sensitive permissions
- ADRs 008–011 in `docs/DECISIONS.md`
- Tests `tests/test_v90_platform_interfaces.py`

### Behavior
- **No user-facing change** — FastAPI routes and Dashboard unchanged
- Anthropic not required; ModelRouter documents `anthropic_required=False`
- No fine-tune automation; no external deploy; no new auth

### Verified
- pytest: **305 passed**
- Live `/health` 200 + Dashboard `/` 200 (AI Command Chat + Coding Academy present)
- No API route wiring changes in PHASE 1

## 2026-09-27 — Coding Academy / Coding Intelligence

### Added
- `coding_agent`, `coding_curriculum`, `coding_tutor`, `coding_skill_profile`, `coding_academy_memory`
- `coding_reviewer`, `coding_debugger`, `coding_quality`, `coding_training_scaffold`
- Extensible JSON curriculum/assessments/projects/knowledge under `configs/coding/`
- API `/coding/*` + Dashboard **Coding Academy** + Chat coding intents
- Tests `test_v89_coding_academy.py`

### Behavior
- Learning Mode teaches with progressive hints; Engineering Mode focuses on task delivery
- Sandbox = existing isolated Python evaluator (no secrets/FS/network)
- Adaptive path from skill profile; repeated errors recorded
- No automatic model weight fine-tuning

### Verified
- 292 pytest passed

## 2026-09-27 — AI Command Chat (Brain ↔ Heart)

### Added
- `command_agent.py`, `tool_router.py`, `command_memory.py`, `command_audit.py`, `model_mock.py`
- API `/chat/*` + `/assets/chat.js`
- Dashboard section **AI Command Chat** (default nav entry)
- Tests `tests/test_v88_command_chat.py`

### Behavior
- Chat → Agent → Tool Router → PFAI core services → reply + timeline statuses
- Sensitive tools wait for Owner Gate approval
- Memory persists conversations, preferences, decisions, corrections (SQLite)
- No automatic model-weight mutation from chat learning

### Verified
- 279 pytest tests passed
- Live Mock chat: Arabic system analysis, English health check, continuous_start approval gate, audit log

## 2026-09-27 — Phases 2–7: memory, continuous gates, production, Docker

### Added
- `AGENTS.md`, `docs/memory/PROJECT_MEMORY.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md`, `.cursor/rules/pfai.mdc`
- `pfai/continuous_gate.py` — config + `PFAI_CONTINUOUS_TRAINING_ENABLED` override
- `pfai/logging_setup.py` — structured stdout logging
- `docker-compose.yml` (API + optional `continuous` profile)
- `.gitignore`, `.dockerignore`, `app/data/.gitkeep`

### Changed
- `run_continuous.py` respects env gate; logs each training cycle; never auto-promotes
- `api.py` — request logging, validation/500 handlers, richer `/health` + `/system`, continuous start/resume blocked when gate off, promote/approve/etc logged to owner ledger + app log
- `runtime.health` accepts extra fields
- `app.py` — openai_compatible secrets via `api_key_env` only (no JSON plaintext keys)
- `configs/default.json` — keep `continuous_training.enabled=true`, add `self_learning`, document gate
- Dockerfile CMD honors `PORT`/`PFAI_HOST`; non-root user retained
- `render.yaml` documents continuous + log env vars
- README / DEPLOY docs aligned with Docker hosting (not Vercel)

### Verified in this environment
- Full pytest suite: all passed
- Live `run_web.py`: `/health`, dashboard `/`, owner gate, code evaluate, continuous status
- Docker image build attempted; daemon/overlay limitations in Cloud Agent VM prevented a successful image layer mount (configs remain ready for Render/Railway/local Docker hosts)

## 2026-09-27 — Phase 2 memory bootstrap

- Created durable agent context files (see ADR-005).
- Operator decisions captured: continuous enabled + human-gated promotion; secrets via env only; no Vercel.
