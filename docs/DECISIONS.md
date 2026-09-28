# PFAI Decisions Log

## ADR-001 — Keep FastAPI monolith with embedded dashboard

- Status: Accepted
- Context: Uploaded PFAI 8.0 already ships API + static RTL dashboard together.
- Decision: Do not rewrite to Next.js/Vercel; keep FastAPI serving `static/index.html`.
- Consequences: Simpler deploy; CORS only needed if UI is hosted separately.

## ADR-002 — Do not target Vercel as primary host

- Status: Accepted
- Context: PFAI needs long-running process, local SQLite, continuous worker, code sandbox.
- Decision: Deploy as Docker on Render/Railway/VM.
- Consequences: Use existing Dockerfile + platform manifests; avoid serverless constraints.

## ADR-003 — Continuous training enabled, promotion always human-gated

- Status: Accepted (2026-09-27)
- Context: Operator wants continuous learning/training support, without unsafe production model swaps.
- Decision:
  - Keep `continuous_training.enabled=true` in config.
  - Allow force disable/enable via `PFAI_CONTINUOUS_TRAINING_ENABLED`.
  - Keep `auto_promote=False` and `require_human_approval=True` non-configurable from JSON.
  - Log cycle/training events to service event logs + owner ledger for gated actions.
- Consequences: Learning can run 24/7; production active model changes remain explicit.

## ADR-004 — Secrets only via environment / platform secret stores

- Status: Accepted
- Context: Anthropic key and owner secret must never appear in git, README real values, or chat.
- Decision: Document placeholders only; runtime reads env vars.
- Consequences: Deploy platforms must inject secrets; local `.env` is gitignored.

## ADR-007 — Coding Academy modular stack on existing sandbox

- Status: Accepted (2026-09-27)
- Context: Need full coding teacher/trainer/reviewer without rewriting PFAI.
- Decision:
  - Add `coding_*` modules + JSON curriculum under `configs/coding/`.
  - Reuse `SandboxedCodeEvaluator` for Python execution.
  - Wire Learning/Engineering modes; chat delegates coding intents to CodingAgent.
  - Anthropic optional; local/openai_compatible/Mock supported.
  - Training scaffold collects examples; no automatic production fine-tune.
- Consequences: Coding Academy dashboard + `/coding/*` APIs; existing code learning pipeline unchanged.

## ADR-006 — Command Chat Brain ↔ Heart via Tool Router

- Status: Accepted (2026-09-27)
- Context: Operator wants a central AI command chat that can operate PFAI safely.
- Decision:
  - Add CommandAgent + ToolRouter + CommandMemory + CommandAudit.
  - Heart access only through registered tool callbacks (no ad-hoc filesystem writes from the model).
  - Sensitive tools require Owner approval before execution.
  - Use Anthropic when `ANTHROPIC_API_KEY` is present; otherwise MockCommandProvider.
  - Phase-1 learning for chat = memory/feedback/approved knowledge/corrections — not automatic weight training.
- Consequences: Dashboard gains AI Command Chat; existing APIs remain intact.

## ADR-005 — Durable agent memory in docs/

- Status: Accepted (2026-09-27)
- Context: Original zip lacked AGENTS.md / docs / .cursor rules.
- Decision: Maintain project memory under `docs/` and `AGENTS.md` after meaningful changes.
- Consequences: Agents must update these files instead of relying on chat history.

## ADR-008 — Additive Orchestrator platform (no rewrite)

- Status: Accepted (2026-09-27)
- Context: Operator approved a 10-phase plan to grow PFAI into an Orchestrator platform while keeping FastAPI + RTL Dashboard and all existing features.
- Decision:
  - Add coordination contracts under `pfai.interfaces` and scaffold modules (`orchestrator`, `model_router`, `memory_system`, `knowledge_layer`, `task_planner`, `skills`, `self_check`, `self_heal`, `goal_system`).
  - Keep public HTTP contracts (`/health`, `/chat/*`, `/coding/*`, `/continuous/*`) and existing CommandAgent / CodingAgent paths.
  - Implement via adapters that wrap existing modules; do not delete or replace user-facing functionality.
  - Freeze phase order 1→10; do not skip ahead.
- Consequences: PHASE 1 ships interfaces + package layout + ADRs only; later phases fill scaffolds without forcing a framework rewrite.

## ADR-009 — ModelRouter roles; Local/Mock first; Anthropic optional

- Status: Accepted (2026-09-27)
- Context: Multiple providers already exist (Echo, openai_compatible, Anthropic, Mock). Platform must not hard-depend on Anthropic.
- Decision:
  - Introduce logical `ModelRole` values: `default`, `coding`, `reasoning`, `fast`, `vision`, `embedding`.
  - `ModelRouter` maps roles → existing `ModelProvider` implementations.
  - Prefer Local / openai_compatible / Mock / Echo when configured; Anthropic only when `ANTHROPIC_API_KEY` is present.
  - Never require Anthropic for core flows or tests.
- Consequences: Role config lands with PHASE 2 wiring; PHASE 1 defines the enum + router scaffold only.

## ADR-010 — Unified ToolPermission ladder with Owner Gate

- Status: Accepted (2026-09-27)
- Context: ToolRouter already uses `risk` + `requires_approval`. Skills/Orchestrator need a shared ladder.
- Decision:
  - Standardize `ToolPermission`: `READ`, `LOW_RISK_WRITE`, `HIGH_RISK_WRITE`, `PRODUCTION`, `SECRETS`, `DATA_DELETE`.
  - `HIGH_RISK_WRITE` and above require Owner Gate (existing approval flow).
  - Map existing ToolRouter specs onto this enum in PHASE 4; do not add a new auth system in early phases.
- Consequences: SkillRegistry scaffold already respects `requires_owner_gate()`; no new login/auth subsystem in PHASE 1.

## ADR-011 — No auto production fine-tune; no external deploy in platform phases until asked

- Status: Accepted (2026-09-27)
- Context: Continuous learning and training scaffolds exist; operator forbids silent weight promotion and premature external deploys during platform build-out.
- Decision:
  - Continuous learning may curate/evaluate; promotion stays human-gated (`auto_promote=False`).
  - Fine-tuning remains scaffold / offline pipeline only — never automatic on production.
  - Platform phases do not perform Vercel/Render/Railway/AWS deploys unless explicitly requested later.
  - No new authentication system in PHASE 1 (reuse Owner Gate header where needed).
- Consequences: Self-heal / eval phases must propose + approve; deploy docs remain informational only.

## ADR-012 — Long-Lived Adaptive AI Platform (20–30 year mission)

- Status: Accepted (2026-09-27)
- Context: Operator reframed PFAI from “production now” to a durable platform that must remain operable and evolvable for decades.
- Decision:
  - Treat PFAI as a Long-Lived Adaptive AI Platform: Durable, Modular, Portable, Auditable, Versioned, Recoverable, Extensible, Model-agnostic, Provider-agnostic.
  - Prefer ports/adapters over hard-wired vendors; document coupling in `docs/LONGEVITY.md`.
  - Keep FastAPI + Dashboard as the stable product surface; evolve internals behind interfaces.
- Consequences: Longevity work is phased; PHASE 1 is foundation (contracts/docs/scaffolds) only.

## ADR-013 — Replaceable Model / Provider / Embedding / Storage ports

- Status: Accepted (2026-09-27)
- Context: Today’s `app.py` branches on provider names; SQLite and Hash embeddings are concrete.
- Decision:
  - Define `ProviderRegistry`, `ModelRouter`, `EmbeddingPort`, `VectorStorePort`, `RelationalStorePort`, `StoragePort`, `BlobStorePort`, `ExportPort`.
  - Core must run with offline Echo/Mock/local; Anthropic and any closed API are optional adapters only.
  - Open-source/local models are first-class options.
- Consequences: Future model/DB/vector/host swaps happen by new adapters + migrations, not rewrites.

## ADR-014 — Model-agnostic Long-Term Memory

- Status: Accepted (2026-09-27)
- Context: Memory must survive model and vendor changes for decades.
- Decision:
  - Memory is structured, exportable data with kinds: episodic, semantic, procedural, user_preference, project_knowledge, learned_lesson, verified_knowledge, interaction_history.
  - Vector indexes are optional accelerators; textual/structured records remain authoritative.
  - Memory never stores secrets or depends on a specific LLM’s latent state.
- Consequences: LTM adapters wrap existing MemoryStore; export/import required for portability.

## ADR-015 — Safe Learning Pipeline (no unsupervised production corruption)

- Status: Accepted (2026-09-27)
- Context: Continuous learning exists; automatic weight changes in production are unacceptable.
- Decision:
  - Production learning path: Learning → Evaluation → Validation → Memory/Knowledge → Future Improvement.
  - Sources: experiences, task outcomes, feedback, errors, corrections, verified knowledge, successful workflows.
  - `allows_weight_mutation()` is False on Core safe pipeline; weight training stays offline/scaffolded + owner-gated.
- Consequences: Bad lessons can be rejected/rolled back; system cannot silently poison itself.

## ADR-016 — Knowledge / Config / Skill / Tool Versioning + Rollback

- Status: Accepted (2026-09-27)
- Context: Important knowledge and configs today lack uniform version metadata.
- Decision:
  - Versioned entities carry version, timestamp, source, confidence, status, provenance.
  - Rollback restores a prior version via audited re-activation (new version row), not silent rewrite.
  - Skills/tools keep prior versions invokable where feasible.
- Consequences: Enables safe evolution and recovery when a change proves harmful.

## ADR-017 — Schema Versioning + Migration Framework

- Status: Accepted (2026-09-27)
- Context: SQLite tables are created ad hoc (`CREATE TABLE IF NOT EXISTS`) without a platform schema number.
- Decision:
  - Introduce `PFAI_SCHEMA_VERSION` and `MigrationRunner` (dry-run default).
  - Every breaking storage change ships a numbered migration with upgrade (and downgrade when practical).
- Consequences: Database/engine swaps become planned migrations, not one-off scripts.

## ADR-018 — Backup, Restore, DR, and Portable Export

- Status: Accepted (2026-09-27)
- Context: BackupManager and DisasterRecovery exist but are file/SQLite-specific; export is incomplete.
- Decision:
  - Formalize Backup/Restore/DR ports over existing modules.
  - Require a portable export bundle (`pfai-export-v1`) so memory/knowledge are not locked to one provider or host.
- Consequences: Later phases flesh out full export contents; DR remains owner-aware for destructive restore.

## ADR-019 — Evaluation gates before adopting new versions

- Status: Accepted (2026-09-27)
- Context: Upgrades over decades need proof that old behavior still works.
- Decision:
  - Keep automated + regression tests as the first gate.
  - Add `VersionComparisonProtocol` to compare candidate vs baseline before promote.
  - Production-impacting promotes remain owner-gated.
- Consequences: Model/config/skill changes can be refused on measured regression.

## ADR-020 — Bounded Self-Heal + Future Compatibility Layer

- Status: Accepted (2026-09-27)
- Context: Self-healing without limits is a longevity hazard.
- Decision:
  - Heal loop: detect → diagnose → propose → apply_safe → test → rollback.
  - Irreversible/high-risk changes never auto-apply.
  - CompatibilityLayer tracks schema/provider/storage/python floors and guides upgrades of runtime, deps, DBs, model APIs, OS, and deploy environments.
  - Do not assume any current technology survives 20 years.
- Consequences: Diagnostics can be automatic; dangerous mutation cannot.

## ADR-021 — PHASE 2 Orchestrator + ProviderRegistry wiring

- Status: Accepted (2026-09-27)
- Context: Longevity PHASE 1 defined ports; operator approved PHASE 2 to implement Orchestrator and provider routing without vendor lock-in.
- Decision:
  - `ProviderRegistry` registers echo/mock/openai_compatible/anthropic; Anthropic remains optional and is never required for Core.
  - `ModelRouter.from_config` binds roles; missing API keys fall back to Echo.
  - `Orchestrator` coordinates CommandAgent, CodingAgent, Skills, LTM, Knowledge, Evaluation, Self-check/heal, Safe Learning.
  - Existing `/chat/*` and Dashboard stay the primary UX; additive `/orchestrate` + `/platform/*` expose the new layer.
  - Durable learning persists candidates + versioned knowledge + audit; `allows_weight_mutation()==False`; fine-tune only prepared via readiness metadata.
- Consequences: Platform is swappable at the provider boundary; learning is reversible and owner-gated for validation/store.

## ADR-022 — Owner authentication sessions + one-time setup

- Status: Accepted (2026-09-27)
- Context: Owner gate previously relied on sending a passcode via `X-Owner-Secret` and browser sessionStorage — unsafe for long-lived operation.
- Decision:
  - Extend `OwnerControl` with `OwnerAuthService` (sessions, rate-limit/lockout, first-time setup lock).
  - Store only password hashes (`pbkdf2_sha256$…` preferred; legacy sha256 accepted). Env: `PFAI_OWNER_USERNAME` + `PFAI_OWNER_PASSWORD_HASH` (email login/OTP removed).
  - HttpOnly cookie sessions (`pfai_owner_session`, SameSite=Strict; Secure always when `PFAI_ENV=production`, otherwise on HTTPS / `PFAI_COOKIE_SECURE=true`); legacy `X-Owner-Secret` header kept for automation.
  - First-time `/owner/setup` permanently disables itself via `owner_setup.lock`; no frontend-trusted roles.
  - Any password shared in development is considered compromised; require a new production hash before deploy.
  - Production requires HTTPS; private knowledge/regression reads are owner-gated; `/health`/`/system`/`/metrics` stay public observability.
- Consequences: Dashboard authenticates via login/setup UI without retaining plaintext secrets; owner APIs remain server-gated.

## ADR-023 — PHASE 3 deep LTM / Knowledge / Migration / Export

- Status: Accepted (2026-09-27)
- Context: PHASE 2 wired Orchestrator; LTM versions were in-memory, KnowledgeLayer ignored version store, migrations were dry-run only, export was empty scaffold.
- Decision:
  - Durable LTM versions in SQLite (`ltm_versions`) over a dedicated `MemoryStore`; kinds preserved across restarts; supersede/rollback audited.
  - `KnowledgeLayer` merges versioned knowledge + store + curriculum; publish/history/rollback via `KnowledgeVersionStore`.
  - `MigrationRunner` persists schema version; non-dry-run requires backup first; `PFAI_SCHEMA_VERSION=2` with registered longevity migration.
  - `ExportBundleScaffold` populates `pfai-export-v1` from live stores (no secrets); import dry-run default.
  - `PlatformEvaluation` adds longevity suites + durable baselines; compare still owner-gated for promote.
  - Additive owner-gated `/platform/ltm|knowledge/versions|eval|migrations|export*` routes; `/chat/*` + Dashboard unchanged.
- Consequences: Memory/knowledge are portable and versioned; schema upgrades are backup-gated; Core still never requires Anthropic or weight mutation.

## ADR-024 — PHASE 4 unified Planner/Tools authorization + versioned skills + bounded heal

- Status: Accepted (2026-09-27)
- Context: ToolRouter used legacy risk strings; SkillRegistry had no versions; TaskPlanner was a stub; self-heal mostly re-checked.
- Decision:
  - Introduce `ActionPermissionGate` + `AuthorizedExecutor` + authz audit (distinct from legacy escalation `PermissionGate` ledger).
  - Map ToolRouter risks → `ToolPermission`; HIGH_RISK_WRITE+ always needs explicit owner `approved=True` (server-side only).
  - Versioned `SkillRegistry` with activate/rollback + schema compatibility checks; handlers stay in-process.
  - Real `TaskPlanner` over ReasoningCore: capped steps/tool calls; forbidden unsafe actions; every step through AuthorizedExecutor.
  - Orchestrator `mode=plan` integrates memory/knowledge/eval/learn/tools/skills.
  - Self-heal: detect→diagnose→propose→owner approve→apply_safe→test→rollback; only registered safe actions; durable heal audit.
  - Providers: add `local` / `open_weight` readiness slots (Echo fallback); Anthropic remains optional.
  - Schema bump to **3** with backup-first migration for skill version tables.
  - Additive `/platform/plan|skills*|tools|heal*|authz/audit` routes; reuse owner auth; no weight training.
- Consequences: Privileged execution has one choke-point; skills/tools are versioned/rollback-capable; learning remains reversible and weight-free.

## ADR-025 — PHASE 5 Email OTP + real local/open-weight adapters + migration audit

- Status: Accepted (2026-09-27)
- Context: PHASE 4 delivered authz/planner/skills; owner login was passcode-only; local/open_weight were Echo placeholders; schema target 3 was pending at runtime 1 in some environments.
- Decision:
  - Add `EmailProvider` port (`MockEmailProvider`, `SMTPEmailProvider`) configured via env (`PFAI_EMAIL_PROVIDER`, `PFAI_SMTP_*`); no commercial vendor forced.
  - Owner Email OTP: cryptographically random, short-lived, single-use, PBKDF2-hashed at rest; resend cooldown + attempt limits; enumeration-resistant uniform responses; never log/return OTP; session via existing `pfai_owner_session` after verify. Passcode login + `X-Owner-Secret` preserved.
  - `LocalModelProvider` / `OpenWeightModelProvider` real OpenAI-compatible HTTP adapters with honest readiness (`Adapter implemented, runtime not connected.` when probe fails). Config via `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_ENDPOINT` / timeout/tokens/temperature.
  - MigrationRunner: intent/result audit, verify hook, backup-first, idempotent re-run, optional reversible downgrade (marker-safe). Schema target remains **3**.
  - Continuous learning stays memory/knowledge/eval only; `allows_weight_mutation()==False`; no deploy; no secrets in source.
- Consequences: Owner can authenticate via email OTP; local engines are pluggable without rewriting Orchestrator/Chat/Coding; schema upgrades are auditable and safe to re-run.


## ADR-026 — Autonomous model training isolated from system authority

- Status: Accepted (2026-09-27)
- Context: PHASE 5 deferred weight training. Operator approved PHASE 6 for real autonomous learning/training while preserving owner auth and zero-trust authorization.
- Decision:
  - Introduce `AutonomousTrainingOrchestrator` as the sole weight-training path: collect→sanitize→validate→dataset version→trigger→train→checkpoint→evaluate→shadow→activate→monitor→rollback.
  - `DurableSafeLearningPipeline.allows_weight_mutation()` remains False (knowledge/memory only). Training never writes auth, OTP, permissions, secrets, or migration safety.
  - Provider-independent `ModelTrainer` registry (`transformers_lora` real backend when stack present; `mock` tests-only and never labeled as real weight update).
  - Immutable dataset + model registries; backup-first schema **v4**; owner-gated `/platform/training/*`.
  - Honest runtime: `TRAINING_RUNTIME_UNAVAILABLE` when compute/training deps are missing — never fake success.
- Consequences: Platform can continuously improve models under gates; system authority remains unchanged by training.


## ADR-027 — Real training runtime integration + Skill Packs (PHASE 7)

- Status: Accepted (2026-09-27)
- Context: PHASE 6 delivered the autonomous training architecture; this environment lacked a real ML training stack. Operator approved connecting honest runtime detection, LoRA/QLoRA backends, skill packs, and a Learning Control Center without faking training success.
- Decision:
  - `TrainingRuntimeDetector` probes imports/hardware and returns AVAILABLE/PARTIALLY_AVAILABLE/UNAVAILABLE/INCOMPATIBLE/ERROR — never from config alone.
  - Real backend remains `TransformersLoRATrainer` / `RealLoRATrainingBackend`; mock only when explicitly allowed and never labeled as real weight updates.
  - Preflight: ModelCompatibilityChecker + TrainingResourceManager with blocked reasons.
  - Job lifecycle adds PREPARING/CHECKPOINTING/EVALUATING + stale RUNNING reconciliation after crash.
  - `ActiveModelRuntime` pointer switches on activate/rollback (not status-only).
  - Canary/shadow controls via env (`MODEL_CANARY_*`).
  - `SkillPackRegistry` versioned packs; skills cannot self-elevate permissions; still gated by AuthorizedExecutor.
  - Owner Control Center APIs + dashboard; schema **v5**.
- Consequences: When a real torch/transformers/peft/trl stack exists, training can execute for real; otherwise status remains honest UNAVAILABLE.

## ADR-028 — Real training runtime enablement + first verified LoRA run (PHASE 8)

- Status: Accepted (2026-09-27)
- Context: PHASE 7 reported RUNTIME_UNAVAILABLE and REAL_TRAINING_EXECUTED=false. Operator approved enabling a real training stack and proving one bounded LoRA pipeline without false claims.
- Decision:
  - Install path is explicit (`requirements-training.txt` / `python -m pfai.longevity.autonomous_training.setup_runtime`) — not silent, not AWS-coupled, not Anthropic/OpenAI-coupled.
  - `TrainingRuntimeDetector` reports AVAILABLE / PARTIAL / UNAVAILABLE with module/hardware reasons and a setup_path.
  - `RealLoRATrainingBackend` executes a real PEFT LoRA Trainer loop; returns `real_training` / `real_weight_update` only after adapter files + reload succeed.
  - Models require local `MODEL_PATH`/`MODEL_NAME` path or `MODEL_DOWNLOAD_APPROVED=true`; otherwise `NO_COMPATIBLE_MODEL`.
  - QLoRA only when CUDA + bitsandbytes present; otherwise honest failure.
  - Activation still requires evaluation + shadow + canary gates; training cannot mutate auth/OTP/permissions/secrets.
  - Control Center surfaces REAL_TRAINING_AVAILABLE / REAL_TRAINING_EXECUTED / REAL_MODEL_ACTIVE distinctly from mock test paths.
- Consequences: Environments with the training stack can run real LoRA; CI without ML deps still uses mock tests and must not claim REAL TRAINING VERIFIED.
