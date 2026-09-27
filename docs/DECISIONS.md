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
