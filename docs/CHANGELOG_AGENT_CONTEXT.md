# Agent Context Changelog

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
