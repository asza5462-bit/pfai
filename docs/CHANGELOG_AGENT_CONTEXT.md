# Agent Context Changelog

## 2026-09-29 — PFAI 8.14: cold-start resilience + Claude-grade ops

### Implemented
- Frontend `wakeBackend` + multi-retry API (free-tier sleep → auto wake)
- Keepalive `/health` every 3 min while tab visible
- Ops short-circuit: «كيف حالة النظام» → natural live pulse (no JSON fog)
- Softer live-monitor boot (defer LoRA on cold start) for faster wake
- UI version labels → 8.14.0; stronger Anthropic compose system prompt
- Tests: `test_v147_resilience_ops.py`

### Honesty
- Render free tier still sleeps when idle — wake/retry hides most Load failed
- Weight promotion still never auto; Claude API used only when key present

## 2026-09-29 — PFAI 8.13: 24/7 live monitor + continuous learn/train

### Implemented
- `live_monitor.py`: supervisor pulse — ensure continuous + evolution, tick learn, LoRA when eligible (cooldown), deep heal/develop
- Boot + evolution minute bind live monitor; hour auto-train when eligible (default ON in open mode)
- Chat routing: Arabic «التدريب المستمر / التعليم المستمر / أكمل» → real start/tick/monitor tools
- Compose: natural continuous/monitor answers; no English latent leaks; UI chip spam reduced
- Tests: `test_v146_live_monitor_continuous.py`

### Honesty
- Weight activation still never auto; monitor starts real LoRA jobs only — promote stays owner-gated

## 2026-09-29 — PFAI 8.12: Elite natural reply brain

### Implemented
- `elite_reply.py`: natural Arabic/English compose — no JSON dumps, no comprehension fog
- Memory short-circuits: remember confirm, name recall, honest empty-name
- Provider brand `pfai-brain` (was `mock-command`); UI collapses timeline under “التتبع”
- Plan tools: memory audit/heal only when explicitly asked
- Tests: `test_v145_elite_reply_brain.py`

### Honesty
- Still no invented metrics; weight promotion stays gated; local brain when Anthropic absent

## 2026-09-28 — PFAI 8.9: Free Sovereign Integrity

### Implemented
- `free_sovereign.py`: full audit → migrate → heal → ensure workers → sandbox repair → re-audit
- Tools: `free_sovereign_audit|repair|cycle`, `free_ai_status`
- Startup auto-applies pending schema (backup-first); hour evolution runs deep sovereign cycle
- Arabic planner/comprehension for مراجعة شاملة / صلاحية كاملة / ذكاء حر
- Tests: `test_v142_free_sovereign.py`

### Honesty
- Productive freedom maximized; weight promotion / SSRF / secrets stay hard-gated

## 2026-09-28 — PFAI 8.8: Quantum-inspired ultra-fast + IoT + evolution

### Implemented
- `quantum_core.py`: classical parallel superposition/collapse with honest ns/μs timing
- `iot_mind.py`: grounded IoT knowledge (MQTT, Zigbee, Matter, edge, security, …)
- `evolution_cadence.py`: minute/hour/day hard-work ticks (curate → improve → develop)
- Chat tools + Arabic planner/comprehension for كمّي / IoT / سرعة / تطوّر كل دقيقة
- Tests: `test_v141_quantum_iot_evolve.py`

### Honesty
- `quantum_hardware: false` always — no fake qubits
- Local hot path measured; LLM/network remain separate slower bands
- No invented live sensor readings

## 2026-09-28 — PFAI 8.7: Smart continuous high-precision training

### Implemented
- `pfai/smart_continuous.py`: focus analyzer, precision scorer, adaptive intervals, seed bank
- Continuous orchestrator: prepare→focus-seed→rank→precision/LLM score→propose; push to experience
- Config: `smart_continuous` block; interval 120s / fast 60s open; self_training batch 3
- Chat tool `smart_continuous_status` + Arabic planner intents (تدريب بذكاء/تركيز/دقة/بدون قيود)
- Tests: `test_v140_smart_continuous.py`

### Invariants kept
- `auto_promote=False`; weight activation still owner/API explicit
- SSRF / secrets / security policy unchanged
- Weight eligibility still honest when backend missing

## 2026-09-27 — PHASE 12: Elite AI Skills + Tool Fabric

### Implemented
- `pfai/elite/`: SkillRegistry2, elite skill library (~76 skills), discovery, composer
- ToolFabric + MCP adapter (untrusted by default) + Sandbox
- EliteOrchestrator unified `/chat` contract + owner APIs under `/platform/elite/*`
- SelfCheckEngine, FailureRecovery, SkillLearningBridge
- Tests: `test_v112_phase12_elite_fabric.py` (flows A–J)

### Security
- Skills/tools/models remain capabilities only
- Privilege-escalation prompts rejected
- Training isolation preserved; no auth/secrets mutation paths added

### Not started
- Phase 13, deploy, remote push

## 2026-09-27 — PHASE 11 FINAL: durable promotion/rollback history

### Root cause
After promoting model-v0007 to LKG, `ModelRollbackManager` only consulted the current LKG pointer (equal to active), so rollback returned `lkg_is_already_active` and could not resolve to model-v0001.

### Fix
- Append-only `promotion_history.jsonl` (PROMOTION + ROLLBACK)
- `resolve_previous_production_model()` from history
- Live seed: previous_lkg=model-v0001 → new_lkg=model-v0007
- Real rollback verification: v0007→v0001 then restore; artifact hashes unchanged
- Tests: `test_v111_phase11_rollback_history.py` (A–M)

### Not changed
- Thresholds, datasets, model weights, auth/security, deploy, remote push

## 2026-09-27 — PHASE 11 FINAL: model-v0007 production-validated

### Root cause + fix
- Trainer used `### Instruction`/`### Response` while evaluator prompts use colon form
- Aligned LoRA training text format; **did not** change ProductionQualityGate thresholds or scoring

### Executed / verified
- REAL_TRAINING_EXECUTED=true → **model-v0007** (transformers_lora / distilgpt2 / dataset-v0006)
- REAL_EVALUATION_EXECUTED=true → pass_rate **0.8690**, coding **0.7947**, samples **336**
- Canary/shadow PASS; regression_detected=false
- PRODUCTION_VALIDATED=true / PRODUCTION_READY=true
- Active + LKG = model-v0007; previous LKG model-v0001 checkpoint retained for rollback
- Orchestrator promotes LKG only after ProductionQualityGate pass; status API exposes truthful blockers/metrics

### Not claimed
- GPU / production-scale training equivalence
- Phase 12 / deploy / remote push (explicitly not started)

## 2026-09-27 — PHASE 11 continued: eval banks + retrain toward production gates

### Implemented
- `production_banks.py`: disjoint provenance-tagged train/eval banks (coding + PFAI/knowledge)
- Evaluation harvest excludes production train-bank hashes (leakage isolation)
- `ActiveModelRuntime.production_serving()` keeps production on LKG until `production_ready`
- ModelRegistry activation preserves existing production LKG when outgoing model is not production_ready
- Tests: `test_v109_phase11_eval_dataset_activation.py`, `test_v110_phase11_production_banks.py`

### Executed / verified (real CPU LoRA)
- REAL_TRAINING_EXECUTED=true → model-v0004, model-v0005, model-v0006 (transformers_lora / distilgpt2)
- Best candidate retained: **model-v0005** (dataset-v0005); model-v0006 regressed and was not kept active
- REAL_EVALUATION_EXECUTED=true on model-v0005 vs LKG model-v0001
- Evaluation corpus **prodeval-v0004**: eligible 325, executed 337 (≥200) — sample gate PASS
- Canary/shadow PASS; regression_detected=false; LKG model-v0001 immutable
- PRODUCTION_VALIDATED=false / PRODUCTION_READY=false
- Remaining blockers (thresholds unchanged):
  - TASK_PASS_RATE_BELOW_PRODUCTION_MIN (0.8071 < 0.85)
  - CODING_PASS_RATE_BELOW_PRODUCTION_MIN (0.6859 < 0.70)
- Production serving path still uses LKG model-v0001 (`lkg_fallback`)

### Not claimed
- Production-ready model quality
- GPU / production-scale training equivalence

## 2026-09-27 — PHASE 11: Production validation & autonomous training hardening

### Implemented
- `ProductionQualityGate` + versioned `EvaluationSuiteRegistry`
- Local deterministic shadow/canary promotion simulation
- `run_production_validation` / `production_validation_status` on orchestrator
- Owner APIs: `/platform/training/production-validate`, `/production-validation`
- Tests: `test_v108_phase11_production_validation.py`

### Executed / verified
- Real production validation run against model-v0003 vs LKG model-v0001
- Checkpoint hashes from real adapter files
- Shadow/canary local path CONTINUE; no regression vs LKG
- `MODEL_QUALITY_PRODUCTION_VALIDATED=false` with machine-readable blockers:
  - INSUFFICIENT_EVALUATION_SAMPLES
  - TASK_PASS_RATE_BELOW_PRODUCTION_MIN
  - CODING_PASS_RATE_BELOW_PRODUCTION_MIN

### Not claimed
- Production-ready model quality
- GPU availability

## 2026-09-27 — Post-train validation of model-v0003 vs LKG model-v0001

### Added
- `PostTrainValidator`: real PEFT load, deterministic inference tasks, dataset perplexity
- `AutonomousTrainingOrchestrator.validate_active_against_lkg`
- Owner API `POST /platform/training/validate`
- Auditable report at `artifacts/post_train_validation.json`

### Result
- Real evaluation executed for both checkpoints (distinct adapter hashes)
- Quality gate PASS (no regression; candidate ppl slightly better)
- KEEP model-v0003 active; LKG remains model-v0001
- PRODUCTION_QUALITY_VALIDATED=false (eval suite / CPU LoRA insufficient for production bar)
- Failed candidate checkpoints are never deleted

## 2026-09-27 — PHASE 10: legitimate dataset growth + real CPU training

### Root cause
ContinuousExperienceBridge was hooked in API, but coding observers used `None`
and dataset builds did not merge prior versions — so growth stayed 0 on the
model-v0001 / dataset-v0002 lineage.

### Fixes
- `VerifiedOutcomeStore` + bridge mirroring for verified coding/eval outcomes
- `build_dataset_from_sources` preserves prior dataset examples
- `run_cycle` consults `TrainingEligibilityEngine` with growth

### Verified execution
- 15 new ACCEPTED examples (sandbox curriculum + verified tasks + regression + eval + owner feedback)
- `dataset-v0003` (67 accepted); prior `dataset-v0002` preserved
- Real transformers_lora CPU training: `job-94d9f8c65f8a` → `model-v0003` ACTIVE
- LKG remains `model-v0001`; checkpoint adapter present
- GPU false; production quality still false

## 2026-09-27 — PHASE 10 verification: real autonomy without forced training

### Verified
- Full code path audited (experience→…→rollback)
- Eligibility gates expose per-gate reasons; primary blocker `NO_REAL_DATASET_GROWTH`
- Trainer probe: transformers_lora can load distilgpt2 tokenizer+weights (CPU); GPU false
- No real training executed this run (growth=0); historical PHASE 9 training retained
- Live store false-eligibility from unseeded scheduler fixed (baseline seeded)
- Owner APIs: eligibility reasons + `/platform/learning/candidates`
- Tests: `test_v105_phase10_verification.py`

### Not claimed
- REAL_TRAINING_EXECUTED this run = false
- MODEL_QUALITY_PRODUCTION_VALIDATED = false

## 2026-09-27 — PHASE 10: Autonomous learning/training production hardening

### Added
- `TrainingEligibilityEngine` — authoritative multi-gate eligibility (`NO_NEW_DATASET_GROWTH` when growth==0)
- `DurableTrainingScheduler` — restart-safe schedule/baseline; concurrent job prevention
- Owner APIs: `/platform/training/eligibility`, `/scheduler`, `/observability`
- Tests `test_v104_phase10_hardening.py`
- Docs: AUTONOMOUS_TRAINING / DATASET_PIPELINE / ARCHITECTURE updated

### Verified (honest)
- Architecture READY; TRAINING_ELIGIBLE=**false** (reason `NO_NEW_DATASET_GROWTH`)
- dataset-v0002 / 52 accepted / growth 0; model-v0001 active+LKG; GPU false
- No forced training; no synthetic inflation; Phase 8 security intact
- MODEL_QUALITY_PRODUCTION_VALIDATED remains **false**

## 2026-09-27 — Autonomous learning verification (no Phase 10)

### Verified
- ContinuousExperienceBridge → LearningCandidate → dataset checksum versioning → trigger → train gates
- Autonomous triggers now require growth/schedule/owner justification (not min_examples alone)
- Raw chat ineligible; secrets rejected; LKG/rollback/isolation intact
- PHASE 9 artifacts intact: model-v0001 active/LKG, dataset-v0002 (52), GPU false
- No new real growth → TRAINING_ELIGIBLE=false; no forced training; no synthetic inflation
- Tests `test_v103_autonomous_learning_verification.py`; docs updated to real state

### Not claimed
- MODEL_QUALITY_PRODUCTION_VALIDATED remains **false**
- No new real training run in this verification pass

## 2026-09-27 — Continuous real experience collection (post–PHASE 9)

### Added
- `ContinuousExperienceBridge` wired to coding pass, regression fixes, durable knowledge store, owner feedback, tools/skills
- Explicit eligibility: INELIGIBLE / PENDING_REVIEW / ACCEPTED / REJECTED / USED_IN_DATASET
- Source attribution + trust weights (CODE_TEST_PASS, FEEDBACK, …)
- Dataset versions created only when content checksum changes
- `INSUFFICIENT_REAL_DATA` when no new real growth; raw chat never trains
- Owner stats: growth, last accepted/training timestamps, next training eligibility
- Tests `test_v102_continuous_experience.py`

### Constraints
- No synthetic inflation; no Phase 10; PHASE 8/9 gates/LKG intact
- MODEL_QUALITY_PRODUCTION_VALIDATED remains **false**

## 2026-09-27 — Real autonomous learning data growth (post–PHASE 9)

### Added
- `LearningCandidatePipeline` + SQLite candidate store (sanitize → secret/PII → quality → dedupe → provenance → accept)
- Multi-source observers: seeds, durable learning, coding, eval, owner feedback, tool/skill, corrected failures
- Dataset growth trigger (`TRAINING_MIN_NEW_EXAMPLES`) + tick loop: collect → version → decide → train
- Owner APIs: `/platform/learning/statistics`, `/dataset`, `/models`, `/feedback`, `/candidates/collect`
- Last training/rollback result persistence; Control Center learning stats
- Tests `test_v101_learning_data_growth.py`
- Docs: DATASET_PIPELINE updated

### Constraints preserved
- PHASE 8/9 gates, LKG, rollback, auth isolation, no per-chat training
- MODEL_QUALITY_PRODUCTION_VALIDATED remains **false**

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
